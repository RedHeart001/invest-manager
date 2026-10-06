"""OPT-2 离线单测：新闻层多源合并（fusion）＋ #34 的合并计数与状态位文件。

背景（`docs/FIX-LEDGER.md` 的 OPT-2 行与 PLAN M8 那条「例外」）：`fetch_news` 旧语义是
"任一源成功即返回"（failover），于是一批新闻常年只来自一家，而"只来自一家"在旧契约里
恒等于 `degraded=True` ⇒ CR8-1 刚治掉的"降级横幅天天亮"其实是被这条上游喂出来的。
主人 10-04 给字"执行 OPT-2"，本轮落地：

1. **源序反转**＝东财 → 财联社 → Tavily（`NEWS_SOURCE_ORDER`，与旧的"海外优先"反方向）；
2. **逐源全部尝试**（不再命中即返回），成功项进 `merge_news`：并集 → 跨源标题二元组
   相似度去重 → 择优（有 url 优先于无 url，其次 summary 更长）；
3. **覆盖面自己说**：`sources`＝到货的源（多家），`degraded` **只在降到单源或零源**时才真，
   缺哪几家进 `note`（⇒ `reasons[]` 的 news 条目）——说话与报警是两件事；
4. **契约**：payload 的 `newsSource` 单值改 `newsSources` 数组（读侧兼容存量裸字符串，
   那半在 `web/lib/hotspots.ts` 与 ① 的 `hotspots-ingest.test.ts`）。

#34（CR9-62，主人 10-04 夜给字"按 lastResult 新键＋状态位文件、note 只顺带 重写后要做"）补的是
上面第 3 条留下的一个空洞：`note` **只在缺源时才说话**，于是"三家齐"那一轮（最该拿样本的一轮）
一个计数都不留 ⇒ ① `merge_news` 产出 `stats`、`run_pipeline` 带出 `newsStats`；
② `hotspot/scheduler` 每轮把 `lastResult` 覆写落盘，`status()` 内存空时回落到它并标 `fromDisk`
（同 #29／CR9-53 的备份状态位口径）。
**10-05 他的再一字＝"合并前／并掉几条"这类数对用户没用、属面向开发者的数据** ⇒ note 退回旧文案（只有"去重后 N 条"），
计数只留在 `newsStats`；下面那两条 note 断言因此是一对**屏幕不带数 ⇔ 数据照样读得到**。

零出网：三个源函数（`_em_global_news`／`_cls_telegraph`／`_tavily`）整体换成假对象，
调用计数就是"有没有真的出网"的证据；顺带断言这条合并路本身**不占东财桶**
（占桶的是 `_em_global_news` 里那一次 `acquire`，它在被测边界之外）。
状态位那一组写进 `tempfile` 临时目录（`HOTSPOT_STATE_FILE` 覆盖），不碰仓库里那份真的。

⚠️ 本套件测不到的那一半：去重那两道阈值（`NEWS_DEDUPE_MIN_SIM=0.5` ＋
`NEWS_DEDUPE_MIN_OVERLAP=0.8`）只在**合成标题**上被断言过（前缀变形要合并 ⇔ 同板块不同事件
不许并 ⇔ 短标题不被长标题吞掉），**没拿真新闻校准**。#34 落地的正是"校准要的那几个数从此每轮
都在"（`perSource`/`raw`/`mergedAway`/`crossSource`），**但数拿到了不等于阈值就校准了**——
比值仍要对着真 pipeline 的那一轮读（`OPT-2` 前置实测 ② 的遗留部分）。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_opt2_news_fusion.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


import app.hotspot.pipeline as pl  # noqa: E402
from app.utils.limiter import get_limiter  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def news(title: str, url: str = "", summary: str = "摘要") -> dict:
    return {"title": title, "url": url, "summary": summary, "time": "2026-10-04 09:00"}


CALLS: dict[str, int] = {}


def install_fake_sources(bodies: dict[str, object]) -> None:
    """把三个源函数换成假对象；`bodies[name]` 可以是列表（成功）或异常实例（失败）。
    没在这份字典里出现的源＝**不该被尝试**，被尝试到就直接抛（"多打了一家"是可见的失败）。"""
    CALLS.clear()
    for name in ("eastmoney-news", "cls", "tavily"):
        def make(n: str, spec: object):
            def _fn(limit: int) -> list[dict]:
                CALLS[n] = CALLS.get(n, 0) + 1
                if isinstance(spec, Exception):
                    raise spec
                if spec is None:
                    raise AssertionError(f"{n} 不该被尝试")
                return list(spec)[:limit]
            return _fn

        target = {"eastmoney-news": "_em_global_news", "cls": "_cls_telegraph", "tavily": "_tavily"}[name]
        setattr(pl, target, make(name, bodies.get(name)) if name in bodies else make(name, None))


def with_key(value: str):
    """临时把 `search_api_key` 换成假值——`fetch_news` 与 `_tavily` 都经它读 key。
    刻意**不碰 `os.environ`**：本机那份是真凭据，用例既不该读它也不该写它
    （CR9-51／#26 同族：把本机 env 当常数读＝环境一变就假红/假绿）。"""

    class _Ctx:
        def __enter__(self):
            self.prev = pl.search_api_key
            pl.search_api_key = lambda *a, **k: value
            return self

        def __exit__(self, *exc):
            pl.search_api_key = self.prev
            return False

    return _Ctx()


