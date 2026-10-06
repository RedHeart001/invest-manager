"""热点 pipeline（P3 / PLAN M1）。

流程：
  1. 新闻抓取（R12 双源）：Tavily（经本地代理优先）→ 财联社电报 → 东财全球快讯
  2. 结构化为板块/概念标签：LLM 优先；未配置/不可用时关键词规则回退
  3. 板块成分映射：东财概念板 → 东财行业板 → 同花顺概念板（逐级降级）
  4. 产出 digest 回调 Next.js `/api/hotspots/ingest` 落库（data-service 不直连数据库）

R10：任何外部源失败都不阻塞整体，缺什么标注什么（degraded + note）。
R15：东财板块接口经源族限速器；板块名单内存缓存 6h。
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from typing import Any
from zoneinfo import ZoneInfo
from datetime import datetime

import requests

from ..config import load_env, search_api_key
from ..utils.limiter import get_limiter
from ..utils.timeout import run_with_timeout
from ..utils.timeutil import beijing_today
from . import llm_client

load_env()  # 读取 data-service/.env 与 ../web/.env（TAVILY_API_KEY 别名已统一）

# CR4（P3）：与 scheduler 一致使用北京时间（此前 finishedAt 用裸 datetime.now()）
TZ = ZoneInfo("Asia/Shanghai")

def _ak_guarded(fn, seconds: float = 45.0, name: str = "akshare"):
    """akshare 调用统一看门狗（C7，2026-09-13 code review 补）。

    akshare 内部 requests 无 timeout：上游节点挂死会让调用永久阻塞。在 hotspot
    pipeline 中的后果是 run_pipeline 不返回 → scheduler 的 _state["running"] 永久
    True → 后续定时/手动/启动补跑全部被拒（热点功能静默失效）。
    """
    value, err = run_with_timeout(fn, seconds, name)
    if err is not None:
        raise RuntimeError(f"{name} failed: {err}") from err
    return value


log = logging.getLogger("hotspot")

WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "http://localhost:3000")
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")

NEWS_LIMIT = 25
TOPIC_LIMIT = 5
BOARD_STOCKS_PER_TOPIC = 6

_EM = get_limiter("eastmoney")
_BOARD_CACHE_TTL = 6 * 3600
# names → [(板块名, 来源)]；codes → {板块名: {来源: "BKxxxx"}}（CR9-3a，同一时间戳同进同退）
_board_cache: dict[str, tuple[float, Any]] = {}


# ---------------- 1. 新闻抓取（R12 双源） ----------------


def _tavily(limit: int) -> list[dict]:
    key = search_api_key()
    if not key:
        raise RuntimeError("no search key")
    # 海外源：显式代理可用（R12），失败即降级
    proxies = None
    px = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if px:
        proxies = {"http": px, "https": px}
    s = requests.Session()
    s.trust_env = False
    try:

        def _query(query: str, days: int) -> list[dict]:
            r = s.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "topic": "news",
                    "days": days,
                    "max_results": limit,
                },
                proxies=proxies,
                timeout=25,
            )
            r.raise_for_status()
            out = []
            for it in (r.json() or {}).get("results", []):
                url = str(it.get("url", ""))
                out.append(
                    {
                        "title": str(it.get("title", "")).strip(),
                        "summary": str(it.get("content", "")).strip()[:200],
                        "url": url,
                        "time": str(it.get("published_date", "")),
                    }
                )
            return out

        # 扩大检索面：3 天窗口 + 两条查询合并去重（单查询常仅 3 条）
        merged: dict[str, dict] = {}
        for q, days in (
            ("今日 A股 市场热点 板块 政策", 1),
            ("股市 板块 领涨 热点", 3),
        ):
            try:
                for it in _query(q, days):
                    if it["title"] and it["url"] not in merged:
                        merged[it["url"]] = it
            except Exception as e:  # noqa: BLE001
                if not merged:
                    raise
                log.warning("tavily query %r failed: %s", q, e)
        out = list(merged.values())[:limit]
        if not out:
            raise RuntimeError("tavily empty")
        return out
    finally:
        # CR4（2026-09-15 review）：低频调用也显式关闭，避免连接句柄滞留
        s.close()


def _cls_telegraph(limit: int) -> list[dict]:
    """财联社电报（国内源，非东财域名族）。"""
    import akshare as ak

    df = _ak_guarded(ak.stock_info_global_cls, 45.0, "ak.stock_info_global_cls")
    if df is None or len(df) == 0:
        raise RuntimeError("cls empty")
    out = []
    for _, r in df.head(limit).iterrows():
        title = str(r.get("标题", "") or "").strip()
        content = str(r.get("内容", "") or "").strip()
        if not title and not content:
            continue
        out.append(
            {
                "title": title or content[:40],
                "summary": content[:200],
                "url": "",
                "time": f"{r.get('发布日期', '')} {r.get('发布时间', '')}".strip(),
            }
        )
    if not out:
        raise RuntimeError("cls unparsable")
    return out


def _em_global_news(limit: int) -> list[dict]:
    """东财全球财经快讯（东财域名族，经限速器）。"""
    import akshare as ak

    if not _EM.acquire(timeout=15):
        raise RuntimeError("eastmoney cooling down")
    try:
        df = _ak_guarded(ak.stock_info_global_em, 45.0, "ak.stock_info_global_em")
        _EM.on_success()
    except Exception:
        _EM.on_failure()
        raise
    if df is None or len(df) == 0:
        raise RuntimeError("em news empty")
    out = []
    for _, r in df.head(limit).iterrows():
        title = str(r.get("标题", "") or "").strip()
        if not title:
            continue
        out.append(
            {
                "title": title,
                "summary": str(r.get("摘要", "") or "").strip()[:200],
                "url": str(r.get("链接", "") or ""),
                "time": str(r.get("发布时间", "") or ""),
            }
        )
    if not out:
        raise RuntimeError("em news unparsable")
    return out


# ---------------- 1b. 新闻层多源合并（OPT-2／PLAN M8 那条「例外」，主人 10-04 给字"执行"） ----------------
#
# 源序＝东财 → 财联社 → Tavily。**与旧的 failover 反了方向**（旧的是"海外优先、国内兜底"）：
# 海外那条要么靠 key 要么靠代理，本机常态拿不到 ⇒ 一批新闻实际上常年只来自一家，
# 而"只有一家"在旧语义里恒等于 degraded ⇒ CR8-1 那条横幅天天亮。fusion 之后三家都尝试，
# 顺序只决定"同一条重复时先留下谁的"（择优另看 url/summary）。
NEWS_SOURCE_ORDER = ("eastmoney-news", "cls", "tavily")
# 跨源标题的相似度用**两道门槛各挡一种错**（二元组集合，同一把尺 `_bigrams`）：
#   · Jaccard（交集/并集）≥ 0.5 —— 挡"同板块的不同事件"（合成样本「地产链午后拉升」vs
#     「地产链龙头涨停」交集只有 2 个二元组，只看重合度也会被"地产链"这三个字骗过去）；
#   · 重合度（交集/较短那条）≥ 0.8 —— 容得下转发造成的变形（「央行宣布降准」vs
#     「【央行宣布降准】」的 Jaccard 只有 5/7≈0.71，单卡 Jaccard 会把同一条事件留成两条）。
# 两个条件都满足才判"同一条"。⚠️ 这对阈值只在**合成标题**上断言过（成对：前缀变形要合并 ⇔
# 同板块不同事件不许并 ⇔ 空标题不参与判定），**没有拿真新闻校准**——那属 `OPT-2` 前置实测，
# 欠一次真 pipeline；校准前不要调这两个数。
NEWS_DEDUPE_MIN_SIM = 0.5
NEWS_DEDUPE_MIN_OVERLAP = 0.8
# #43（CR9-71）：`nearMiss` 一次最多留几对。样本是"人工看"的东西，不是统计量——留得多不等于看得完。
NEAR_MISS_KEEP = 10

def _news_metrics(a: set[str], b: set[str]) -> tuple[float, float]:
    """两道门槛各自的比值 `(Jaccard, 重合度)`——**判据与样本共用这一把尺**，别在采集侧另算一次。

    任一侧为空 ⇒ `(0.0, 0.0)`：空标题既过不了任何一道门，也就不该在样本里出现（与 `_news_similar`
    原来的 `if not a or not b` 同义，`min()` 那个分母也因此不会碰到零）。
    """
    if not a or not b:
        return 0.0, 0.0
    inter = len(a & b)
    return inter / len(a | b), inter / min(len(a), len(b))


def _news_similar(a: set[str], b: set[str]) -> bool:
    """两个标题的二元组集合是否够判"同一条"（两道门槛都要过，理由见上面那对常数）。
    任一侧为空 ⇒ 不算相似：财联社那类只有摘要、没有标题的条目，宁可留下重复也不误并。"""
    sim, overlap = _news_metrics(a, b)
    return sim >= NEWS_DEDUPE_MIN_SIM and overlap >= NEWS_DEDUPE_MIN_OVERLAP


def _news_shortfall(sim: float, overlap: float) -> tuple[str, float] | None:
    """**恰好只过一道门槛**时返回 `(没过那道, 还差多少)`，否则 None——这就是 `nearMiss` 的排序依据。

    为什么用"没过那道还差多少"而不是"过了那道超出多少"：要判的是**漏并**（该合的没合），而漏并
    的特征正是"那道门槛差一点点"。反过来看超出量，排出来的会是"最像的没并"这种我们已经并掉的对。
    两道都过＝已经并了（进 `mergedPairs`）；两道都不过＝离阈值远，不是这一刀要看的。
    """
    ok_sim = sim >= NEWS_DEDUPE_MIN_SIM
    ok_over = overlap >= NEWS_DEDUPE_MIN_OVERLAP
    if ok_sim == ok_over:
        return None
    if ok_sim:
        return ("overlap", NEWS_DEDUPE_MIN_OVERLAP - overlap)
    return ("sim", NEWS_DEDUPE_MIN_SIM - sim)


def _news_better(cand: dict, kept: dict) -> bool:
    """重复条目的择优：**有链接优先于没链接**（CR8-3「相关文章」能不能出东西就靠这条，
    而财联社电报的 `url` 恒空），其次摘要更长的优先。
    两条规则的顺序不能反：先比链接再比长度，否则会出现"摘要长但没链接的那条把带链接的顶掉"。
    """
    has_url_new = bool(cand.get("url"))
    has_url_kept = bool(kept.get("url"))
    if has_url_new != has_url_kept:
        return has_url_new
    return len(cand.get("summary") or "") > len(kept.get("summary") or "")


def merge_news(attempts: list[dict], limit: int = NEWS_LIMIT) -> dict:
    """OPT-2 刀 1：多源并集 → 跨源标题去重（择优留一条）→ 覆盖面自述。**纯函数**，不碰网络也不碰限流器。

    入参＝`[{"source": 名, "items": list|None, "error": str|None}]`，顺序即源序（重复条目
    先留下靠前那家的字段组合，再按 url/summary 择优）。返回 `{items, sources, source, missing,
    degraded, note, stats}`：
      · `items` 每条带 `via`＝这一条由哪几家供的（可能不止一家）；
      · `sources`＝**到货**的源（`error` 为空的），`source`＝主源＝`sources[0]`；
      · `degraded` **只在降到单源或零源时才真**——多源到手是 fusion 的设计常态，缺一家不算降级，
        否则 CR8-1 刚治掉的"降级横幅天天亮"会原样回来；缺的那几家仍进 `note`（⇒ `reasons[]`
        的 news 条目），说话与报警是两件事。

    `stats`（#34／CR9-62）＝**不受"有没有缺源"约束的那份计数**。`note` 只在缺源时才说话
    （三家齐走 `else: note=None`），于是"合并前逐源几条"这个 `OPT-2` 前置实测 ② 真正要的数字
    恰好在看不到——满配那一轮最该有样本，却一个字都不留。计数因此独立成键、每轮都在：
      · `perSource`＝各家**交来多少行**（合并前、按源分列，就是缺的那个"分母"）；
      · `raw = sum(perSource)`，恒等式 `raw == blank + kept + mergedAway`（拿去校准阈值时先查这条）；
      · `kept`＝并集大小（**截断前**）、`truncated`＝被 `NEWS_LIMIT` 切掉的那部分，
        两者相加才等于 `items` 的条数——note 里"去重后 N 条"报的是截断**后**，别看混；
      · `crossSource`＝`via` 跨了 ≥2 家的条目数，**这才是 0.5/0.8 那两道门槛真正作用的对象**
        （同一家内的重复不需要阈值）。
    `samples`（#43／CR9-71）＝**给那两道阈值校准用的成对标题**，与 `stats` 同住、同样不上屏：
      · `mergedPairs`＝真的并掉了哪一对（`incumbent`／`incoming` 两条标题＋两侧来源＋`sim`/`overlap`
        ＋`survivor`＝择优之后活下来的是哪一条），条数恒等于 `stats.mergedAway`；
      · `nearMiss`＝**只过了一道门槛**的那些对里、按"没过那道还差多少"最小的前 `NEAR_MISS_KEEP` 条，
        另带 `nearMissTotal`（实采多少）——**只有 `mergedPairs` 答不了"该合的没合"**：恒等式在漏并时
        两边照样自洽，所以这一档才是"0.5/0.8 该不该动"的真正原料。每对都带两侧来源，因为同家与跨家
        走的是同一把尺（`_news_similar` 不分家），要只看跨源的那一档由 `incomingVia` 判、不靠这里预设。
    **计数只留在这份结构里、不进 `note`**（主人 10-05 的字＝"合并前／并掉几条"这类数对用户没用，
    属面向开发者的数据）⇒ note 维持"几家到货、去重后几条、未到货是谁"，两者各说各的话。
    """
    arrived = [str(a.get("source") or "?") for a in attempts if not a.get("error")]
    missing = [f"{a.get('source')}（{a.get('error')}）" for a in attempts if a.get("error")]

    per_source: dict[str, int] = {}
    blank = 0
    merged_away = 0
    kept: list[dict] = []
    # #43（CR9-71）：阈值校准要的原料。`mergedPairs`＝真的并掉了哪一对，`nearMiss`＝**差一点就并**的那一档。
    # 只有前者看不见漏并（恒等式 `raw==blank+kept+mergedAway` 在"该合的没合"时照样自洽）。
    merged_pairs: list[dict] = []
    near_all: list[dict] = []
    for a in attempts:
        name = str(a.get("source") or "?")
        if a.get("error"):
            continue
        rows = a.get("items") or []
        per_source[name] = per_source.get(name, 0) + len(rows)
        for raw in rows:
            title = str(raw.get("title", "") or "")[:120]
            summary = str(raw.get("summary", "") or "")[:200]
            if not title and not summary:
                blank += 1
                continue
            cand = {
                "title": title,
                "summary": summary,
                "url": str(raw.get("url", "") or ""),
                "time": str(raw.get("time", "") or ""),
                "via": [name],
            }
            grams = _bigrams(cand["title"])
            # 单次扫描：命中即 `break` ⇒ 代表条目仍是"第一个过门槛的那条"，与旧的 `next(...)` 同形。
            # 未命中的那些比较顺手量一次短板（`nearMiss` 的原料），不另起第二轮循环＝不加一份成本。
            hit: int | None = None
            hit_ratios: tuple[float, float] = (0.0, 0.0)
            best_gap: float | None = None
            best_near: dict | None = None
            for i, k in enumerate(kept):
                sim, overlap = _news_metrics(grams, k["_grams"])
                if sim >= NEWS_DEDUPE_MIN_SIM and overlap >= NEWS_DEDUPE_MIN_OVERLAP:
                    hit, hit_ratios = i, (sim, overlap)
                    break
                gap = _news_shortfall(sim, overlap)
                if gap is not None and (best_gap is None or gap[1] < best_gap):
                    best_gap = gap[1]
                    best_near = {
                        "incumbent": k["title"],
                        "incoming": cand["title"],
                        "incumbentVia": list(k["via"]),
                        "incomingVia": name,
                        "sim": round(sim, 3),
                        "overlap": round(overlap, 3),
                        "failed": gap[0],
                        "shortfall": round(gap[1], 4),
                    }
            if hit is None:
                if best_near is not None:
                    near_all.append(best_near)
                kept.append({**cand, "_grams": grams})
                continue
            merged_away += 1
            group = kept[hit]
            incumbent_via = list(group["via"])
            incumbent_title = group["title"]
            if name not in group["via"]:
                group["via"].append(name)
            take = _news_better(cand, group)  # 择优：换掉代表条目，但 `via` 要累计
            if take:
                kept[hit] = {**cand, "via": list(group["via"]), "_grams": grams}
            merged_pairs.append({
                "incumbent": incumbent_title,
                "incoming": cand["title"],
                "incumbentVia": incumbent_via,
                "incomingVia": name,
                "sim": round(hit_ratios[0], 3),
                "overlap": round(hit_ratios[1], 3),
                # 活下来的标题是哪一条：`mergedAway` 把"并掉"与"换了代表"混在同一个数里，
                # 不写这一格，样本会让人以为被吞的那条总是输家。
                "survivor": "incoming" if take else "incumbent",
            })

    items = [{k: g[k] for k in ("title", "summary", "url", "time", "via")} for g in kept[:limit]]
    stats = {
        "attempted": len(attempts),
        "arrived": len(arrived),
        "perSource": per_source,
        "raw": sum(per_source.values()),
        "blank": blank,
        "kept": len(kept),
        "mergedAway": merged_away,
        "truncated": max(0, len(kept) - limit),
        "crossSource": sum(1 for g in kept if len(g["via"]) > 1),
    }
    degraded = len(items) == 0 or len(arrived) <= 1
    # #43（CR9-71）：样本。`nearMiss` 按"没过那道还差多少"升序取前 `NEAR_MISS_KEEP` 对，
    # 排序带上标题兜底⇒同一批输入两次跑出来的顺序可复现（否则三天后没法比这两枚样本）。
    near_sorted = sorted(
        near_all, key=lambda d: (d["shortfall"], d["incumbent"], d["incoming"])
    )[:NEAR_MISS_KEEP]
    samples = {
        # 阈值随样本一起写：这两个数哪天变了，样本才不会失去解释。
        "thresholds": {"minSim": NEWS_DEDUPE_MIN_SIM, "minOverlap": NEWS_DEDUPE_MIN_OVERLAP},
        "nearMissKeep": NEAR_MISS_KEEP,  # 上限
        "nearMissTotal": len(near_all),  # 实采多少——与 `nearMiss` 的条数不同形，别当截断没发生
        "mergedPairs": merged_pairs,  # 条数恒等于 `stats.mergedAway`（断言锁住）
        "nearMiss": near_sorted,
    }
    if not items:
        note = "全部新闻源不可用" + (f"（{'；'.join(missing)}）" if missing else "")
    elif missing:
        note = (
            f"新闻多源合并：{len(arrived)}/{len(attempts)} 家到货（{'、'.join(arrived)}）、"
            f"去重后 {len(items)} 条；未到货：{'；'.join(missing)}"
        )
    else:
        note = None
    return {
        "items": items,
        "sources": arrived,
        "source": arrived[0] if arrived else "none",
        "missing": missing,
        "degraded": degraded,
        "note": note,
        "stats": stats,
        # #43（CR9-71）：与 `stats` 同一条路（进 `lastResult` → 状态位文件），**不进 note、不进 payload**
        "samples": samples,
    }


def fetch_news(limit: int = NEWS_LIMIT, deadline: float | None = None) -> dict:
    """R15「例外」＋R12：新闻层走 **fusion**（OPT-2 刀 2）＝按 `NEWS_SOURCE_ORDER` **逐源全部尝试**，
    不再"任一源成功即返回"，成功项交给 `merge_news` 并集去重择优。

    ⚠️ 代价要说清（10-04 08:2x 实测 ② 之后改过一次，原来那句"每次必调"说满了）：东财新闻从此**每次
    pipeline 必尝试**，而它与板块成分/快照同抢一个 `eastmoney` 桶（`_em_global_news` 里那次
    `_EM.acquire(timeout=15)`）。被拒分两种形态、代价不同：桶在**冷却期**时 `acquire` 立刻返回 False
    （不等待、不出网，代价＝这一家缺席、原因写进 note），只有**令牌紧而没熔断**时才会等到超时。
    "必调之后令牌获取率掉多少"＝`OPT-2` 前置实测 ②：真 pipeline 跑过一次，拿到的 `granted=12 denied=62`
    是**整轮集成门禁的合计**（p1/p2/p5 同窗也在打东财族），与"还没有 fusion"时那枚不构成对照 ⇒ **不动桶参数**
    （读码阶段不猜），四条缓解方向（缩短超时／拿不到先跳过最后补／重排调用顺序／微调桶）等一个能归因的数字。

    `deadline` 仍是硬预算（CR-16）：到点就停止尝试后面的源，**已到货的部分照常合并**——
    旧实现在这里只能整批放弃或整批来自一家，fusion 之后"跑到第几家算第几家"。
    """
    fns = {"eastmoney-news": _em_global_news, "cls": _cls_telegraph, "tavily": _tavily}
    attempts: list[dict] = []
    for name in NEWS_SOURCE_ORDER:
        if deadline is not None and time.monotonic() > deadline:
            attempts.append({"source": name, "items": None, "error": "pipeline 预算已尽，未尝试"})
            continue
        if name == "tavily" and not search_api_key():
            # 没配 key 不是"上游挂了"，写成人看得懂的一句（旧实现把它当降级说明拼进 note）
            attempts.append({"source": name, "items": None, "error": "未配置 SEARCH_API_KEY"})
            continue
        try:
            items = _ak_guarded(lambda f=fns[name]: f(limit), 45.0, "news-source")
        except Exception as e:  # noqa: BLE001 单源失败不许拖垮整批（R10）
            attempts.append({"source": name, "items": None, "error": f"{type(e).__name__}: {str(e)[:80]}"})
            continue
        attempts.append({"source": name, "items": items, "error": None})
    return merge_news(attempts, limit=limit)


# ---------------- 2. 板块名单（EM → THS 降级 + 缓存） ----------------

# 关键词匹配用的黑名单：非主题类宽泛板块（避免"融资融券/深股通"等噪声误命中）
_BOARD_BLACKLIST = (
    "融资", "融券", "标普", "MSCI", "富时", "深股通", "沪股通", "同花顺",
    "破净", "预盈", "预亏", "ST", "次新", "高价", "低价", "超跌", "举牌",
    "转债", "B股", "H股", "GDR", "CDR", "注册制", "两融",
)


def _pick_col(df, *candidates: str):
    """按候选列名取值（兼容中英文列名差异）。"""
    for c in candidates:
        if c in df.columns:
            return df[c]
    return df.iloc[:, 0]


# CR9-3(a)：东财板块代码形态（BK + 数字）。名单表里混着 "-"、空串和别的源族的编码，
# 只有这个形态能喂给 *_cons_em 走短路，其余一律按名称回退。
_BK_RE = re.compile(r"BK\d{3,8}$", re.IGNORECASE)


def _board_names() -> list[tuple[str, str]]:
    """返回 [(板块名, 来源)]：EM 概念+行业 → 新浪行业+概念 → THS 概念。

    与成分映射源保持一致性：东财不可用时优先用新浪名单（映射同源，命中即可得成分）。
    顺带把 名称→板块代码 记进 `_board_cache["codes"]`（CR9-3(a)，见 `_board_code`）。
    """
    cached = _board_cache.get("names")
    if cached and time.time() - cached[0] < _BOARD_CACHE_TTL:
        return cached[1]

    boards: list[tuple[str, str]] = []
    codes: dict[str, dict[str, str]] = {}
    import akshare as ak

    if _EM.acquire(timeout=15):
        try:
            for fn, tag in (
                (ak.stock_board_concept_name_em, "em-concept"),
                (ak.stock_board_industry_name_em, "em-industry"),
            ):
                df = _ak_guarded(fn, 45.0, "board-name-list")
                name_col = _pick_col(df, "板块名称", "name").tolist()
                code_col = _pick_col(df, "板块代码", "code").tolist()
                for raw_name, raw_code in zip(name_col, code_col):
                    n = str(raw_name).strip()
                    # 旧实现是 `series.dropna()`：pandas 同时丢 NaN 与 None，改成逐行判断后
                    # 这两个占位值会以字符串形式漏进来，必须一并按名字滤掉（否则会进关键词表）。
                    if not n or n.lower() in ("nan", "none"):
                        continue
                    boards.append((n, tag))
                    c = str(raw_code).strip()
                    if _BK_RE.fullmatch(c):
                        codes.setdefault(n, {})[tag] = c.upper()
            _EM.on_success()
        except Exception as e:  # noqa: BLE001
            _EM.on_failure()
            log.warning("em board names failed: %s", e)

    if not boards:
        sina_map = _sina_sector_map()
        boards.extend((name, "sina") for name in sina_map.keys())

    if not boards:
        try:
            df = _ak_guarded(ak.stock_board_concept_name_ths, 45.0, "ak.stock_board_concept_name_ths")
            series = _pick_col(df, "概念名称", "name")
            boards.extend(
                (str(x).strip(), "ths-concept")
                for x in series.dropna().tolist()
                if str(x).strip()
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ths board names failed: %s", e)

    if boards:
        now = time.time()
        _board_cache["names"] = (now, boards)
        # 东财不可用时 codes 为空 dict —— 映射自动按名称回退（原行为）
        _board_cache["codes"] = (now, codes)
    return boards


def _board_code(board: str, source: str) -> str | None:
    """板块名 → 该东财源（em-concept / em-industry）下的 BK 板块代码；取不到返回 None。

    **CR9-3(a)（2026-09-26 拍板深度 (a)）——省下的是百次级扇出**：
    `stock_board_*_cons_em(symbol=名称)` 会先重拉整张板块映射表。09-27 00:1x 在 requests
    层计数实证：传名称 **9 个东财请求**（`fs=m:90+t:3`，横跨 push2 全家族），传 BK 代码
    **1 个请求**（`fs=b:BKxxxx`）。一次 pipeline 最多 10 次映射、每次概念+行业两条 ⇒ 名义
    10 次 `acquire` 实际可发 180 次 HTTP——这正是 CR7-7"stock 熔断连坐 hk"的真正来源，
    也是 C29"按逻辑请求计次"口径与真实额度的量级差。
    名单未缓存/非东财源/代码形态不符时按名称请求，行为与改动前一致。
    """
    entry = _board_cache.get("codes")
    if not entry or time.time() - entry[0] >= _BOARD_CACHE_TTL:
        _board_names()  # 名单与代码同批取回；6h TTL ⇒ warming 每天个位数
        entry = _board_cache.get("codes")
    if not entry:
        return None
    return entry[1].get(board, {}).get(source)


def _keyword_board_names() -> list[str]:
    """关键词匹配候选：过滤黑名单与非主题噪声，长名优先。"""
    names = [n for n, _ in _board_names()]
    names = [
        n
        for n in names
        if len(n) >= 2 and not any(b in n for b in _BOARD_BLACKLIST)
    ]
    names.sort(key=len, reverse=True)
    return names


# ---------------- 3. 结构化（LLM 优先 → 关键词回退） ----------------

_LLM_SYSTEM = (
    "你是 A股市场热点分析助手。输入若干条财经新闻，输出 JSON："
    '{"topics":[{"title":"热点标题(≤20字)","summary":"一句话解读(≤80字)",'
    '"boards":["相关板块或概念名(用A股常用板块名)"]}]}'
    "。要求：最多 5 条，按重要性排序；boards 用简短通用板块名（如 光伏、储能、半导体、创新药）。"
)


def structure_topics(news_items: list[dict], deadline: float | None = None) -> dict:
    if not news_items:
        return {"topics": [], "engine": "none", "note": "无新闻可结构化"}

    headlines = "\n".join(
        f"{i + 1}. {it['title']}｜{it.get('summary', '')[:80]}"
        for i, it in enumerate(news_items[:20])
    )
    # CR-16：LLM 结构化的超时取"剩余预算"（默认 60s 上限），不越过 pipeline deadline。
    remaining = None
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            # 预算已尽：直接走关键词回退（不调用 LLM）
            llm = None
        else:
            llm = llm_client.chat_json(_LLM_SYSTEM, headlines, timeout=min(60.0, remaining))
    else:
        llm = llm_client.chat_json(_LLM_SYSTEM, headlines)
    if isinstance(llm, dict) and isinstance(llm.get("topics"), list) and llm["topics"]:
        topics = []
        for t in llm["topics"][:TOPIC_LIMIT]:
            if not isinstance(t, dict) or not t.get("title"):
                continue
            boards = [str(b).strip() for b in (t.get("boards") or []) if str(b).strip()]
            topics.append(
                {
                    "title": str(t["title"])[:60],
                    "summary": str(t.get("summary", ""))[:200],
                    "boards": boards[:4],
                }
            )
        if topics:
            return {"topics": topics, "engine": "llm", "note": None}

    # 关键词规则回退：用板块名单在标题/摘要中匹配
    topics = _keyword_topics(news_items)
    note = (
        "LLM 未配置或不可用，已使用关键词规则结构化（板块名匹配）"
        if topics
        else "LLM 不可用且关键词未命中板块"
    )
    # 兜底：关键词命中不足时，用当日涨幅居前板块补位（新浪源，仍走成分映射，保证不空白）
    if len(topics) < 2:
        hot = _sina_hot_topics(3)
        existing = {b for t in topics for b in t["boards"]}
        hot = [h for h in hot if h["boards"][0] not in existing]
        if hot:
            topics = topics + hot[: max(0, TOPIC_LIMIT - len(topics))]
            note += "；关键词命中不足，已用当日涨幅居前板块兜底（新浪源）"
    return {
        "topics": topics,
        "engine": "keyword",
        "note": note if topics else "关键词与涨幅兜底均未产出热点",
    }


def _keyword_topics(news_items: list[dict], limit: int = TOPIC_LIMIT) -> list[dict]:
    names = _keyword_board_names()
    topics: list[dict] = []
    used: set[str] = set()
    for it in news_items:
        text = f"{it.get('title', '')} {(it.get('summary', '') or '')[:400]}"
        hit = [n for n in names if n in text][:2]
        if not hit:
            continue
        key = hit[0]
        if key in used:
            continue
        used.add(key)
        topics.append(
            {
                "title": it.get("title", "")[:60],
                "summary": (it.get("summary", "") or "")[:200],
                "boards": hit,
            }
        )
        if len(topics) >= limit:
            break
    return topics


# ---------------- 4. 板块成分映射（东财 → 新浪降级） ----------------

_SINA_TTL = 6 * 3600
_sina_cache: dict = {}


def _sina_sector_map() -> dict[str, tuple[str, float | None]]:
    """新浪行业+概念板块：中文名 → (sector label, 涨跌幅%)（缓存 6h，非东财域名族）。"""
    cached = _sina_cache.get("map")
    if cached and time.time() - _sina_cache.get("ts", 0) < _SINA_TTL:
        return cached

    import akshare as ak

    mapping: dict[str, tuple[str, float | None]] = {}
    for indicator in ("行业", "概念"):
        try:
            df = _ak_guarded(lambda: ak.stock_sector_spot(indicator=indicator), 45.0, "ak.stock_sector_spot")
            label_series = _pick_col(df, "label")
            name_series = _pick_col(df, "板块", "名称")
            pct_series = _pick_col(df, "涨跌幅")
            for label, name, pct in zip(label_series, name_series, pct_series):
                n = str(name).strip()
                if not n or n in mapping:
                    continue
                # CR4（2026-09-15 review）：裸 float() 拦不住 NaN → "+nan%" 污染热点标题。
                # 用 isfinite 过滤非有限值。
                try:
                    f = float(pct)
                    pct_val: float | None = f if math.isfinite(f) else None
                except (TypeError, ValueError):
                    pct_val = None
                mapping[n] = (str(label).strip(), pct_val)
        except Exception as e:  # noqa: BLE001
            log.warning("sina sector list failed (%s): %s", indicator, e)
    if mapping:
        _sina_cache["map"] = mapping
        _sina_cache["ts"] = time.time()
    return mapping


def _sina_board_products(board: str, limit: int) -> dict:
    """新浪板块成分（名称精确 → 包含匹配）。"""
    import akshare as ak

    mapping = _sina_sector_map()
    if not mapping:
        return {"stocks": [], "source": "none", "note": f"新浪板块列表不可用，无法映射「{board}」"}

    label = mapping.get(board)
    matched = board
    if label is None:
        cands = sorted(
            (n for n in mapping if board in n or n in board), key=len
        )
        if cands:
            matched = cands[0]
            label = mapping[matched]
    if label is None:
        return {"stocks": [], "source": "none", "note": f"新浪板块名称未匹配「{board}」"}
    try:
        df = _ak_guarded(lambda: ak.stock_sector_detail(sector=label[0]), 45.0, "ak.stock_sector_detail")
        code_series = _pick_col(df, "code", "代码")
        name_series = _pick_col(df, "name", "名称")
        stocks = [
            {"code": str(c).strip(), "name": str(n).strip()}
            for c, n in zip(code_series.head(limit), name_series.head(limit))
        ]
        if stocks:
            return {"stocks": stocks, "source": f"sina·{matched}", "note": None}
    except Exception as e:  # noqa: BLE001
        log.warning("sina sector detail failed (%s): %s", label[0], e)
    return {"stocks": [], "source": "none", "note": f"新浪板块「{board}」成分获取失败"}


def _sina_hot_topics(limit: int = 3) -> list[dict]:
    """当日涨幅居前板块（新浪源）——关键词未命中时的兜底热点（数据驱动，仍走成分映射）。"""
    mapping = _sina_sector_map()
    scored = [
        (name, entry[1])
        for name, entry in mapping.items()
        if entry[1] is not None
        and len(name) >= 2
        and not any(b in name for b in _BOARD_BLACKLIST)
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    out = []
    for name, pct in scored[:limit]:
        out.append(
            {
                "title": f"板块异动：{name}领涨（+{pct:.2f}%）",
                "summary": f"当日涨幅居前板块（新浪源 +{pct:.2f}%），成分股见相关产品；盘中/收盘快照，仅供参考。",
                "boards": [name],
            }
        )
    return out


def map_board_products(board: str, limit: int = BOARD_STOCKS_PER_TOPIC) -> dict:
    """板块成分映射：东财概念板 → 东财行业板 → 新浪行业/概念板（R15 多源降级）。"""
    import akshare as ak

    if _EM.acquire(timeout=15):
        for fn, tag in (
            (ak.stock_board_concept_cons_em, "em-concept"),
            (ak.stock_board_industry_cons_em, "em-industry"),
        ):
            # CR9-3(a)：知道 BK 代码就按代码请求（1 个 HTTP），否则按名称（实测 9 个）。
            sym = _board_code(board, tag) or board
            try:
                df = _ak_guarded(lambda: fn(symbol=sym), 45.0, "board-constituents")
                if df is None or len(df) == 0:
                    continue
                code_series = _pick_col(df, "代码", "code")
                name_series = _pick_col(df, "名称", "name")
                stocks = [
                    {"code": str(c).strip(), "name": str(n).strip()}
                    for c, n in zip(code_series.head(limit), name_series.head(limit))
                ]
                _EM.on_success()
                if stocks:
                    return {"stocks": stocks, "source": tag, "note": None}
            except Exception as e:  # noqa: BLE001
                _EM.on_failure()
                log.warning("board cons failed (%s %s→%s): %s", tag, board, sym, e)
                break  # 熔断已触发，转新浪备源

    sina = _sina_board_products(board, limit)
    if sina["stocks"]:
        return sina
    return {
        "stocks": [],
        "source": "none",
        "note": sina.get("note") or f"板块「{board}」成分全源不可用",
    }


# ---------------- 5. 组装与回调 ----------------


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text)
    return {t[i : i + 2] for i in range(len(t) - 1)}


def _topic_urls(topic: dict, news_items: list[dict], limit: int = 3) -> list[dict]:
    """CR4（P3）：按 topic 相关性挑选来源链接——此前所有 topic 都取相同的前 3 条
    新闻 URL（与各自 topic 无关联）。用 topic 标题+板块名的字二元组与新闻
    title+summary 的重叠数打分取前 N；无命中时回退首 N 条（与旧行为一致）。

    CR8-3：返回 `{url, title}` 而不是裸 URL。打分环节（下面 `text`）本来就持有
    `n["title"]`，旧实现在 `return` 那一步把它丢掉 ⇒ 前端只能渲染无差别的「原文」，
    标题在链路上任何一处都再也拿不回来。财联社电报条目写死 `url=""`，被 `if` 滤掉
    （所以 cls 批次的「相关文章」仍为空，这是来源本身没有链接，不是本层的缺陷）。
    """
    key = " ".join([str(topic.get("title", "")), *[str(b) for b in topic.get("boards", [])]])
    grams = _bigrams(key)
    scored: list[tuple[int, dict]] = []
    for n in news_items:
        text = f"{n.get('title', '')} {n.get('summary', '')}"
        score = len(grams & _bigrams(text))
        if score > 0:
            scored.append((score, n))
    scored.sort(key=lambda x: -x[0])
    picked = scored[:limit] if scored else [(0, n) for n in news_items[:limit]]
    return [
        {"url": str(n["url"]), "title": str(n.get("title", ""))[:120]}
        for _, n in picked
        if n.get("url")
    ]


def build_items(
    topics: list[dict], news_meta: dict, deadline: float | None = None
) -> tuple[list[dict], list[str]]:
    """CR6-P2-3：board 映射最坏可达 ~900s（5 topic × 2 board × 2 源 × 45s），
    `run_pipeline` 此前无整体超时 → `_state["running"]` 长期占用、所有触发被拒。
    此处接收 deadline，每轮 board 循环开头检查；超时即停止后续映射，但**每个 topic
    仍产出**（只是未完成成分映射），并在 note 标注降级。
    """
    notes: list[str] = []
    items: list[dict] = []
    timed_out = False
    for t in topics:
        related: list[dict] = []
        board_notes: list[str] = []
        for board in t.get("boards", [])[:2]:
            # 已超时：不再调用外部映射（这是唯一的重活），该 topic related 留空
            if deadline is not None and time.monotonic() > deadline:
                timed_out = True
                break
            mapped = map_board_products(board)
            if mapped["note"]:
                board_notes.append(mapped["note"])
            related.extend(
                {"type": "stock", "code": s["code"], "name": s["name"], "board": board}
                for s in mapped["stocks"]
            )
        if board_notes:
            notes.extend(board_notes)
        items.append(
            {
                "title": t["title"],
                "summary": t.get("summary", ""),
                "boardTags": t.get("boards", []),
                "sourceUrls": _topic_urls(t, news_meta["items"]),
                "relatedCodes": related[:12],
            }
        )
    if timed_out:
        notes.append("pipeline 超时，部分 topic 未完成成分映射")
    return items, notes


def emit_ingest(payload: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if INGEST_TOKEN:
        headers["x-ingest-token"] = INGEST_TOKEN
    r = requests.post(
        f"{WEB_BASE_URL}/api/hotspots/ingest", json=payload, headers=headers, timeout=30
    )
    r.raise_for_status()
    return r.json()


def run_pipeline(trigger: str = "manual") -> dict:
    started = time.time()
    # CR6-P2-3：整体超时预算（env 可覆盖，默认 300s）。主要约束 build_items 的
    # board 映射（最坏 ~900s）。保证最坏情况下 _state["running"] 有限期释放。
    try:
        timeout_s = float(os.environ.get("HOTSPOT_PIPELINE_TIMEOUT_S", "300"))
    except ValueError:
        timeout_s = 300.0
    deadline = time.monotonic() + timeout_s
    news = fetch_news(deadline=deadline)
    struct = structure_topics(news["items"], deadline=deadline)
    items, board_notes = build_items(struct["topics"], news, deadline=deadline)
    # CR8-1：旧实现把三件不相干的事 OR 成一个 `degraded`、再把三类 note 拼成一条
    # ≤500 字串，`web` 侧于是逐卡渲染「降级产出」横幅（一张卡一条、同批互相重复）。
    # 现在按成因分类，只有 ①② 进入落库契约：
    #   news   ① 新闻源降级（本机网络下是常态，产出可用）
    #   engine ② 结构化引擎退化（真实能力损失；`struct["note"]` 已是它的成因文案）
    #   board  ③ 板块名映射未命中（几乎每轮都有，纯噪声）⇒ 不再参与 `degraded`/`note`，
    #          只留在运行结果 `reasons` 里供排查（"看不见的降级"由这条兜住）
    # ① 的消灭（源序反转＋fusion）已随 `OPT-2` 落地（10-04）：现在缺一家是常态、不算降级，
    #    只有降到**单源或零源**才把 `degraded` 点亮——所以这条 reasons 仍存在，但它是"说明"不是"报警"。
    reasons: list[dict] = []
    if news.get("note"):
        reasons.append({"kind": "news", "text": str(news["note"])})
    if struct.get("note"):
        reasons.append({"kind": "engine", "text": str(struct["note"])})
    for n in board_notes:
        reasons.append({"kind": "board", "text": str(n)})
    shown = [r["text"] for r in reasons if r["kind"] != "board"]
    payload = {
        # CR-06：digest 日期统一北京时间（与 web 侧 dayStart/beijingToday 同口径）
        "date": beijing_today(),
        "trigger": trigger,
        "engine": struct["engine"],
        # OPT-2 刀 1：`newsSource` 单值 → **`newsSources` 数组**（fusion 之后"这批来自哪家"
        # 本来就可能是多家）。库里那一列仍是 `String?`，web 侧写成 JSON 文本、读侧归一，
        # **存量裸字符串行不迁移、不重写**（无 migration，按 CR8-8 那条"只改写侧会留存量缺口"）。
        "newsSources": news["sources"],
        "degraded": bool(news["degraded"] or struct["engine"] == "keyword"),
        "note": "；".join(dict.fromkeys(shown))[:500] or None,
        "items": items,
    }
    result = {
        "date": payload["date"],
        "trigger": trigger,
        "topics": len(items),
        "newsSources": news["sources"],  # OPT-2：到货的源（可以是多家），不再是单值
        # #34（CR9-62）：合并计数每轮都在，**不随 note 一起消失**（三家齐时 note=None，
        # 这一份就是"合并前逐源几条／并掉几条"的唯一去处）。它不进 `payload`——落库那列
        # 没有装它的地方，而加列＝migration，按 CR8-8 那条口径要另立需求。
        "newsStats": news["stats"],
        # #43（CR9-71）：样本走 `newsStats` 同一条路（内存 `lastResult` → 覆写 `hotspot-state.json`
        # → `GET /hotspots/status`），同样**不进 `payload`**：落库那列没地方装它，加列＝migration。
        # 按键严格取（不用 `.get`）＝离线桩件少这个契约要当场 KeyError 崩掉，而不是"生产有、测试无"。
        "newsSamples": news["samples"],
        "engine": struct["engine"],
        "degraded": payload["degraded"],
        "note": payload["note"],
        "reasons": reasons,
        "tookMs": int((time.time() - started) * 1000),
    }
    if items:
        try:
            resp = emit_ingest(payload)
            result["ingested"] = resp.get("inserted", 0)
        except Exception as e:  # noqa: BLE001
            result["ingested"] = 0
            result["note"] = ((result["note"] + "；") if result["note"] else "") + (
                f"回调落库失败：{type(e).__name__}: {str(e)[:100]}"
            )
    else:
        result["ingested"] = 0
    result["finishedAt"] = datetime.now(TZ).isoformat(timespec="seconds")
    return result
