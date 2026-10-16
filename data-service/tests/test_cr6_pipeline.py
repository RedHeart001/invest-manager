"""CR6-P2-3 离线单测：热点 pipeline 整体 deadline 降级。

运行方式（无需服务在跑）：
    .venv/Scripts/python tests/test_cr6_pipeline.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
# 自带 UTF-8 输出后，跑本脚本不再需要 PYTHONIOENCODING（errors=replace 兜极端情况）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


import app.hotspot.pipeline as pl

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _topics() -> list[dict]:
    return [
        {"title": f"topic{i}", "summary": "", "boards": ["B1", "B2", "B3"]} for i in range(5)
    ]


# #34（CR9-62）之后 `run_pipeline` 按键取 `news["stats"]`（真 `fetch_news` 每轮都带），
# 所以这里的桩件必须与它同形——缺这个键不是"桩件更简单"，而是**桩件比真函数少一个契约**，
# 表现就是整轮 KeyError（本轮 ② 全量实跑撞到的就是这一条）。
STUB_STATS = {
    "attempted": 3, "arrived": 1, "perSource": {"test": 0}, "raw": 0,
    "blank": 0, "kept": 0, "mergedAway": 0, "truncated": 0, "crossSource": 0,
}

# #43（CR9-71）之后 `run_pipeline` 也按键取 `news["samples"]` —— 同一条纪律：桩件少契约就该崩在这里。
STUB_SAMPLES = {
    "thresholds": {"minSim": 0.5, "minOverlap": 0.8},
    "nearMissKeep": 10, "nearMissTotal": 0, "mergedPairs": [], "nearMiss": [],
}

# #44（CR9-72）之后 `run_pipeline` 解包 `build_items` 的第三个返回值（`build_items` 自己
# 按键取 `mapped["pathForms"]`）⇒ 桩 build_items 的三处也必须带这一份，形状照真函数。
STUB_PATHS = {
    "byCode": 0, "byName": 0,
    "requestsPerCodePath": 1, "requestsPerNamePath": 9,
    "savedRequestsEstimate": 0, "emCodeRows": 0,
    # CR9-112 刀 2：`build_items` 的第三枚返回值多带一格每腿种类（形状照真函数）
    "legs": {"attempts": 0, "byClass": {}},
}


def test_build_items_deadline_expired() -> None:
    """deadline 已过期 → 不调用 map_board_products，但每个 topic 仍产出，带降级 note。"""
    calls = {"n": 0}
    orig = pl.map_board_products

    def _boom(board):
        calls["n"] += 1
        # #44（CR9-72）：`build_items` 现在按键取 `pathForms`，桩件少这个契约就是 KeyError——
        # 与 CR9-62 那条"桩件比真函数少一个契约"同形，超时这一支本来也不该发过成分请求。
        # CR9-112 刀 2 同形再加一枚：`legOutcomes` 少了一样当场崩。
        return {"stocks": [], "note": None, "pathForms": [], "legOutcomes": []}

    pl.map_board_products = _boom
    try:
        # deadline 设为过去时刻：立即判定超时
        items, notes, paths = pl.build_items(_topics(), {"items": []}, deadline=time.monotonic() - 1)
    finally:
        pl.map_board_products = orig

    check("P2-3：超时后不再调用外部映射", calls["n"] == 0, str(calls))
    check("P2-3：每个 topic 仍产出（不整段丢弃）", len(items) == 5, str(len(items)))
    check("P2-3：relatedCodes 为空（未映射）", all(i["relatedCodes"] == [] for i in items))
    check("P2-3：note 标注降级", any("超时" in n for n in notes), str(notes))
    check("#44：一次都没发出去的轮，两格计数都是 0（超时早退不得被读成「BK 路径通了」）",
          paths["byCode"] == 0 and paths["byName"] == 0 and paths["savedRequestsEstimate"] == 0,
          str(paths)[:200])


def test_build_items_within_deadline() -> None:
    """deadline 充裕 → 正常映射，无降级 note。"""
    calls = {"n": 0}
    orig = pl.map_board_products

    def _ok(board):
        calls["n"] += 1
        return {"stocks": [{"code": "000001", "name": "x"}], "note": None, "pathForms": ["code"],
                "legOutcomes": ["em-concept:ok"]}

    pl.map_board_products = _ok
    try:
        items, notes, paths = pl.build_items(_topics(), {"items": []}, deadline=time.monotonic() + 999)
    finally:
        pl.map_board_products = orig

    check("P2-3：未超时则正常映射（5 topic × 2 board）", calls["n"] == 10, str(calls))
    check("P2-3：未超时不加降级 note", not any("超时" in n for n in notes), str(notes))
    check("P2-3：未超时 relatedCodes 非空", all(len(i["relatedCodes"]) == 2 for i in items))
    check("#44：计数是从**每一次真发出去的成分请求**累加的（10 次映射 ⇒ byCode=10，不是 byCode=1）",
          paths["byCode"] == 10 and paths["byName"] == 0, str(paths)[:160])
    check("#44：省下的是折算值而非常量——byCode 每走一次代码路径记 (名称扇出 − 代码扇出)",
          paths["savedRequestsEstimate"]
          == paths["byCode"] * (paths["requestsPerNamePath"] - paths["requestsPerCodePath"]),
          str(paths)[:200])


def test_run_pipeline_deadline_env() -> None:
    """run_pipeline 读取 HOTSPOT_PIPELINE_TIMEOUT_S（非法值回落 300），并传入 deadline。"""
    captured = {}

    orig_fetch = pl.fetch_news
    orig_struct = pl.structure_topics
    orig_build = pl.build_items
    orig_emit = pl.emit_ingest

    pl.fetch_news = lambda **kw: {"items": [], "source": "test", "sources": ["test"], "note": None,
                                  "degraded": False, "stats": STUB_STATS, "samples": STUB_SAMPLES}
    pl.structure_topics = lambda items, **kw: {"topics": [], "engine": "keyword", "note": None}

    def _build(topics, news, deadline=None):
        captured["deadline"] = deadline
        return [], [], dict(STUB_PATHS)

    pl.build_items = _build
    pl.emit_ingest = lambda payload: {}

    try:
        os.environ["HOTSPOT_PIPELINE_TIMEOUT_S"] = "1"
        t0 = time.monotonic()
        pl.run_pipeline(trigger="test")
        d = captured.get("deadline")
        check("P2-3：run_pipeline 传入 deadline", d is not None)
        check("P2-3：deadline 约为 now+1s", d is not None and 0 < d - t0 <= 2.0, str(d and d - t0))

        os.environ["HOTSPOT_PIPELINE_TIMEOUT_S"] = "bad"
        pl.run_pipeline(trigger="test")
        d2 = captured.get("deadline")
        # 容差放宽到 300.5：deadline = 起点 + 300，断言处再取一次 monotonic，
        # 两次取值间必有微小正/负差，严格 <=300 会因浮点边界误报（本轮暴露）。
        check("P2-3：非法 env 回落 300s", d2 is not None and 290 < (d2 - time.monotonic()) <= 300.5, str(d2 and d2 - time.monotonic()))
    finally:
        pl.fetch_news = orig_fetch
        pl.structure_topics = orig_struct
        pl.build_items = orig_build
        pl.emit_ingest = orig_emit
        os.environ.pop("HOTSPOT_PIPELINE_TIMEOUT_S", None)


def test_topic_urls_title_passthrough() -> None:
    """CR8-3：来源链接必须带标题出 ds。

    旧实现在 `return` 那一步丢掉 `n["title"]`（打分环节 `:588` 一直持有它），
    于是 `sourceUrls` 存成裸 URL、前端只能渲染三个无差别的「原文」。
    """
    news_items = [
        {"url": "https://a/1", "title": "芯片设备领涨", "summary": "半导体 板块"},
        {"url": "", "title": "财联社电报条目（无链接）", "summary": "半导体"},
        {"url": "https://a/2", "title": "另一条相关内容", "summary": "芯片 设备"},
    ]
    out = pl._topic_urls(
        {"title": "芯片设备领涨科技分化", "boards": ["半导体"]}, news_items
    )
    check(
        "CR8-3：返回 {url,title} 结构而不是裸字符串",
        bool(out) and all(isinstance(x, dict) and {"url", "title"} <= set(x) for x in out),
        str(out),
    )
    check(
        "CR8-3：标题真的透传出来了（非空）",
        any(isinstance(x, dict) and x.get("title") for x in out),
        str(out),
    )
    check(
        "CR8-3：写死空 url 的条目被滤掉（cls 电报没有链接，不是本层丢的）",
        all(isinstance(x, dict) and x.get("url") for x in out) and len(out) == 2,
        str(out),
    )
    check(
        "🔁 CR8-3 反向：输入里确有 3 条、其中 1 条无链接 ⇒ 出 2 条不是测试自造空集",
        len(news_items) == 3 and len(out) == 2,
        str(out),
    )


def test_run_pipeline_reasons_split() -> None:
    """CR8-1：三类成因不再被 OR 成一个 `degraded`、拼成一条 note。

    旧实现 `degraded = news or engine=="keyword" or board_notes` 且把三类 note
    一起拼串 ⇒ `web` 侧逐卡渲染「降级产出」，其中 ③ 板块名未命中几乎每轮都有，
    是纯噪声。现在 ③ 只进运行结果 `reasons`，不进落库契约。
    """
    cap = {}
    cap2 = {}
    orig = (pl.fetch_news, pl.structure_topics, pl.build_items, pl.emit_ingest)
    items = [
        {"title": "t", "summary": "", "boardTags": [], "sourceUrls": [], "relatedCodes": []}
    ]
    board_note = "新浪板块名称未匹配「地产链」"

    try:
        # 场景 A：① 新闻源降级 + ③ 板块未命中 同时在场
        pl.fetch_news = lambda **kw: {
            "items": [],
            "source": "eastmoney-news",
            "sources": ["eastmoney-news"],
            "note": "新闻多源合并：1/3 家到货；未到货：Tavily（Timeout）",
            "degraded": True, "stats": STUB_STATS, "samples": STUB_SAMPLES,
        }
        pl.structure_topics = lambda items, **kw: {
            "topics": [{"title": "t"}],
            "engine": "llm",
            "note": None,
        }
        pl.build_items = lambda topics, news, deadline=None: (items, [board_note], dict(STUB_PATHS))
        pl.emit_ingest = lambda payload: (cap.update(payload), {})[1]
        res = pl.run_pipeline(trigger="test")
        check(
            "CR8-1：① 新闻源降级仍进 note（该说的没说少）",
            "Tavily" in (cap.get("note") or ""),
            str(cap.get("note")),
        )
        check(
            "CR8-1：③ 板块名未命中不再进 note",
            "未匹配" not in (cap.get("note") or ""),
            str(cap.get("note")),
        )
        check(
            "CR8-1：运行结果按成因分类，③ 仍可观测",
            [r["kind"] for r in res.get("reasons", [])] == ["news", "board"],
            str(res.get("reasons")),
        )

        # 场景 B（🔁 反向）：只有 ③ 在场 ⇒ 不得判降级（旧实现会判 True 并满屏噪声）
        pl.fetch_news = lambda **kw: {
            "items": [],
            "source": "tavily",
            "sources": ["tavily"],
            "note": None,
            "degraded": False, "stats": STUB_STATS, "samples": STUB_SAMPLES,
        }
        pl.emit_ingest = lambda payload: (cap2.update(payload), {})[1]
        pl.run_pipeline(trigger="test")
        check(
            "🔁 CR8-1 反向：只有 ③ 时 degraded=False 且 note 为空（旧实现在此回归）",
            cap2.get("degraded") is False and cap2.get("note") is None,
            str({k: cap2.get(k) for k in ("degraded", "note")}),
        )
    finally:
        pl.fetch_news, pl.structure_topics, pl.build_items, pl.emit_ingest = orig


def test_board_code_shortcut() -> None:
    """CR9-3(a)：名称→BK 代码缓存让成分映射从 9 个东财请求降到 1 个。

    实证口径（09-27 00:1x 在 requests 层计数）：`*_cons_em(symbol=名称)` 先重拉整张
    板块表（9 请求，fs=m:90+t:3），传 BK 代码直接打成分端点（1 请求，fs=b:BKxxxx）。
    """
    import akshare as ak
    import pandas as pd

    ak_names = (
        "stock_board_concept_name_em",
        "stock_board_industry_name_em",
        "stock_board_concept_cons_em",
        "stock_board_industry_cons_em",
    )
    orig_ak = {n: getattr(ak, n) for n in ak_names}
    orig_sina = pl._sina_board_products
    orig_em = (pl._EM.acquire, pl._EM.on_success, pl._EM.on_failure)

    seen: list[str] = []

    def _cons(symbol: str):
        seen.append(symbol)
        return pd.DataFrame({"代码": ["601012"], "名称": ["隆基绿能"]})

    ak.stock_board_concept_name_em = lambda: pd.DataFrame(
        {"板块名称": ["光伏设备", "储能"], "板块代码": ["BK0446", "-"]}
    )
    ak.stock_board_industry_name_em = lambda: pd.DataFrame(
        {"板块名称": ["电源设备"], "板块代码": ["BK1033"]}
    )
    ak.stock_board_concept_cons_em = _cons
    ak.stock_board_industry_cons_em = _cons
    pl._sina_board_products = lambda board, limit=6: {
        "stocks": [], "source": "none", "note": "sina 不应参与",
    }
    pl._EM.acquire = lambda *a, **k: True
    pl._EM.on_success = lambda: None
    pl._EM.on_failure = lambda: None
    pl._board_cache.clear()
    try:
        check("CR9-3a：BK 代码随名单入缓存", pl._board_code("光伏设备", "em-concept") == "BK0446")
        check(
            "CR9-3a：非 BK 形态（横杠占位）不入库 → 按名称回退",
            pl._board_code("储能", "em-concept") is None,
        )
        check(
            "CR9-3a：概念/行业分源记账，不跨源误用代码",
            pl._board_code("光伏设备", "em-industry") is None
            and pl._board_code("电源设备", "em-industry") == "BK1033",
        )
        seen.clear()
        r = pl.map_board_products("光伏设备")
        check("CR9-3a：映射按 BK 代码请求（省掉 9 个整表请求）", seen == ["BK0446"], str(seen))
        check(
            "CR9-3a：返回形态与改动前一致",
            r["source"] == "em-concept" and r["stocks"][0]["code"] == "601012",
            str(r)[:120],
        )
        check("#44：真发出去的那一发记成 `code`（清单按请求计，不按板块计）",
              r["pathForms"] == ["code"], str(r.get("pathForms")))
        # 🔁 旁路代码查询：必须退回"按名称请求"的原行为，证明差异出自缓存命中而非改写语义
        orig_bc = pl._board_code
        pl._board_code = lambda *a, **k: None
        try:
            seen.clear()
            r2 = pl.map_board_products("光伏设备")
            check("CR9-3a🔁：无代码时按名称请求（原行为）", seen == ["光伏设备"], str(seen))
            check("#44🔁：同一板块退回名称时记成 `name`——两格分开，才读得出「名单通没通」",
                  r2["pathForms"] == ["name"], str(r2.get("pathForms")))
        finally:
            pl._board_code = orig_bc
    finally:
        for n, v in orig_ak.items():
            setattr(ak, n, v)
        pl._sina_board_products = orig_sina
        pl._EM.acquire, pl._EM.on_success, pl._EM.on_failure = orig_em
        pl._board_cache.clear()


def test_board_leg_exception_split() -> None:
    """#79 甲′（CR9-110）：概念腿抛**哪一类**异常，决定行业腿试不试得到。

    旧写法在 `except` 里无条件 `break`（注释写"熔断已触发"，可额度被拒根本不走异常），
    于是 em-industry 那一腿在任何概念板异常之后**结构上永远试不到**——实测样本＝拿着
    `BK1033` 的「电源设备」整块落新浪（今日读数 `byCode=0／byName=2` 就是这个形状）。
    判据取 `_ak_guarded` 早就保下来的 `__cause__`（`raise ... from 原异常`），不改中间层。
    """
    import akshare as ak
    import pandas as pd

    from app.utils.timeout import WatchdogOpenError

    ak_names = ("stock_board_concept_cons_em", "stock_board_industry_cons_em")
    orig_ak = {n: getattr(ak, n) for n in ak_names}
    orig_sina = pl._sina_board_products
    orig_em = (pl._EM.acquire, pl._EM.on_success, pl._EM.on_failure)
    orig_bc = pl._board_code
    orig_wl = pl._BOARD_DATA_SHAPE_ERRORS

    seen: list[tuple[str, str]] = []
    fails: list[str] = []
    oks: list[str] = []

    def _cons(tag: str, err: Exception | None = None):
        def _f(symbol: str):
            seen.append((tag, symbol))
            if err is not None:
                raise err
            return pd.DataFrame({"代码": ["300750", "601012"], "名称": ["宁德时代", "隆基绿能"]})
        return _f

    try:
        pl._EM.acquire = lambda *a, **k: True
        pl._EM.on_success = lambda: oks.append("ok")
        pl._EM.on_failure = lambda: fails.append("fail")
        pl._sina_board_products = lambda board, limit=6: {
            "stocks": [{"code": "300750", "name": "宁德时代"}], "source": "sina-test", "note": None,
        }
        # 真形状：概念板名单里没有这一只（返回 None），行业板有 BK 代码 ⇒ 第一腿按名称、第二腿按代码
        codes = {("电源设备", "em-concept"): None, ("电源设备", "em-industry"): "BK1033"}
        pl._board_code = lambda board, tag: codes.get((board, tag))

        ak.stock_board_concept_cons_em = _cons("em-concept", IndexError("单测桩：这一族没有这个板块"))
        ak.stock_board_industry_cons_em = _cons("em-industry")
        seen.clear(); fails.clear(); oks.clear()
        r = pl.map_board_products("电源设备")
        check("甲′：概念腿抛 IndexError ⇒ 行业腿真发出去（旧写法到这里就 break）",
              seen == [("em-concept", "电源设备"), ("em-industry", "BK1033")], str(seen))
        check("甲′：第二腿命中时 `source` 换成 `em-industry`（不再白落新浪）",
              r["source"] == "em-industry" and len(r["stocks"]) == 2, str(r)[:140])
        check("甲′：`pathForms` 记两枚＝名称腿＋代码腿（一枚板块两格读数，别当成两次抓取）",
              r["pathForms"] == ["name", "code"], str(r.get("pathForms")))
        check("CR9-112（改口）：一腿抛、一腿取回成分＝整枚映射只回报一次，且按最终结果报（成功压过中途的失败）",
              len(fails) == 0 and len(oks) == 1, f"fails={len(fails)} oks={len(oks)}")

        # 🔁 两半样本：把白名单清空＝模拟"改回无条件 break"，同一输入必须翻回旧文案
        pl._BOARD_DATA_SHAPE_ERRORS = ()
        ak.stock_board_concept_cons_em = _cons("em-concept", IndexError("单测桩：同上"))
        seen.clear(); fails.clear(); oks.clear()
        r2 = pl.map_board_products("电源设备")
        check("甲′🔁：摘掉白名单＝第二腿又试不到、落回新浪（证差异出自那枚判据，不是别的）",
              seen == [("em-concept", "电源设备")] and r2["source"] == "sina-test",
              f"{seen} / {r2['source']}")
        pl._BOARD_DATA_SHAPE_ERRORS = orig_wl

        # 超时那一形（看门狗真构造的就是 TimeoutError）＝维持今天的语义：整族降级，不多打一腿
        ak.stock_board_concept_cons_em = _cons("em-concept", TimeoutError("单测桩：>45s 已放弃"))
        seen.clear(); fails.clear(); oks.clear()
        r3 = pl.map_board_products("电源设备")
        check("甲′：概念腿抛 TimeoutError ⇒ 仍不试第二腿、直接转新浪（上游不可信时不追加扇出）",
              seen == [("em-concept", "电源设备")] and r3["source"] == "sina-test", str(seen))
        ak.stock_board_concept_cons_em = _cons(
            "em-concept", WatchdogOpenError("单测桩：在飞达上限，一个请求都没发")
        )
        seen.clear()
        r4 = pl.map_board_products("电源设备")
        check("甲′：WatchdogOpenError 是 TimeoutError 子类 ⇒ 白名单不认它，同样不追加那一腿",
              seen == [("em-concept", "电源设备")] and r4["source"] == "sina-test", str(seen))

        # 判据函数逐形点名（`_pick_col` 那一形是**裸异常、没有 `__cause__`**，也要认得）
        def _wrapped(err: Exception) -> RuntimeError:
            e = RuntimeError("board-constituents failed")
            e.__cause__ = err
            return e

        # 刀 3（CR9-112）：这一族**有**这块板、只是零成分 ⇒ akshare 在 utils/func.py:38 除零抛
        ak.stock_board_concept_cons_em = _cons("em-concept", ZeroDivisionError("division by zero"))
        ak.stock_board_industry_cons_em = _cons("em-industry")
        seen.clear(); fails.clear(); oks.clear()
        r5 = pl.map_board_products("电源设备")
        check("刀3：概念腿抛 ZeroDivisionError（＝`total=0` 那一形）⇒ 换下一腿、行业腿把成分取回来",
              seen == [("em-concept", "电源设备"), ("em-industry", "BK1033")]
              and r5["source"] == "em-industry" and r5["legOutcomes"] == ["em-concept:ZeroDivisionError", "em-industry:ok"],
              f"{seen} / {r5.get('legOutcomes')}")
        check("刀3：零成分那一腿的失败被第二腿的成功压掉 ⇒ 东财族只收到一枚 `ok`（刀 1 那枚收口在此生效）",
              len(fails) == 0 and len(oks) == 1, f"fails={len(fails)} oks={len(oks)}")
        orig_wl_now = pl._BOARD_DATA_SHAPE_ERRORS
        pl._BOARD_DATA_SHAPE_ERRORS = ()
        ak.stock_board_concept_cons_em = _cons("em-concept", ZeroDivisionError("division by zero"))
        seen.clear(); fails.clear(); oks.clear()
        r6 = pl.map_board_products("电源设备")
        check("刀3🔁：清空白名单＝零成分那一形又判成『上游不可信』⇒ 一腿都不追加（证种类名不是白拿的）",
              seen == [("em-concept", "电源设备")] and r6["source"] == "sina-test", str(seen))
        pl._BOARD_DATA_SHAPE_ERRORS = orig_wl_now

        check("甲′ 判据：RuntimeError from IndexError ⇒ 可换下一腿",
              pl._board_leg_is_data_shape(_wrapped(IndexError())) is True)
        check("甲′ 判据：裸 KeyError（列名对不上那一形，没有 __cause__）⇒ 同样可换下一腿",
              pl._board_leg_is_data_shape(KeyError("板块名称")) is True)
        check("甲′ 判据：RuntimeError from TimeoutError ⇒ 不换（默认按上游不可信）",
              pl._board_leg_is_data_shape(_wrapped(TimeoutError())) is False)
        check("甲′ 判据：没见过的形态（ValueError）⇒ 不猜，按不换处理",
              pl._board_leg_is_data_shape(ValueError()) is False)
        check("刀3 判据：RuntimeError from ZeroDivisionError ⇒ 换（payload 结构完整＝数据形态）",
              pl._board_leg_is_data_shape(_wrapped(ZeroDivisionError())) is True)
        check("刀3 判据钉『不动』：RuntimeError from TypeError ⇒ 不换——`func.py:37` 让『这个 BK 没数据』"
              "与『东财软拒（200 空 body）』同一句，源码层不可分辨；放宽这一条必须先改这枚绿字",
              pl._board_leg_is_data_shape(_wrapped(TypeError("NoneType object is not subscriptable"))) is False)
    finally:
        for n, v in orig_ak.items():
            setattr(ak, n, v)
        pl._sina_board_products = orig_sina
        pl._EM.acquire, pl._EM.on_success, pl._EM.on_failure = orig_em
        pl._board_code = orig_bc
        pl._BOARD_DATA_SHAPE_ERRORS = orig_wl


def test_board_leg_reports_once() -> None:
    """CR9-112（#79 后续 P1）：一次映射＝一枚逻辑请求 ⇒ 只回报一次（C29，`docs/CONSTRAINTS.md:63`）。

    为什么这是缺陷不是口径之争：`acquire()` 在两条腿的循环**外**（`pipeline.py:878`），而甲′
    加宽换腿之后 `except` 在循环**内** ⇒ 一枚坏板块能连报两枚失败，达到 `failure_threshold=2`
    当场把整个东财族锁 180s（`limiter.py:185-193`），而个股新闻与转债→正股映射共用这一族
    （`akshare_provider.py:76`）。旧写法因为无条件 `break` 恰好只报一枚，所以这条违例是加宽之后才有的。
    这里一枚都不出网，只数回报次数。
    """
    import akshare as ak
    import pandas as pd

    ak_names = ("stock_board_concept_cons_em", "stock_board_industry_cons_em")
    orig_ak = {n: getattr(ak, n) for n in ak_names}
    orig_sina = pl._sina_board_products
    orig_em = (pl._EM.acquire, pl._EM.on_success, pl._EM.on_failure)
    orig_bc = pl._board_code
    orig_note = pl._board_note_outcome
    orig_flush = pl._board_flush

    seen: list[tuple[str, str]] = []
    fails: list[str] = []
    oks: list[str] = []

    def _cons(tag: str, err: Exception | None = None, empty: bool = False):
        def _f(symbol: str):
            seen.append((tag, symbol))
            if err is not None:
                raise err
            if empty:
                return pd.DataFrame()
            return pd.DataFrame({"代码": ["300750"], "名称": ["宁德时代"]})
        return _f

    try:
        pl._EM.acquire = lambda *a, **k: True
        pl._EM.on_success = lambda: oks.append("ok")
        pl._EM.on_failure = lambda: fails.append("fail")
        pl._sina_board_products = lambda board, limit=6: {
            "stocks": [{"code": "300750", "name": "宁德时代"}], "source": "sina-test", "note": None,
        }
        codes = {("电源设备", "em-concept"): None, ("电源设备", "em-industry"): "BK1033"}
        pl._board_code = lambda board, tag: codes.get((board, tag))

        err = IndexError("单测桩：这一族没有这个板块")
        ak.stock_board_concept_cons_em = _cons("em-concept", err)
        ak.stock_board_industry_cons_em = _cons("em-industry", err)
        seen.clear(); fails.clear(); oks.clear()
        r = pl.map_board_products("电源设备")
        check("CR9-112：两腿背靠背失败 ⇒ 东财族只收到**一枚**失败（旧形两枚＝一枚坏板块直接熔断）",
              len(fails) == 1 and len(oks) == 0, f"fails={len(fails)} oks={len(oks)}")
        check("CR9-112：回报口径收口没把换腿语义带跑（第二腿照样发出去、仍落新浪）",
              seen == [("em-concept", "电源设备"), ("em-industry", "BK1033")] and r["source"] == "sina-test",
              str(seen))
        check("刀2：两枚失败在 `legOutcomes` 里各留一种类名（种类＝异常类名本身，没被折成 other）",
              r["legOutcomes"] == ["em-concept:IndexError", "em-industry:IndexError"],
              str(r.get("legOutcomes")))

        # 🔁 摘刀＝改回逐腿即报（CR9-110 那一版的形状），同一输入必须数到两枚失败
        pl._board_note_outcome = lambda rep, ok: (
            pl._EM.on_success() if ok else pl._EM.on_failure()
        )
        pl._board_flush = lambda rep: None
        seen.clear(); fails.clear(); oks.clear()
        pl.map_board_products("电源设备")
        check("CR9-112🔁：摘掉那枚收口＝同一输入两枚失败 ⇒ 熔断被一枚坏板块推进（证差异出自收口）",
              len(fails) == 2 and len(oks) == 0, f"fails={len(fails)} oks={len(oks)}")
        pl._board_note_outcome = orig_note
        pl._board_flush = orig_flush

        # 空表那一档：一枚都不报，且 `df` 为空时必须 continue 而不是落到 _pick_col
        ak.stock_board_concept_cons_em = _cons("em-concept", empty=True)
        ak.stock_board_industry_cons_em = _cons("em-industry", empty=True)
        seen.clear(); fails.clear(); oks.clear()
        r_empty = pl.map_board_products("电源设备")
        check("CR9-112：空表不记成功也不记失败（删掉那句 continue 会让空表抛 IndexError＝多报一枚失败）",
              seen == [("em-concept", "电源设备"), ("em-industry", "BK1033")]
              and len(fails) == 0 and len(oks) == 0,
              f"{seen} fails={len(fails)} oks={len(oks)}")
        check("刀2：空表那一档的种类名＝`empty`（它与 `norows` 是两格，别并成一格）",
              r_empty["legOutcomes"] == ["em-concept:empty", "em-industry:empty"],
              str(r_empty.get("legOutcomes")))

        # 首腿就命中：出口只报一次（多报会在这里数出 2）
        ak.stock_board_concept_cons_em = _cons("em-concept")
        ak.stock_board_industry_cons_em = _cons("em-industry")
        seen.clear(); fails.clear(); oks.clear()
        pl.map_board_products("电源设备")
        check("CR9-112：首腿命中 ⇒ 一枚 ok、第二腿不再发（成功出口也只有一个回报点）",
              len(oks) == 1 and len(fails) == 0 and seen == [("em-concept", "电源设备")],
              f"{seen} fails={len(fails)} oks={len(oks)}")
    finally:
        for n, v in orig_ak.items():
            setattr(ak, n, v)
        pl._sina_board_products = orig_sina
        pl._EM.acquire, pl._EM.on_success, pl._EM.on_failure = orig_em
        pl._board_code = orig_bc
        pl._board_note_outcome = orig_note
        pl._board_flush = orig_flush


def test_board_path_stats_two_gates_and_free_signal() -> None:
    """#44（CR9-72）：`_board_path_stats` 那六格各自咬得住什么。

    这族是纯函数读数，所以每条都要先问「哪一处回退会让它红」——尤其**与扇出常数同写**那两条：
    只断 `savedRequestsEstimate` 的绝对值，常数被人改成 5 时它照样绿。
    """
    prev = pl._board_cache.get("codes")
    try:
        pl._board_cache["codes"] = (time.time(), {
            "光伏设备": {"em-concept": "BK0446"},
            "电源设备": {"em-concept": "BK1033", "em-industry": "BK1033"},
            "储能": {},
        })
        s = pl._board_path_stats(["code", "code", "name"])
        check("#44：两格分开计数（代码路径 ⇔ 名称路径），不是一个 bool",
              s["byCode"] == 2 and s["byName"] == 1, str(s))
        check("#44：恒等式 `byCode + byName == 真发出去的成分请求次数`",
              s["byCode"] + s["byName"] == 3, str(s))
        check("#44：`emCodeRows` 数的是 (名, 源) 配对行而非板块个数（「储能」那行空 dict 不占一格）",
              s["emCodeRows"] == 3, str(s["emCodeRows"]))
        check("#44：省下的那条是**按实测扇出折算**，两个扇出常数必须与它同写（读的人能自己复算）",
              s["savedRequestsEstimate"] == 16 and s["requestsPerNamePath"] == 9
              and s["requestsPerCodePath"] == 1, str(s)[:200])
        check("#44：折算用的两个常数就是模块里那一对（写死与取常量各断一次＝两种失败形态都要红）",
              s["requestsPerNamePath"] == pl._BOARD_CONS_REQ_BY_NAME
              and s["requestsPerCodePath"] == pl._BOARD_CONS_REQ_BY_CODE, str(s)[:160])

        pl._board_cache["codes"] = (time.time(), {})
        z = pl._board_path_stats([])
        check("🔁 名单没通那一档：`emCodeRows` 归 0 ⇔ 映射表一条代码都没给（这就是那枚免费读数）",
              z["emCodeRows"] == 0 and z["byCode"] == 0 and z["byName"] == 0
              and z["savedRequestsEstimate"] == 0, str(z))
        del pl._board_cache["codes"]
        n = pl._board_path_stats(["name"])
        check("缓存整个不存在时不抛（新进程首帧就是这个形态），计数照旧按发出去的那一算",
              n["emCodeRows"] == 0 and n["byName"] == 1, str(n))
        pl._board_cache["codes"] = (time.time(), {"A": {"em-concept": "BK0001"}})
        a1 = pl._board_path_stats(["code", "name", "code"])
        a2 = pl._board_path_stats(["name", "code", "code"])
        check("🔁 计数与到达顺序无关（挡住「只看第一发」那类退化写法）", a1 == a2, str([a1, a2])[:200])
    finally:
        if prev is None:
            pl._board_cache.pop("codes", None)
        else:
            pl._board_cache["codes"] = prev


def test_board_paths_reach_state_file_from_the_event_path() -> None:
    """#44：读数必须落到盘上，而这条断言**只从事件路径读**（一次都不手调 `_board_path_stats`）。

    全链只假在四处：`fetch_news`／`structure_topics`／`map_board_products`（为零出网）／`emit_ingest`。
    中间四层——真 `build_items` → `_board_path_stats` → `run_pipeline` → `scheduler._execute`
    → `_write_state`——没人手调：摘掉 `result["boardPaths"]` 那一行、或摘掉 `build_items` 里
    那句 `forms.extend(...)`，下面第一条就红（CR9-69 学到的「出厂自带一条只从事件读」）。
    """
    import shutil
    import tempfile

    import app.hotspot.scheduler as hs

    tmpdir = tempfile.mkdtemp()
    prev_env = os.environ.get("HOTSPOT_STATE_FILE")
    prev_state = dict(hs._state)
    orig = (pl.fetch_news, pl.structure_topics, pl.map_board_products, pl.emit_ingest)
    sent: dict = {}
    os.environ["HOTSPOT_STATE_FILE"] = os.path.join(tmpdir, "hotspot-state.json")
    try:
        hs._state.update({"running": True, "runs": 0, "lastRun": None,
                          "lastResult": None, "catchUpResolved": None})
        pl.fetch_news = lambda **kw: {"items": [], "source": "t", "sources": ["t"], "note": None,
                                      "degraded": False, "stats": STUB_STATS, "samples": STUB_SAMPLES}
        pl.structure_topics = lambda items, **kw: {
            "topics": [{"title": "甲", "boards": ["B1", "B2"]}], "engine": "llm", "note": None}
        pl.map_board_products = lambda board, limit=6: {
            "stocks": [{"code": "601012", "name": "x"}], "source": "em-concept",
            "note": None, "pathForms": ["code"], "legOutcomes": ["em-concept:ok"]}
        pl.emit_ingest = lambda payload: (sent.update(payload), {"inserted": 1})[1]
        res = hs._execute("unit-test-paths")
        disk = (hs.read_state() or {}).get("lastResult") or {}
        p = disk.get("boardPaths") or {}
        check("前提先钉住：这一轮**真走完了**（emit 拿到载荷、盘上有 lastResult），不是测试自己填的内存",
              bool(sent) and bool(disk), str(res)[:150])
        check("#44：盘上读得到 `boardPaths`，且两个板块各一发代码路径是被真 `build_items` 累加进来的",
              p.get("byCode") == 2 and p.get("byName") == 0, str(p)[:200])
        check("#44：扇出常数与读数出自**同一份载荷**（读它不用去 import 私有常量）",
              p.get("requestsPerNamePath") == 9 and p.get("savedRequestsEstimate") == 16, str(p)[:200])
        # 刀 2（CR9-112）：每腿种类读数同处落盘——它回答的是"真上游这一轮到底抛了什么"
        check("刀2：盘上读得到 `boardPaths[\"legs\"]`，两个板块各一枚 `em-concept:ok` 是被真 `build_items` 累加进来的",
              p.get("legs", {}).get("attempts") == 2
              and p.get("legs", {}).get("byClass", {}).get("em-concept:ok") == 2,
              str(p.get("legs"))[:200])
        check("刀2：`legOutcomes` 没漏进落库 payload（读的是真 emit 拿到的那一份）",
              "legOutcomes" not in sent and "legOutcomes" not in str(sent),
              str(sorted(sent.keys()))[:200])
        check("落库 payload 里没有这份读数（读的是真 emit 拿到的那一份，不是手搭的）",
              "boardPaths" not in sent and "pathForms" not in str(sent),
              str(sorted(sent.keys()))[:200])
        check("🔁 上屏那层没被它带跑：`note` 里不含 `boardPaths`／`pathForms`／`legOutcomes` 的字面",
              all(k not in str(res.get("note")) for k in ("boardPaths", "pathForms", "legOutcomes", "legs")),
              str(res.get("note"))[:160])
    finally:
        pl.fetch_news, pl.structure_topics, pl.map_board_products, pl.emit_ingest = orig
        hs._state.clear()
        hs._state.update(prev_state)
        if prev_env is None:
            os.environ.pop("HOTSPOT_STATE_FILE", None)
        else:
            os.environ["HOTSPOT_STATE_FILE"] = prev_env
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_build_items_deadline_expired()
    test_build_items_within_deadline()
    test_topic_urls_title_passthrough()
    test_run_pipeline_reasons_split()
    test_board_code_shortcut()
    test_board_leg_exception_split()
    test_board_leg_reports_once()
    test_run_pipeline_deadline_env()
    test_board_path_stats_two_gates_and_free_signal()
    test_board_paths_reach_state_file_from_the_event_path()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