# ---------- 1. 源序与"全部尝试" ----------


def test_source_order_and_attempts() -> None:
    em = [news("东财第一条", url="https://em/1"), news("东财第二条", url="https://em/2")]
    cls = [news("财联社第一条"), news("东财第一条【快讯】", summary="同一条事件的转发")]
    tv = [news("Tavily 搜到的", url="https://t/1")]

    check("源序＝东财 → 财联社 → Tavily（与旧 failover 反方向，这一条要钉死）",
          pl.NEWS_SOURCE_ORDER == ("eastmoney-news", "cls", "tavily"), str(pl.NEWS_SOURCE_ORDER))

    install_fake_sources({"eastmoney-news": em, "cls": cls, "tavily": tv})
    with with_key("fake-tavily-key"):
        out = pl.fetch_news(limit=25)
    check("三家全部尝试（旧的'命中即返回'不会调满三家）",
          CALLS.get("eastmoney-news") == 1 and CALLS.get("cls") == 1 and CALLS.get("tavily") == 1,
          str(CALLS))
    check("主源＝源序里第一个到货的（东财）", out["source"] == "eastmoney-news", str(out["source"]))
    check("sources 是**到货清单**而不是单值", out["sources"] == ["eastmoney-news", "cls", "tavily"],
          str(out["sources"]))

    install_fake_sources({"eastmoney-news": RuntimeError("eastmoney cooling down"),
                          "cls": cls, "tavily": tv})
    with with_key("fake-tavily-key"):
        out2 = pl.fetch_news(limit=25)
    check("🔁 第一家失败不缩短后面两家的尝试（旧实现 cls 成功就不会再打 Tavily）",
          CALLS.get("cls") == 1 and CALLS.get("tavily") == 1, str(CALLS))
    check("失败的源从 sources 里消失，但成因为留在 missing 里",
          out2["sources"] == ["cls", "tavily"] and any("eastmoney" in m for m in out2["missing"]),
          f'{out2["sources"]}｜{out2["missing"]}')

    install_fake_sources({"eastmoney-news": em, "cls": cls, "tavily": tv})
    with with_key(""):
        out3 = pl.fetch_news(limit=25)
    check("没配 SEARCH_API_KEY ⇒ Tavily **一次请求都不发**（缺原因写成人话，不抛）",
          "tavily" not in CALLS and any("未配置 SEARCH_API_KEY" in m for m in out3["missing"]),
          f'{CALLS}｜{out3["missing"]}')
    check("🔁 没 key 时两家国内源到手 ⇒ 仍不算降级（否则无 key 的机器天天亮横幅）",
          out3["degraded"] is False and len(out3["sources"]) == 2, str(out3["sources"]))

    install_fake_sources({"eastmoney-news": em, "cls": cls, "tavily": tv})
    import time as _t
    with with_key("fake-tavily-key"):
        out4 = pl.fetch_news(limit=25, deadline=_t.monotonic() - 1)  # 预算早已耗尽
    check("deadline 用尽 ⇒ 三家都标'未尝试'，但**不发起任何一次调用**（CR-16 那条预算不变）",
          not CALLS and out4["items"] == [] and out4["degraded"] is True, str(CALLS))


# ---------- 2. 并集 / 去重 / 择优（纯函数） ----------


