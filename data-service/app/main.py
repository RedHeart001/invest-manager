"""invest-manager data-service 入口。

无状态数据适配层：Provider 层（外部数据源 → 统一 JSON schema）对外暴露
REST 接口，供 Next.js BFF 调用。不建库、不写盘。
"""

import os

# Windows 上 requests 会读取系统注册表代理；系统代理不可达时东财等
# 国内数据源请求全部失败（ProxyError）。数据源默认直连，需要走代理时
# 显式设置 NO_PROXY 为空（或具体域名列表）。
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .hotspot import scheduler as hotspot_scheduler
from . import sync_scheduler
from .providers import (
    ProviderError,
    ProviderNotSupported,
    get_list_provider,
    get_provider_chain,
)
from .research import tasks as research_tasks


def _primary(type_: str):
    """取主源（用于无备源的单能力端点：新闻/持仓/收益率曲线）。"""
    try:
        return get_provider_chain(type_)[0]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"unsupported type: {type_}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # P3：启动热点调度（盘前/盘后 + 启动补跑）
    hotspot_scheduler.start_scheduler()
    # G2（批次 D）：启动产品主数据每日同步调度（含启动补跑）
    sync_scheduler.start_scheduler()
    yield
    hotspot_scheduler.shutdown_scheduler()
    sync_scheduler.shutdown_scheduler()


