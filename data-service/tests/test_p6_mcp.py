"""P6（M7 ③）离线单测：fastmcp MCP server 的工具暴露与降级行为。

运行方式（无需服务在跑）：
    .venv/Scripts/python tests/test_p6_mcp.py

说明：核心断言全部离线可复现；网络依赖项（真实行情）单独标注，失败不计入 NG。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# web BFF 指向不可达端口 → 验证 search_products 回调降级（不直连库）
os.environ["WEB_API_BASE"] = "http://127.0.0.1:9"

from fastmcp import Client  # noqa: E402

from app.mcp_server import mcp  # noqa: E402

results: list[tuple[str, bool, str]] = []
notes: list[str] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


EXPECTED_TOOLS = {
    "get_quote",
    "get_kline",
    "list_products",
    "get_stock_news",
    "get_fund_holdings",
    "get_fund_report",
    "get_hotspot_status",
    "get_research_status",
    "get_research_latest",
    "search_products",
}

# 只读约束：MCP server 不得暴露任何写/交易类工具
FORBIDDEN_HINTS = ("order", "trade", "buy", "sell", "delete", "write", "update", "cancel")


async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}

        check("工具全集与设计一致", names == EXPECTED_TOOLS, f"missing={EXPECTED_TOOLS - names} extra={names - EXPECTED_TOOLS}")
        check("工具数量 = 10", len(names) == 10, f"count={len(names)}")

        bad = [n for n in names if any(h in n.lower() for h in FORBIDDEN_HINTS)]
        check("只读约束：无写/交易类工具", bad == [], f"违规={bad}")

        # 必需参数缺失 → 明确报错（不静默返回空）
        try:
            await client.call_tool("get_quote", {"type": "stock"})
            check("get_quote 缺 code 时报错", False, "未抛错")
        except Exception as e:  # noqa: BLE001
            check("get_quote 缺 code 时报错", "code" in str(e).lower(), str(e)[:80])

        try:
            await client.call_tool("search_products", {"q": "  "})
            check("search_products 空关键词报错", False, "未抛错")
        except Exception as e:  # noqa: BLE001
            check("search_products 空关键词报错", "q" in str(e).lower(), str(e)[:80])

        # 回调 web BFF：不可达时降级为 degraded（不抛错，不直连库）
        res = await client.call_tool("search_products", {"q": "贵州茅台"})
        payload = res.data if hasattr(res, "data") else res.structured_content
        check("search_products 回调 BFF 不可达 → 降级标注", isinstance(payload, dict) and payload.get("degraded") is True, str(payload)[:120])
        check("降级响应含 note 说明", bool((payload or {}).get("note")), str(payload)[:120])

        # 网络依赖项（非 NG）：真实行情链路
        try:
            q = await client.call_tool("get_quote", {"type": "stock", "code": "600519"})
            data = q.data if hasattr(q, "data") else q.structured_content
            price = (data or {}).get("price")
            notes.append(f"[网络项] get_quote 600519 → price={price} source={(data or {}).get('source')}")
        except Exception as e:  # noqa: BLE001
            notes.append(f"[网络项] get_quote 600519 不可用（外部源/沙箱限制）：{str(e)[:80]}")

    print()
    for n in notes:
        print(n)

    failed = [r for r in results if not r[1]]
    print(f"\n== MCP server 单测：{len(results) - len(failed)}/{len(results)} 通过 ==")
    if failed:
        for name, _, detail in failed:
            print(f"  - {name} {detail}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