def test_merge_union_dedupe_and_pick() -> None:
    a = {"source": "eastmoney-news", "items": [news("央行宣布降准", url="https://em/1", summary="短")], "error": None}
    b = {"source": "cls", "items": [news("【央行宣布降准】", summary="长得多的一条转发说明，足够长了吧")], "error": None}
    m = pl.merge_news([a, b], limit=25)
    check("跨源同一条事件合并成一条（标题只差前缀）", len(m["items"]) == 1, str(m["items"])[:160])
    it = m["items"][0]
    check("`via` 记下供过这条的**两家**（不是只记留下那条的来源）",
          set(it["via"]) == {"eastmoney-news", "cls"}, str(it["via"]))
    check("择优＝有 url 优先（财联社 url 恒空，不能让它顶掉带链接的）",
          it["url"] == "https://em/1", str(it)[:160])

    a2 = {"source": "eastmoney-news", "items": [news("央行宣布降准", url="", summary="短")], "error": None}
    b2 = {"source": "cls", "items": [news("【央行宣布降准】", url="https://em/2", summary="也短")], "error": None}
    m2 = pl.merge_news([a2, b2], limit=25)
    check("🔁 反向：先到那条没链接、后到那条有链接 ⇒ 换成有链接的代表条目（CR8-3 的可用性就靠这条）",
          len(m2["items"]) == 1 and m2["items"][0]["url"] == "https://em/2", str(m2["items"])[:160])

    a3 = {"source": "eastmoney-news",
          "items": [news("央行宣布降准", url="https://em/1", summary="很短")], "error": None}
    b3 = {"source": "cls", "items": [news("央行宣布降准", url="", summary="摘要长得多的多得多")], "error": None}
    m3 = pl.merge_news([a3, b3], limit=25)
    check("择优的两条规则顺序不许反：摘要更长**不能**把带 url 的顶掉",
          m3["items"][0]["url"] == "https://em/1", str(m3["items"])[:160])

    a4 = {"source": "eastmoney-news",
          "items": [news("地产链午后拉升", url="https://em/a"), news("光伏组件报价上涨", url="https://em/b")],
          "error": None}
    b4 = {"source": "cls", "items": [news("地产链龙头涨停", url=""), news("白酒板块震荡回落", url="")],
          "error": None}
    m4 = pl.merge_news([a4, b4], limit=25)
    check("🔁 同板块的**不同事件**不许被误并（阈值再宽一点就会吃掉这种）",
          len(m4["items"]) == 4, str([x["title"] for x in m4["items"]]))

    short_long = [
        {"source": "eastmoney-news", "items": [news("降准")], "error": None},
        {"source": "cls", "items": [news("央行宣布降准")], "error": None},
    ]
    msl = pl.merge_news(short_long, limit=25)
    check("🔁 短标题不被长标题吞掉（重合度 1.0 但 Jaccard 只有 0.2 ⇒ 两道门槛都要过）",
          len(msl["items"]) == 2, str([x["title"] for x in msl["items"]]))

    only_summary = {"source": "cls",
                    "items": [{"title": "", "url": "", "summary": "没有标题只有内容的一条"},
                              {"title": "", "url": "", "summary": "没有标题只有内容的另一条"}],
                    "error": None}
    m5 = pl.merge_news([only_summary], limit=25)
    check("没有标题的条目不参与相似度判定（宁可重复也不误并），两条都在",
          len(m5["items"]) == 2, str(m5["items"])[:160])

    # 去重发生在截断**之前**——这条用一个能区分两种顺序的样本断：
    # 前 10 行是同一件事的同名转发、后 6 行各不相同 ⇒ 16 行进、并集 7 条、limit=5 留 5 条；
    # 若实现是"先截断再去重"，那 5 行全是同一个标题 ⇒ 只会剩 1 条，这个断言就会红。
    dups = [news("某公司发布季度业绩预告") for _ in range(10)]
    uniq = [news(t) for t in ("三大股指集体收涨", "宁德时代发布新电池", "贵州茅台公布分红方案",
                              "比亚迪三月销量创新高", "油轮运价单周翻倍", "央行公开市场逆回购加码")]
    m6 = pl.merge_news([{"source": "eastmoney-news", "items": dups + uniq, "error": None}], limit=5)
    check("limit 在去重**之后**截断（16 行进 ⇒ 并集 7 条 ⇒ 留 5；反序只剩 1 条）",
          len(m6["items"]) == 5, str(len(m6["items"])))
    check("同一家内的重复只算一条，via 不重复登记同一家",
          m6["items"][0]["via"] == ["eastmoney-news"], str(m6["items"][0]["via"]))

    # 两道门槛各自的可判别样本（直接喂二元组集合，不靠"恰好找得到的标题"）：
    # 交集 7、并集 13 ⇒ Jaccard 0.538（过 0.5 那道）但重合度 7/10＝0.7（不过 0.8 那道）。
    jac_only = {f"g{i:02d}" for i in range(10)}
    shifted = {f"g{i:02d}" for i in range(7)} | {"h1", "h2", "h3"}
    check("🔁 只过 Jaccard 那道门、重合度不够 ⇒ 判成两条不同的事件（少一道门就会误并）",
          pl._news_similar(jac_only, shifted) is False,
          f"交集 {len(jac_only & shifted)}、并集 {len(jac_only | shifted)}")
    check("两道门都过才判同一条（交集 9、并集 11 ⇒ Jaccard 0.82、重合度 0.9）",
          pl._news_similar({f"g{i:02d}" for i in range(10)},
                           {f"g{i:02d}" for i in range(9)} | {"z1"}) is True, "")

    near = [{"source": "eastmoney-news", "items": [news("第 1 条独立事件标题")], "error": None},
            {"source": "cls", "items": [news("第 10 条独立事件标题")], "error": None}]
    mnb = pl.merge_news(near, limit=25)
    check("已知**过度合并**形态（不是设计意图）：只差一个数字的近似标题会被判同一条"
          "（Jaccard 0.7、重合度 0.875）⇒ 已登记进 `OPT-2` 前置实测 ② 要看的东西；"
          "阈值没拿真新闻校准前不要动这两个数，也别把它们当『够用』的证据",
          len(mnb["items"]) == 1 and set(mnb["items"][0]["via"]) == {"eastmoney-news", "cls"},
          str(mnb["items"])[:180])

    m7 = pl.merge_news([], limit=25)
    check("空输入 ⇒ 空批次、source=none、degraded（空列表不许冒充成功）",
          m7["items"] == [] and m7["source"] == "none" and m7["degraded"] is True, str(m7)[:160])


