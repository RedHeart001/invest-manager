"""MCP server：把 data-service 的统一行情能力暴露给外部 agent（PLAN M7 ③，P6）。

设计约束（2026-09-13 二轮定稿）：
- **只暴露 data-service 自有只读能力**（quote / kline / products / news / fund / research 状态）
- `search_products` 依赖 web 侧 Prisma FTS5 → 本 server **回调 web BFF `/api/search`**，
  不直连数据库（保持 data-service 无状态铁律）
- 对外能力全部只读，无写操作、无下单类工具
- 传输：stdio（默认，供 Claude Code 等本地客户端）与 streamable-http（**仅绑定 127.0.0.1**）

用法：
    python -m app.mcp_server            # stdio
    python -m app.mcp_server --http     # 127.0.0.1:8765 (streamable-http)
"""

from __future__ import annotations

import os
import sys

# 与 main.py 一致：国内数据源默认直连（避免 Windows 注册表代理导致 ProxyError）
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

from .hotspot import scheduler as hotspot_scheduler
from .providers import ProviderError, get_list_provider, get_provider_chain
from .providers.chain import chain_call as _providers_chain_call
from .research import tasks as research_tasks

WEB_API_BASE = (
    os.environ.get("WEB_API_BASE")
    # 兼容：data-service 其他回调统一用 WEB_BASE_URL（hotspot/research），
    # P7 容器化只设一个变量也能生效
    or os.environ.get("WEB_BASE_URL")
    or "http://localhost:3000"
).rstrip("/")
MCP_HTTP_HOST = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
MCP_HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "8765"))
# D3（CR7-13）：list_products 看门狗阈值——外部 MCP 客户端不应感知"卡死"。
# 环境变量可覆盖（测试注入短超时用）。
MCP_LIST_TIMEOUT_S = float(os.environ.get("MCP_LIST_TIMEOUT_S", "120"))

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover - 依赖缺失时给出明确指引
    print(
        "fastmcp 未安装：请执行\n"
        "  .venv/Scripts/pip install fastmcp\n"
        "（或 pip install -r requirements.txt）后重试。",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _chain(type_: str, fn):
    """主备源链调用（B4：收敛到 providers/chain.py 公共实现）。"""
    return _providers_chain_call(type_, fn)


mcp = FastMCP(
    name="invest-manager-data",
    instructions=(
        "投资理财助手的数据服务：提供 A股/基金/债券/美股/加密的行情、日K、产品列表、"
        "个股新闻、基金持仓与定期报告，以及热点与深度研究任务状态。全部只读；"
        "数据来自公开免费源，可能延迟或降级（响应中的 source/note 会标注来源与降级状态）。"
    ),
)


@mcp.tool
def get_quote(type: str = "stock", code: str = "") -> dict:
    """获取单个产品的实时行情快照（价格、涨跌幅、开高低、成交量、来源标注）。

    type: stock / fund / bond / crypto / us / hk；code: 如 600519、110022、AAPL
    """
    if not code:
        raise ValueError("code is required")
    return _chain(type, lambda p: p.get_quote(type, code))


@mcp.tool
def get_kline(
    type: str = "stock",
    code: str = "",
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """获取日 K 数据（含区间首尾与来源标注）。start/end 形如 20260101，可省略。"""
    if not code:
        raise ValueError("code is required")
    return _chain(type, lambda p: p.get_kline(type, code, start=start, end=end, interval="1d"))


@mcp.tool
def list_products(type: str = "stock", limit: int = 50) -> dict:
    """列出某类产品（产品代码/名称/拼音），默认返回前 50 条（全量约 3.4 万条，勿全量拉取）。"""
    from .utils.timeout import run_with_timeout

    provider = get_list_provider(type)
    # D3（CR7-13，2026-09-25）：list_products 无内在超时（hk 直连分页可达数十发
    # 请求）——外部 MCP 客户端视角此前是"无响应卡死 4 分钟"。用看门狗包裹，
    # 超时按 ProviderError 降级语义返回（不挂死客户端）。
    value, err = run_with_timeout(lambda: provider.list_products(type), MCP_LIST_TIMEOUT_S, f"mcp.list_products({type})")
    if err is not None:
        return {
            "type": type,
            "count": 0,
            "products": [],
            "degraded": True,
            "note": f"产品列表获取失败（{err.__class__.__name__}: {err}）",
        }
    items = value or []
    return {"type": type, "count": len(items), "products": items[: max(1, min(limit, 200))]}


@mcp.tool
def get_stock_news(code: str = "") -> dict:
    """获取个股新闻（事件归因数据源，内存缓存 10 分钟）。"""
    if not code:
        raise ValueError("code is required")
    providers = get_provider_chain("stock")
    provider = providers[0]
    try:
        items = provider.get_news(code)
    except ProviderError as e:
        return {"code": code, "degraded": True, "note": str(e), "items": []}
    return {"code": code, "degraded": False, "note": None, "items": items}


@mcp.tool
def get_fund_holdings(code: str = "") -> dict:
    """获取场外基金最新披露的前十大重仓（含披露季度）。"""
    if not code:
        raise ValueError("code is required")
    provider = get_provider_chain("fund")[0]
    try:
        data = provider.get_fund_holdings(code)
    except ProviderError as e:
        return {"code": code, "degraded": True, "note": str(e), "holdings": [], "quarter": None}
    return {**data, "degraded": False, "note": None}


@mcp.tool
def get_fund_report(code: str = "") -> dict:
    """获取基金定期报告清单（季报/半年报/年报披露记录）与最新行业配置占比。"""
    if not code:
        raise ValueError("code is required")
    provider = get_provider_chain("fund")[0]
    try:
        data = provider.get_fund_report(code)
    except ProviderError as e:
        return {"code": code, "degraded": True, "note": str(e), "reports": [], "industry": None}
    return {**data, "degraded": False, "note": None}


@mcp.tool
def get_hotspot_status() -> dict:
    """获取热点 pipeline 的调度状态与最近一次产出摘要。"""
    return hotspot_scheduler.status()


@mcp.tool
def get_research_status() -> dict:
    """获取深度研究任务总览（运行中数量、当日完成清单）。"""
    return research_tasks.statuses()


@mcp.tool
def get_research_latest(type: str = "stock", code: str = "") -> dict:
    """获取某标的最近一次完成的深度研究结果（内存注册表口径）。"""
    if not code:
        raise ValueError("code is required")
    r = research_tasks.latest_done(type, code)
    if r is None:
        return {"status": "none", "note": "暂无该标的的已完成研报"}
    return r


@mcp.tool
async def search_products(q: str = "", type: str | None = None, limit: int = 8) -> dict:
    """搜索理财产品（名称/代码/拼音）。实现方式：回调 web BFF /api/search（本服务不直连数据库）。"""
    if not q.strip():
        raise ValueError("q is required")
    params: dict[str, str] = {"q": q.strip(), "limit": str(max(1, min(limit, 20)))}
    if type:
        params["type"] = type
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(f"{WEB_API_BASE}/api/search", params=params)
        if res.status_code != 200:
            return {
                "degraded": True,
                "note": f"web BFF 返回 {res.status_code}（{WEB_API_BASE}）",
                "results": [],
            }
        return res.json()
    except Exception as e:  # noqa: BLE001 —— 依赖缺失/网络不可达一律降级而非报错
        return {"degraded": True, "note": f"web BFF 不可达：{e}（{WEB_API_BASE}）", "results": []}


def main() -> None:
    if "--http" in sys.argv:
        print(f"[mcp] streamable-http on http://{MCP_HTTP_HOST}:{MCP_HTTP_PORT}/mcp", flush=True)
        mcp.run(transport="http", host=MCP_HTTP_HOST, port=MCP_HTTP_PORT)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
