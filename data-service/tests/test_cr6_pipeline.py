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


def test_build_items_deadline_expired() -> None:
    """deadline 已过期 → 不调用 map_board_products，但每个 topic 仍产出，带降级 note。"""
    calls = {"n": 0}
    orig = pl.map_board_products

    def _boom(board):
        calls["n"] += 1
        return {"stocks": [], "note": None}

    pl.map_board_products = _boom
    try:
        # deadline 设为过去时刻：立即判定超时
        items, notes = pl.build_items(_topics(), {"items": []}, deadline=time.monotonic() - 1)
    finally:
        pl.map_board_products = orig

    check("P2-3：超时后不再调用外部映射", calls["n"] == 0, str(calls))
    check("P2-3：每个 topic 仍产出（不整段丢弃）", len(items) == 5, str(len(items)))
    check("P2-3：relatedCodes 为空（未映射）", all(i["relatedCodes"] == [] for i in items))
    check("P2-3：note 标注降级", any("超时" in n for n in notes), str(notes))


def test_build_items_within_deadline() -> None:
    """deadline 充裕 → 正常映射，无降级 note。"""
    calls = {"n": 0}
    orig = pl.map_board_products

    def _ok(board):
        calls["n"] += 1
        return {"stocks": [{"code": "000001", "name": "x"}], "note": None}

    pl.map_board_products = _ok
    try:
        items, notes = pl.build_items(_topics(), {"items": []}, deadline=time.monotonic() + 999)
    finally:
        pl.map_board_products = orig

    check("P2-3：未超时则正常映射（5 topic × 2 board）", calls["n"] == 10, str(calls))
    check("P2-3：未超时不加降级 note", not any("超时" in n for n in notes), str(notes))
    check("P2-3：未超时 relatedCodes 非空", all(len(i["relatedCodes"]) == 2 for i in items))


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
        return [], []

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
        pl.build_items = lambda topics, news, deadline=None: (items, [board_note])
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
        # 🔁 旁路代码查询：必须退回"按名称请求"的原行为，证明差异出自缓存命中而非改写语义
        orig_bc = pl._board_code
        pl._board_code = lambda *a, **k: None
        try:
            seen.clear()
            pl.map_board_products("光伏设备")
            check("CR9-3a🔁：无代码时按名称请求（原行为）", seen == ["光伏设备"], str(seen))
        finally:
            pl._board_code = orig_bc
    finally:
        for n, v in orig_ak.items():
            setattr(ak, n, v)
        pl._sina_board_products = orig_sina
        pl._EM.acquire, pl._EM.on_success, pl._EM.on_failure = orig_em
        pl._board_cache.clear()


if __name__ == "__main__":
    test_build_items_deadline_expired()
    test_build_items_within_deadline()
    test_topic_urls_title_passthrough()
    test_run_pipeline_reasons_split()
    test_board_code_shortcut()
    test_run_pipeline_deadline_env()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