# ---------- 3. 覆盖面的说话与报警是分开的两件事 ----------


def test_coverage_declaration() -> None:
    two = [
        {"source": "eastmoney-news", "items": [news("甲事件标题一")], "error": None},
        {"source": "cls", "items": [news("乙事件标题二")], "error": None},
    ]
    m = pl.merge_news(two, limit=25)
    check("两家到货 ⇒ degraded=False **且** note 为 None（常态不该说话）",
          m["degraded"] is False and m["note"] is None, str(m)[:160])

    one = [
        {"source": "eastmoney-news", "items": [news("甲事件标题一")], "error": None},
        {"source": "cls", "items": None, "error": "RuntimeError: cls unparsable"},
        {"source": "tavily", "items": None, "error": "未配置 SEARCH_API_KEY"},
    ]
    m1 = pl.merge_news(one, limit=25)
    check("🔁 降到单源 ⇒ degraded=True（这才是该报警的那一档）", m1["degraded"] is True, str(m1)[:160])
    check("报警的同时把缺的是谁、为什么说出来（CR9-31 覆盖面自述口径）",
          "1/3 家到货" in (m1["note"] or "") and "cls unparsable" in (m1["note"] or ""),
          str(m1["note"])[:200])

    partial = [
        {"source": "eastmoney-news", "items": [news("甲事件标题一")], "error": None},
        {"source": "cls", "items": [news("乙事件标题二")], "error": None},
        {"source": "tavily", "items": None, "error": "未配置 SEARCH_API_KEY"},
    ]
    m2 = pl.merge_news(partial, limit=25)
    check("缺一家但两家在手 ⇒ 只说话不报警：note 有、degraded 无（CR8-1 那条横幅不许回来）",
          m2["degraded"] is False and "未到货" in (m2["note"] or ""), str(m2)[:200])

    zero = [
        {"source": "eastmoney-news", "items": None, "error": "RuntimeError: eastmoney cooling down"},
        {"source": "cls", "items": None, "error": "RuntimeError: cls empty"},
        {"source": "tavily", "items": None, "error": "RuntimeError: no search key"},
    ]
    m3 = pl.merge_news(zero, limit=25)
    check("全部失败 ⇒ 空批次＋成因逐条列出（旧实现在这里也只说'全部不可用'，但成因更该带上）",
          m3["items"] == [] and "全部新闻源不可用" in (m3["note"] or "")
          and "eastmoney cooling down" in (m3["note"] or ""), str(m3["note"])[:220])


