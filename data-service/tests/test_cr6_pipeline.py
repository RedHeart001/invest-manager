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

    pl.fetch_news = lambda **kw: {"items": [], "source": "test", "note": None, "degraded": False}
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
    test_board_code_shortcut()
    test_run_pipeline_deadline_env()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
