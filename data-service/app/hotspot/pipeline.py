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
from zoneinfo import ZoneInfo
from datetime import date, datetime

import requests

from ..config import load_env, search_api_key
from ..utils.limiter import get_limiter
from ..utils.timeout import run_with_timeout
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
_board_cache: dict[str, tuple[float, list[tuple[str, str]]]] = {}


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


def fetch_news(limit: int = NEWS_LIMIT) -> dict:
    """R12：海外源优先、国内源降级；返回 {items, source, degraded, note}。"""
    notes: list[str] = []
    if os.environ.get("SEARCH_API_KEY"):
        try:
            items = _tavily(limit)
            return {"items": items, "source": "tavily", "degraded": False, "note": None}
        except Exception as e:  # noqa: BLE001
            notes.append(f"Tavily 不可用（{type(e).__name__}），已降级国内新闻源")
    else:
        notes.append("未配置 SEARCH_API_KEY，使用国内新闻源")

    for name, fn in (("cls", _cls_telegraph), ("eastmoney-news", _em_global_news)):
        try:
            items = _ak_guarded(lambda: fn(limit), 45.0, "news-source")
            return {
                "items": items,
                "source": name,
                "degraded": True,
                "note": "；".join(notes),
            }
        except Exception as e:  # noqa: BLE001
            notes.append(f"{name} 不可用（{type(e).__name__}: {str(e)[:80]}）")
    return {
        "items": [],
        "source": "none",
        "degraded": True,
        "note": "；".join(notes) or "全部新闻源不可用",
    }


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


def _board_names() -> list[tuple[str, str]]:
    """返回 [(板块名, 来源)]：EM 概念+行业 → 新浪行业+概念 → THS 概念。

    与成分映射源保持一致性：东财不可用时优先用新浪名单（映射同源，命中即可得成分）。
    """
    cached = _board_cache.get("names")
    if cached and time.time() - cached[0] < _BOARD_CACHE_TTL:
        return cached[1]

    boards: list[tuple[str, str]] = []
    import akshare as ak

    if _EM.acquire(timeout=15):
        try:
            for fn, tag in (
                (ak.stock_board_concept_name_em, "em-concept"),
                (ak.stock_board_industry_name_em, "em-industry"),
            ):
                df = _ak_guarded(fn, 45.0, "board-name-list")
                series = _pick_col(df, "板块名称", "name")
                boards.extend(
                    (str(x).strip(), tag) for x in series.dropna().tolist() if str(x).strip()
                )
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
        _board_cache["names"] = (time.time(), boards)
    return boards


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


def structure_topics(news_items: list[dict]) -> dict:
    if not news_items:
        return {"topics": [], "engine": "none", "note": "无新闻可结构化"}

    headlines = "\n".join(
        f"{i + 1}. {it['title']}｜{it.get('summary', '')[:80]}"
        for i, it in enumerate(news_items[:20])
    )
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
            try:
                df = _ak_guarded(lambda: fn(symbol=board), 45.0, "board-constituents")
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
                log.warning("board cons failed (%s %s): %s", tag, board, e)
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


def _topic_urls(topic: dict, news_items: list[dict], limit: int = 3) -> list[str]:
    """CR4（P3）：按 topic 相关性挑选来源链接——此前所有 topic 都取相同的前 3 条
    新闻 URL（与各自 topic 无关联）。用 topic 标题+板块名的字二元组与新闻
    title+summary 的重叠数打分取前 N；无命中时回退首 N 条（与旧行为一致）。"""
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
    return [n["url"] for _, n in picked if n.get("url")]


def build_items(topics: list[dict], news_meta: dict) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    items: list[dict] = []
    for t in topics:
        related: list[dict] = []
        board_notes: list[str] = []
        for board in t.get("boards", [])[:2]:
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
    news = fetch_news()
    struct = structure_topics(news["items"])
    items, board_notes = build_items(struct["topics"], news)
    notes = [x for x in [news.get("note"), struct.get("note")] if x] + board_notes
    payload = {
        "date": date.today().isoformat(),
        "trigger": trigger,
        "engine": struct["engine"],
        "newsSource": news["source"],
        "degraded": bool(news["degraded"] or struct["engine"] == "keyword" or board_notes),
        "note": "；".join(dict.fromkeys(notes))[:500] or None,
        "items": items,
    }
    result = {
        "date": payload["date"],
        "trigger": trigger,
        "topics": len(items),
        "newsSource": news["source"],
        "engine": struct["engine"],
        "degraded": payload["degraded"],
        "note": payload["note"],
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