# ---------- 4. 合并这条路本身不占东财桶 + payload 契约 ----------


def test_no_bucket_use_and_payload_key() -> None:
    em_state = get_limiter("eastmoney").state()
    m = pl.merge_news(
        [{"source": "eastmoney-news", "items": [news("甲")], "error": None},
         {"source": "cls", "items": None, "error": "boom"}],
        limit=25,
    )
    after = get_limiter("eastmoney").state()
    check("merge_news 是纯函数：granted/denied/seenTotal 逐项未变（占桶的是真源函数，不在这一层）",
          (after["granted"], after["denied"], after["seenTotal"])
          == (em_state["granted"], em_state["denied"], em_state["seenTotal"]) and bool(m["items"]),
          f'{after["granted"]}/{after["denied"]}/{after["seenTotal"]}')

    cap: dict = {}
    orig = (pl.fetch_news, pl.structure_topics, pl.build_items, pl.emit_ingest)
    try:
        pl.fetch_news = lambda **kw: {
            "items": [news("甲")], "sources": ["eastmoney-news", "cls"],
            "source": "eastmoney-news", "missing": ["tavily（未配置）"],
            "degraded": False, "note": None,
            # #34：桩件必须与真 `fetch_news` 同形（`run_pipeline` 直接按键取，缺了就是 KeyError，
            # 这是刻意的——“计数丢了”不该被静默吞掉）。
            "stats": {"attempted": 3, "arrived": 2, "perSource": {"eastmoney-news": 1},
                      "raw": 1, "blank": 0, "kept": 1, "mergedAway": 0,
                      "truncated": 0, "crossSource": 0},
        }
        pl.structure_topics = lambda items, **kw: {"topics": [{"title": "甲"}], "engine": "llm", "note": None}
        pl.build_items = lambda topics, news, deadline=None: (
            [{"title": "甲", "summary": "", "boardTags": [], "sourceUrls": [], "relatedCodes": []}], [])
        pl.emit_ingest = lambda payload: (cap.update(payload), {"inserted": 0})[1]
        res = pl.run_pipeline(trigger="unit-test")
    finally:
        pl.fetch_news, pl.structure_topics, pl.build_items, pl.emit_ingest = orig

    check("落库 payload 的键改成了 `newsSources`（数组），旧单值键不再存在",
          cap.get("newsSources") == ["eastmoney-news", "cls"] and "newsSource" not in cap,
          str({k: v for k, v in cap.items() if "news" in k})[:160])
    check("运行结果同一口径（web 的「抓取完成：来源 X」读的就是这一份）",
          res.get("newsSources") == ["eastmoney-news", "cls"] and "newsSource" not in res,
          str({k: v for k, v in res.items() if "news" in k})[:160])
    check("#34：计数随 `run_pipeline` 的返回值出来（web/探针读的是这一份，不是 merge_news 的中间态）",
          res.get("newsStats", {}).get("attempted") == 3, str(res.get("newsStats"))[:160])
    check("🔁 计数**不进落库 payload**（那一列没有装它的地方；加列＝migration，按 CR8-8 要另立需求）",
          "newsStats" not in cap and "stats" not in cap, str(sorted(cap.keys()))[:200])


# ---------- 5. #34：满配那一轮的计数读得到（note 恰恰在这一轮是 None） ----------


