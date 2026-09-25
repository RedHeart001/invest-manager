"""D3（CR7-13）离线单测：hk 列表分页上限 + MCP list_products 看门狗。

背景：① hk_provider 分页循环无上限——上游 total 异常时以每页一发东财请求
长时间捶打源族（对照 akshare_provider 的 min(pages, 100)）；
② mcp_server.list_products 无内在超时——外部 MCP 客户端视角是"卡死 4 分钟"。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_d3_guards.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def test_hk_pagination_cap() -> None:
    """① total 异常大 → 分页被截到 100 页，超出的页不再请求。"""
    import app.providers.hk_provider as hp

    calls = {"clist": 0}

    def _fake_em_json(hosts, path, params):
        if path.endswith("/ulist.np/get"):
            return {"data": {"diff": [{"f12": "00700", "f14": "腾讯控股"}]}}
        if path.endswith("/clist/get"):
            pn = str(params.get("pn", "1"))
            if pn == "1":
                # total 声称 100 万条（异常值）→ 按每页 1 条会算出 100 万页
                return {"data": {"total": 1_000_000, "diff": [{"f12": "00700", "f14": "腾讯控股"}]}}
            calls["clist"] += 1
            return {"data": {"total": 1_000_000, "diff": [{"f12": "00700", "f14": "腾讯控股"}]}}
        raise AssertionError(path)

    p = hp.HkProvider()
    p._em_json = _fake_em_json  # type: ignore[assignment]
    products = p.list_products("hk")
    # 上限 100 页 → clist 额外调用 ≤ 99 次（第 1 页不计）；无上限会是 ~100 万次
    check(
        "D3：分页调用被上限截断（≤99 次额外请求）",
        0 < calls["clist"] <= 99,
        f"实际额外调用 {calls['clist']} 次",
    )
    check("D3：列表仍产出（截断不阻塞主流程）", len(products) >= 1, str(len(products)))


def test_hk_pagination_normal_unaffected() -> None:
    """② 正常 total（如 3 条 2 页）→ 分页行为不变（上限不误伤）。"""
    import app.providers.hk_provider as hp

    calls = {"clist": 0}

    def _fake_em_json(hosts, path, params):
        if path.endswith("/ulist.np/get"):
            return {"data": {"diff": []}}
        if path.endswith("/clist/get"):
            pn = str(params.get("pn", "1"))
            if pn == "1":
                return {"data": {"total": 3, "diff": [{"f12": "89988", "f14": "阿里巴巴-WR"}]}}
            calls["clist"] += 1
            return {"data": {"total": 3, "diff": [
                {"f12": "00700", "f14": "腾讯控股"},
                {"f12": "09988", "f14": "阿里巴巴-W"},
            ]}}
        raise AssertionError(path)

    p = hp.HkProvider()
    p._em_json = _fake_em_json  # type: ignore[assignment]
    products = p.list_products("hk")
    # page_size=1（首页 diff 1 条）→ 3 条共 3 页 → 第 2、3 页各一发 clist
    check("D3：正常分页不误伤（第 2、3 页各一发）", calls["clist"] == 2, str(calls))
    check("D3：正常列表产出 3 条", len(products) == 3, str(len(products)))


def test_mcp_list_products_watchdog() -> None:
    """③ MCP list_products：provider 挂死 → 看门狗按时返回降级 dict（不卡死）。"""
    import time as _t

    import app.mcp_server as mcp

    # FastMCP @mcp.tool 装饰后是 FunctionTool 包装，内层 .fn 才是原函数
    list_products_fn = mcp.list_products.fn

    class _HangingProvider:
        source = "hang"

        def list_products(self, type_: str):
            _t.sleep(60)  # 远超看门狗阈值（测试注入 2s）
            return []

    orig = mcp.get_list_provider
    orig_timeout = mcp.MCP_LIST_TIMEOUT_S
    mcp.MCP_LIST_TIMEOUT_S = 2.0  # 测试注入：2s 看门狗
    mcp.get_list_provider = lambda t: _HangingProvider()  # type: ignore[assignment]
    try:
        started = _t.time()
        res = list_products_fn("hk", 50)
        elapsed = _t.time() - started
        check("D3：挂死 provider 被看门狗按时截断（<10s）", elapsed < 10, f"{elapsed:.1f}s")
        check("D3：返回降级形态（degraded + note）", res.get("degraded") is True and "失败" in (res.get("note") or ""), str(res)[:120])
        check("D3：products 为空数组（无半成品）", res.get("products") == [])
    finally:
        mcp.get_list_provider = orig  # type: ignore[assignment]
        mcp.MCP_LIST_TIMEOUT_S = orig_timeout


def test_mcp_list_products_normal_passthrough() -> None:
    """④ 正常 provider → 结果原样透传（看门狗不误伤）。"""
    import app.mcp_server as mcp

    list_products_fn = mcp.list_products.fn

    class _FastProvider:
        source = "fast"

        def list_products(self, type_: str):
            return [{"code": "00700", "name": "腾讯控股", "pinyin": "gfk", "pinyinInitials": "gfk"}]

    orig = mcp.get_list_provider
    mcp.get_list_provider = lambda t: _FastProvider()  # type: ignore[assignment]
    try:
        res = list_products_fn("hk", 50)
        check("D3：正常 provider 原样透传", res.get("count") == 1 and res.get("products"), str(res)[:120])
        check("D3：无降级标注", "degraded" not in res or res.get("degraded") is not True)
    finally:
        mcp.get_list_provider = orig  # type: ignore[assignment]


if __name__ == "__main__":
    test_hk_pagination_cap()
    test_hk_pagination_normal_unaffected()
    test_mcp_list_products_watchdog()
    test_mcp_list_products_normal_passthrough()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
