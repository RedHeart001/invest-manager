"""CR6-P2-3 离线单测：热点 pipeline 整体 deadline 降级。

运行方式（无需服务在跑）：
    .venv/Scripts/python tests/test_cr6_pipeline.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


if __name__ == "__main__":
    test_build_items_deadline_expired()
    test_build_items_within_deadline()
    test_run_pipeline_deadline_env()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