def test_news_stats_survive_a_full_merge() -> None:
    """这一组是 #34 的**本体**：三家齐时 `note=None`，于是"合并前逐源几条"必须有别的去处。

    样本是照着"能手工数出来"设计的（三家全部到货、无 missing ⇒ note 必为 None）：
      · 东财 3 行：`央行宣布降准`／`白酒板块震荡回落`／`光伏组件报价上涨`
      · 财联社 2 行：`央行宣布降准`（与东财同一条）／`【白酒板块震荡回落】`（前缀变形，同一条）
      · Tavily 2 行：`央行宣布降准`（第三次供同一条）／一行空标题空摘要（该被当噪声丢）
      ⇒ raw 7、blank 1、kept 3、mergedAway 3、crossSource 2（降准跨三家、白酒跨两家）。
    """
    em = [news("央行宣布降准", url="https://em/1"), news("白酒板块震荡回落"), news("光伏组件报价上涨")]
    cls = [news("央行宣布降准"), news("【白酒板块震荡回落】")]
    tv = [news("央行宣布降准"), {"title": "", "url": "", "summary": "", "time": ""}]
    m = pl.merge_news(
        [{"source": "eastmoney-news", "items": em, "error": None},
         {"source": "cls", "items": cls, "error": None},
         {"source": "tavily", "items": tv, "error": None}],
        limit=25,
    )
    s = m["stats"]
    check("前提先钉住：三家齐 ⇒ note=None（旧口径下这一轮**什么数都不留**，#34 就是补这个）",
          m["note"] is None and len(m["sources"]) == 3, str(m["note"]))
    check("perSource＝合并前**逐源**交来几行（缺的就是这个分母）",
          s["perSource"] == {"eastmoney-news": 3, "cls": 2, "tavily": 2}, str(s["perSource"]))
    check("raw/blank/kept/mergedAway 四数手工可数（7/1/3/3）",
          (s["raw"], s["blank"], s["kept"], s["mergedAway"]) == (7, 1, 3, 3), str(s)[:200])
    check("恒等式 raw == blank + kept + mergedAway（拿去校准阈值时先查这条，不对就别读比值）",
          s["raw"] == s["blank"] + s["kept"] + s["mergedAway"], str(s)[:200])
    check("crossSource＝`via` 跨了 ≥2 家的条目数（同一家内的重复不需要阈值 ⇒ 只该数到 2）",
          s["crossSource"] == 2, str([x["via"] for x in m["items"]]))
    check("kept 是**截断前**的并集、truncated 是被 NEWS_LIMIT 切掉的 ⇒ 两者相加才等于 items",
          s["truncated"] == 0 and s["kept"] - s["truncated"] == len(m["items"]), str(s)[:200])

    # 截断这一档单独测：limit 比并集小，`truncated` 必须 nonzero，否则 note 与 stats 会互相打脸
    m2 = pl.merge_news(
        [{"source": "eastmoney-news",
          "items": [news("央行宣布降准"), news("第 2 条独立事件标题甲"), news("第 3 条独立事件标题乙")],
          "error": None},
         {"source": "cls", "items": [news("央行宣布降准")], "error": None}],
        limit=2,
    )
    check("🔁 limit=2 时 kept=3 而 items=2 ⇒ truncated=1（“并掉多少”与“切掉多少”是两件事）",
          m2["stats"]["kept"] == 3 and len(m2["items"]) == 2 and m2["stats"]["truncated"] == 1
          and m2["stats"]["mergedAway"] == 1, str(m2["stats"])[:200])

    # 缺一家：note 说话了，但说的是『给用户看的那一层』——计数只在 stats 里（主人 10-05 的字＝
    # "合并前／并掉几条"对用户没用、属面向开发者的数据，不要上屏）。
    m3 = pl.merge_news(
        [{"source": "eastmoney-news", "items": em, "error": None},
         {"source": "cls", "items": cls, "error": None},
         {"source": "tavily", "items": None, "error": "未配置 SEARCH_API_KEY"}],
        limit=25,
    )
    note = m3["note"] or ""
    check("note 不带合并前后的计数（屏幕只说几家到货、去重后几条、未到货是谁）",
          "合并前" not in note and "并掉" not in note and "去重后 3 条" in note, note[:220])
    check("🔁 撤的是屏幕不是数据：同一轮 stats 里 raw=5／mergedAway=2／arrived=2／attempted=3 照样读得到",
          m3["stats"]["raw"] == 5 and m3["stats"]["mergedAway"] == 2
          and m3["stats"]["arrived"] == 2 and m3["stats"]["attempted"] == 3, str(m3["stats"])[:200])
    check("缺源时 attempted/arrived 也在 stats 里（note=None 的那一轮同样要能说清“试了几家”）",
          m3["stats"]["attempted"] == 3 and m3["stats"]["arrived"] == 2, str(m3["stats"])[:160])


# ---------- 6. 状态位文件：重启后那一轮的数还在（fromDisk 不许与"从没跑过"同形） ----------