app = FastAPI(title="invest-manager data-service", version="0.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


from .providers.chain import chain_call as _providers_chain_call  # noqa: E402


def _chain_call(type_: str, fn) -> dict:
    """按主备源链依次尝试（R15/M8，B4：公共实现 providers/chain.py）。"""
    try:
        return _providers_chain_call(type_, fn)
    except ProviderError as e:
        if str(e).startswith("unsupported type"):
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise


@app.get("/health")
def health():
    # CR-22：附带看门狗"已放弃存活线程"计数，供运维观测上游是否持续挂起
    from .utils.timeout import abandoned_count

    return {"status": "ok", "version": app.version, "abandonedWatchdogs": abandoned_count()}


@app.get("/quote")
def quote(
    type: str = Query("stock", description="产品类型：stock/fund/bond/crypto/hk/us"),
    code: str = Query(..., description="产品代码，如 600519"),
):
    try:
        return _chain_call(type, lambda p: p.get_quote(type, code))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/quotes")
def quotes(
    type: str = Query("stock"),
    codes: str = Query(..., description="逗号分隔的代码列表，如 600519,000001"),
):
    """批量行情（搜索结果价格富集，单次外部请求）。"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()][:100]
    if not code_list:
        raise HTTPException(status_code=400, detail="codes is empty")
    try:
        data = _chain_call(type, lambda p: {"quotes": p.get_quotes(type, code_list)})
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"type": type, "quotes": data.get("quotes", {}), "note": data.get("note")}


# ---------- R13 新增：双源交叉验证（G3 / 批次 D） ----------


@app.get("/quote/verified")
def quote_verified(
    type: str = Query("stock", description="产品类型"),
    code: str = Query(..., description="产品代码"),
    field: str = Query("price", description="比对字段（price/prevClose/close 等）"),
    threshold_pct: float = Query(0.5, description="偏差阈值（相对 %），超出则显式标注"),
):
    """行情 + 双源交叉验证（R13）：主源结果叠加备源比对，差异超阈值显式标注。

    按需端点——不叠加到普通 /quote，避免成倍放大对限流敏感的数据源请求。
    """
    from .providers.chain import verify_metric

    try:
        return verify_metric(
            type,
            lambda p: p.get_quote(type, code),
            field=field,
            threshold_pct=max(0.0, min(threshold_pct, 100.0)),
        )
    except ProviderError as e:
        if str(e).startswith("unsupported type"):
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/kline")
def kline(
    type: str = Query("stock"),
    code: str = Query(...),
    start: str = Query(None, description="开始日期 YYYYMMDD"),
    end: str = Query(None, description="结束日期 YYYYMMDD"),
    interval: str = Query(
        "1d", description="1d 日线（默认）| 1m 当日 1 分钟分时（仅场内品种）"
    ),
):
    try:
        return _chain_call(
            type,
            lambda p: p.get_kline(type, code, start=start, end=end, interval=interval),
        )
    except ProviderNotSupported as e:
        raise HTTPException(status_code=501, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/products")
def products(
    type: str = Query(..., description="产品类型：stock/fund/bond/crypto"),
):
    """全量产品列表（供 BFF 同步落库，低频调用）。"""
    try:
        provider = get_list_provider(type)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"unsupported list type: {type}")
    try:
        items = provider.list_products(type)
    except ProviderNotSupported as e:
        raise HTTPException(status_code=501, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"type": type, "count": len(items), "products": items}


# ---------- P2 新增：详情页数据接口（R10：失败降级为 200 + degraded 标注） ----------


@app.get("/news")
def news(
    code: str = Query(..., description="个股代码，如 600519"),
):
    """个股新闻（事件标注数据源，内存缓存 10 分钟）。"""
    try:
        provider = _primary("stock")
        items = provider.get_news(code)
    except ProviderError as e:
        return {"code": code, "degraded": True, "note": str(e), "items": []}
    return {"code": code, "degraded": False, "note": None, "items": items}


@app.get("/fund/holdings")
def fund_holdings(
    code: str = Query(..., description="场外基金代码，如 110022"),
):
    """基金重仓持股（最新披露季度 Top10）。"""
    try:
        provider = _primary("fund")
        data = provider.get_fund_holdings(code)
    except ProviderError as e:
        return {"code": code, "degraded": True, "note": str(e), "holdings": [], "quarter": None}
    return {**data, "degraded": False, "note": None}


@app.get("/bond/yieldcurve")
def bond_yieldcurve(
    days: int = Query(90, description="返回最近 N 个交易日，默认 90"),
):
    """中美国债收益率（明细区债券槽位，内存缓存 30 分钟）。"""
    try:
        provider = _primary("bond")
        data = provider.get_yield_curve(days=min(max(days, 5), 365))
    except ProviderError as e:
        return {"degraded": True, "note": str(e), "curve": []}
    return {**data, "degraded": False, "note": None}


# ---------- P6 新增：基金定期报告（技能 fund-report-analysis 数据源） ----------


@app.get("/fund/report")
def fund_report(
    code: str = Query(..., description="场外基金代码，如 110022"),
):
    """基金定期报告清单 + 行业配置（内存缓存 6 小时）。"""
    try:
        provider = _primary("fund")
        data = provider.get_fund_report(code)
    except ProviderError as e:
        return {
            "code": code,
            "degraded": True,
            "note": str(e),
            "reports": [],
            "industry": None,
        }
    return {**data, "degraded": False, "note": None}


# ---------- P3 新增：热点 pipeline（M1） ----------


@app.post("/hotspots/run")
def hotspots_run(trigger: str = Query("manual-ui", description="触发来源标注")):
    """手动触发热点任务（M4：后台执行，立即返回；进度经 /hotspots/status 轮询）。"""
    return hotspot_scheduler.request_run(trigger=trigger)


@app.get("/hotspots/status")
def hotspots_status():
    """调度状态：下次执行时间、最近一次结果、时区。"""
    return hotspot_scheduler.status()


# ---------- G2 新增：产品主数据每日同步调度（批次 D） ----------


@app.post("/sync/run")
def sync_run(trigger: str = Query("manual-ui", description="触发来源标注")):
    """手动触发产品主数据同步（G2：BFF 侧另有 /api/sync 直连入口，此为调度侧）。

    C4（CR7-10，2026-09-25）：异步化——认领后立即返回 `{accepted: true}`，
    同步由后台线程执行（15min+ 级）；进度见 `GET /sync/status`。
    已在跑时返回 `{accepted: false, note: ...}`（原 skipped 语义并入 accepted）。
    """
    return sync_scheduler.run_now(trigger=trigger)


@app.get("/sync/status")
def sync_status():
    """同步调度状态：下次执行时间、最近一次结果、时区。"""
    return sync_scheduler.status()


# ---------- P5 新增：深度研究（M5） ----------


@app.post("/research/start")
def research_start(body: dict):
    """提交深度研究任务（异步）。body: {type, code, name?}"""
    type_ = str(body.get("type", "stock")).strip()
    code = str(body.get("code", "")).strip()
    name = str(body.get("name", "") or code).strip()
    if not code:
        raise HTTPException(status_code=400, detail="code is required")
    result = research_tasks.start_research(type_, code, name)
    if result.get("rejected"):
        # CR6-P1-1：409 响应体同时带 detail，与其它端点的错误口径一致
        # （web 侧按 status/body 分流，detail 便于日志与人工定位）。
        return JSONResponse({**result, "detail": result["rejected"]}, status_code=409)
    return result


@app.get("/tasks/{task_id}")
def task_status(task_id: str):
    """轮询任务状态（PLAN：BFF 轮询 /tasks/{id}）。"""
    t = research_tasks.get_task(task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="task not found")
    return t


@app.get("/research/latest")
def research_latest(
    type: str = Query("stock"),
    code: str = Query(...),
):
    """最近一次完成的研究结果（内存注册表；BFF 落库后以库为准）。"""
    r = research_tasks.latest_done(type, code)
    if r is None:
        raise HTTPException(status_code=404, detail="no research result")
    return r


@app.get("/research/status")
def research_status():
    """研究任务总览（运行数 / 当日完成）。"""
    return research_tasks.statuses()