def test_state_file_and_from_disk_fallback() -> None:
    import shutil
    import tempfile

    import app.hotspot.scheduler as hs

    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "hotspot-state.json")
    prev_env = os.environ.get("HOTSPOT_STATE_FILE")
    prev_state = dict(hs._state)
    os.environ["HOTSPOT_STATE_FILE"] = path
    try:
        hs._state.update({
            "running": False, "runs": 7, "catchUpResolved": "2026-10-05",
            "lastRun": "2026-10-05T08:30:05+08:00",
            "lastResult": {"trigger": "pre-market", "newsSources": ["eastmoney-news", "cls", "tavily"],
                           "note": None, "newsStats": {"kept": 3, "raw": 7, "crossSource": 2}},
        })
        wrote = hs._write_state()
        check("落盘写侧的形状（这一条的内存是测试**手填**的，不等于跑过一轮——真跑一轮由下面那组盯）",
              wrote is True and os.path.exists(path), f"wrote={wrote}")
        s_mem = hs.status()
        check("内存非空 ⇒ fromDisk=False（本进程跑过与上个进程跑过，两格不许同形）",
              s_mem["fromDisk"] is False and s_mem["runs"] == 7, str(s_mem["fromDisk"]))

        # 模拟重启：内存清空，只有盘上那份
        hs._state.update({"lastRun": None, "lastResult": None, "runs": 0, "catchUpResolved": None})
        s_disk = hs.status()
        check("🔁 内存清空后一次 curl 仍读得到那一轮的合并计数，且标 fromDisk=True",
              s_disk["fromDisk"] is True
              and s_disk["lastResult"]["newsStats"]["crossSource"] == 2
              and s_disk["lastRun"] == "2026-10-05T08:30:05+08:00", str(s_disk)[:200])
        check("回落**只捞 lastRun/lastResult**，`runs` 保持本进程原义（p3 的轮询条件靠它）",
              s_disk["runs"] == 0, f'runs={s_disk["runs"]}')
        check("`catchUpResolved` 不进状态位文件（昨天的“补跑已定案”放到今天就是错的）",
              "catchUpResolved" not in (hs.read_state() or {}), str(sorted((hs.read_state() or {}).keys())))

        # 盘上也没有 ⇒ 与"读到 null"分开
        os.remove(path)
        s_none = hs.status()
        check("🔁 内存空**且**盘上也没有 ⇒ fromDisk=False、lastResult=None（“从没跑过”是另一格）",
              s_none["fromDisk"] is False and s_none["lastResult"] is None, str(s_none)[:160])

        with open(path, "w", encoding="utf-8") as f:
            f.write("{ 半截的 JSON")
        check("文件损坏一律当“没有”：read_state 不抛、status 不 500",
              hs.read_state() is None and hs.status()["fromDisk"] is False, "corrupt")

        # 失败轮同样要落盘，且**写盘这一步接在 `_execute` 的收尾**：只让单测手动调 `_write_state`
        # 是假绿——把 `_execute` 里那行删掉，下面这条就该红。
        orig_exec = hs.run_pipeline
        hs._state.update({"lastRun": None, "lastResult": None})
        try:
            hs.run_pipeline = lambda trigger="manual": (_ for _ in ()).throw(RuntimeError("boom"))
            hs._state["running"] = True
            res = hs._execute("unit-test-fail")
        finally:
            hs.run_pipeline = orig_exec
        disk_err = str((hs.read_state() or {}).get("lastResult", {}).get("error", ""))
        check("🔁 失败轮同样落盘，且写盘接在 `_execute` 收尾（不是只有单测手动调）",
              disk_err.startswith("RuntimeError: boom") and disk_err != ""
              and res.get("error", "").startswith("RuntimeError: boom"), f"disk={disk_err[:100]}")
        check("失败轮的出口照样释放 `running`（状态位不许把单飞锁卡死）",
              hs._state["running"] is False, str(hs._state["running"]))

        # 写不进去 ⇒ 观测不得拖垮主功能（CR9-45）：只 warning、返回 False、不留半截
        blocker = os.path.join(tmpdir, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("占位：blocker 是个文件，它下面的目录建不出来")
        os.environ["HOTSPOT_STATE_FILE"] = os.path.join(blocker, "sub", "hotspot-state.json")
        check("写不进去时只 log.warning、返回 False，且不留 `.tmp` 半截（CR9-45）",
              hs._write_state() is False and not os.path.exists(path + ".tmp"), "unwritable")
    finally:
        hs._state.clear()
        hs._state.update(prev_state)
        if prev_env is None:
            os.environ.pop("HOTSPOT_STATE_FILE", None)
        else:
            os.environ["HOTSPOT_STATE_FILE"] = prev_env
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_execute_success_branch_is_written_by_production() -> None:
    """CR9-68（#40 乙）：状态位里"成功轮"那一格，必须由 `_execute` 的**成功分支**写出来。

    为什么单开一组（10-06 断言强度审计登记的 #40 (b)）：上面那组里叫「成功轮的出口」的那条
    （`:412-420`）其实是**测试自己**把 `lastResult` 写进内存、再直调 `hs._write_state()`——
    它没有跑那一轮。全文件唯一真驱动 `_execute` 的是 `:450-461`，而那一支把 `run_pipeline`
    换成抛 `RuntimeError` 的版本＝失败轮。⇒ `app/hotspot/scheduler.py:103-105` 那三行
    （`lastRun`／`_state["lastResult"] = result`／`runs += 1`）此前**无人从调用点盯**：
    摘掉 `:104`，成功轮的 `newsStats` 再也进不了内存与盘＝**#34 那个洞原样回来**，而这套照绿。

    顺带把"用例名会替测试说谎"这一形状钉死：**落过盘 ⇔ 跑过一轮**是两件事，
    所以第一组断言先只做"手填＋直调 `_write_state()`"，要求 `runs` 一动不动。
    """
    import shutil
    import tempfile

    import app.hotspot.scheduler as hs

    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "hotspot-state.json")
    prev_env = os.environ.get("HOTSPOT_STATE_FILE")
    prev_state = dict(hs._state)
    os.environ["HOTSPOT_STATE_FILE"] = path
    payload = {
        "trigger": "unit-test-ok",
        "newsSources": ["eastmoney-news", "cls"],
        "note": None,
        "newsStats": {"kept": 9, "raw": 12, "crossSource": 3},
    }
    orig = hs.run_pipeline
    try:
        hs._state.update({
            "running": True, "runs": 0, "lastRun": None,
            "lastResult": None, "catchUpResolved": None,
        })
        # 只复现旧用例那个动作：手填内存 + 直接落盘，不经过 `_execute`
        hs._state["lastResult"] = payload
        hs._write_state()
        check("🔁 「写进内存再落盘」不等于跑过一轮：`runs` 仍是 0（旧用例名谎称的那件事）",
              hs._state["runs"] == 0, f'runs={hs._state["runs"]}')
        # 手填那份**必须先清掉**再跑 `_execute`：留着它，摘掉 `scheduler.py:104` 也照样绿＝
        # 与这枚洞同形的自证（19:2x 钻 b 实测第一版就是这么漏的，改在此处而不是只在注释里说）
        hs._state["lastResult"] = None

        hs.run_pipeline = lambda trigger="manual": payload
        res = hs._execute("unit-test-ok")
        check("成功轮的出口由生产写：`_execute` 回的就是 pipeline 那份载荷，内存 `lastResult` 与它同物",
              res is payload and hs._state["lastResult"] is payload, str(res)[:120])
        check("🔁 摘掉 `scheduler.py:104` ⇒ 红在这里：盘上那份 `lastResult.newsStats` 与内存同源",
              ((hs.read_state() or {}).get("lastResult") or {}).get("newsStats", {}).get("crossSource") == 3,
              str(hs.read_state())[:200])
        check("成功轮要写 `lastRun`（失败轮不写 ⇒ 两态在状态位上必须不同形）",
              isinstance(hs._state["lastRun"], str) and hs._state["lastRun"] != "",
              str(hs._state["lastRun"]))
        check("🔁 跑完一轮 ⇒ `runs` 恰好 +1（计数住在成功分支里，不在 `finally`）",
              hs._state["runs"] == 1, f'runs={hs._state["runs"]}')
        check("成功轮的出口同样释放 `running`（单飞锁不因为成功而卡住）",
              hs._state["running"] is False, str(hs._state["running"]))
        disk = (hs.read_state() or {}).get("lastResult") or {}
        check("盘上成功那份**不带** `error` 键（只有失败轮出口才有＝两态不许在文件里同形）",
              "error" not in disk, str(disk)[:160])
    finally:
        hs.run_pipeline = orig
        hs._state.clear()
        hs._state.update(prev_state)
        if prev_env is None:
            os.environ.pop("HOTSPOT_STATE_FILE", None)
        else:
            os.environ["HOTSPOT_STATE_FILE"] = prev_env
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_source_order_and_attempts()
    test_merge_union_dedupe_and_pick()
    test_coverage_declaration()
    test_no_bucket_use_and_payload_key()
    test_news_stats_survive_a_full_merge()
    test_state_file_and_from_disk_fallback()
    test_execute_success_branch_is_written_by_production()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
