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
from . import backup_scheduler, sync_scheduler
from .providers import (
    ProviderError,
    ProviderNotSupported,
    get_list_provider,
    get_provider_chain,
    list_products_with_meta,
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
    # ①（2026-10-02）：启动 dev.db 每日备份调度（**无补跑**，错过一轮等下一夜）
    backup_scheduler.start_scheduler()
    yield
    hotspot_scheduler.shutdown_scheduler()
    sync_scheduler.shutdown_scheduler()
    backup_scheduler.shutdown_scheduler()


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
async def health():
    # CR-22：附带看门狗"已放弃存活线程"计数，供运维观测上游是否持续挂起。
    #
    # CR9-45①（2026-10-01，主人点头）：**必须是 `async def`**。本服务所有端点都是同步
    # `def` ⇒ 它们共用 anyio 的默认 40 线程池（实测 `total_tokens == 40`）。同步版
    # `/health` 也排在这个池里，于是上游挂满 40 个取数线程时，连"你还活着吗"都答不出
    # （09-29 夜实测：补跑整轮 ≥29 分钟未收敛，`/health` 从 4.3s 涨到无响应）——
    # **探针和它要监控的东西抢同一份资源**。async 端点跑在事件循环上、不占线程池，
    # 永远能应答。函数体是一次廉价锁读，无需 await。
    # （② 落地后本端点更是双保险：并发等待已被 `MAX_INFLIGHT_WATCHDOGS` 钉住，
    #   取数线程"占满 40"这条路本身就不成立了。）
    from .utils.timeout import MAX_INFLIGHT_WATCHDOGS, abandoned_count, inflight_count
    from .utils.limiter import durable_today, durable_window, snapshot_all

    return {
        "status": "ok",
        "version": app.version,
        "abandonedWatchdogs": abandoned_count(),
        # CR9-45②：加"在飞/上限"两个数后，一次 curl 就能把
        # "进程死"（连不上）/"线程池饿死"（inflight 顶到上限）/"上游慢"（abandoned 涨）
        # 三种状态分开——CR9-30 同族的观测隔离。
        "inflightWatchdogs": inflight_count(),
        "watchdogInflightCap": MAX_INFLIGHT_WATCHDOGS,
        # 刀 4/G7（2026-10-01）：入库回调带 token 这件事**代码侧早就有了**（`hotspot/pipeline.py:652`、
        # `research/tasks.py:131`），开启鉴权只欠 web 与 ds **两侧同名 env 填成同一个值**。要防的
        # 失败形态是"只配了一侧 ⇒ 热点/研报入库全 401 且静默丢失"，而 ds 侧那声 `log.warning`
        # 在 uvicorn 默认配置下不一定看得见（#21 同族理由）⇒ 做成状态位：**只报布尔、绝不回显值**，
        # 主人填完 `.env` 一条 curl 就能核对两侧是否一致。
        "ingestTokenConfigured": bool(os.environ.get("INGEST_TOKEN", "")),
        # ①（2026-10-02，主人"执行推荐方案"轮）：`dev.db` 此前**零备份**——脚本有、单测有，
        # 但没有任何调度调它（10-01 审计实测 `backups/` 空）。现在它挂在 `backup_scheduler`
        # 的每日 job 上，而"昨夜到底备份成没成"必须一条 curl 可读（#21 同族：日志会被回收，
        # 状态位不会）。**只报时刻/成败/次数，不回显绝对路径。**
        "dbBackup": backup_scheduler.health(),
        # #27 第一步（10-03）：源族**真实计数**的读数面。此前"哪条路出了多少次网"只能靠日志
        # 反推（而 `log.info` 在 uvicorn 默认配置下根本不打），而给"打 eastmoney 域名却不占
        # 东财桶"那几处补限流，前提是先有次数可看。`akshare-obs` 族刻意只 observe 不 acquire
        # ⇒ 这一位是纯观测，不会把任何一条取数路径改成"到限就拒"。
        "limiters": snapshot_all(),
        # #41 甲（CR9-69，主人 10-06 的字＝"走甲"）：上面那一位是**进程内**的，重启即归零
        # （历次读数 11→10→47→2 非单调），所以 #27 第二步"拿一周计数定数值"取不到数。
        # 这一位读的是**落盘那份＋本进程未落盘的增量**＝"这一天到底出网多少次"，跨重启可读。
        "limitersDurable": durable_today(),
        # #42 丙（CR9-70，主人 10-06 20:3x 的字＝「走丙」）：上面那一位只回**今天这一格**，而 #27
        # 第二步的立项依据是"拿**一周**真实计数定数值"。缺的从来不是存储（日桶已经在盘上），
        # 是"把 7 格相加"这一步的读数出口 ⇒ 汇总长在`读`侧，写侧与留存上限（`KEEP_DAYS=30`）
        # 一字未动。`coveredDays` 会老实告诉你盘上到底只攒了几天——别把 2 天的数当一周读。
        "limitersWindow": durable_window(),
    }


@app.get("/quote")
def quote(
    type: str = Query("stock", description="产品类型：stock/fund/bond/crypto/hk/us"),
    code: str = Query(..., description="产品代码，如 600519"),
):
    try:
        return _chain_call(type, lambda p: p.get_quote(type, code))
    except ProviderError as e:
        # CR9-30：detail 必须点名是哪个标的。限速/熔断态下逐源理由只有
        # "eastmoney cooling down (rate-limited)"这类**与入参无关**的文案，
        # code 从错误里消失 ⇒ 运维与 LLM 看不出谁失败（今天两次让 test_p0
        # 在"环境噪声"与"真回归"之间无法判定）。
        raise HTTPException(status_code=502, detail=f"{type}/{code}: {e}")


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
    # 丙／CR9-67：把"这一批要不要按东财族节奏走"交给调用方，是为了让刷新腿只给**真打东财**
    # 的批次睡 5 秒（10-06 实测 fund 的 281 批里只有 31 批含场内代码，其余 249 批的 5 秒
    # 保护的是一个 30 分钟缓存、且不占东财桶的场外净值路径）。按**主源**路由算＝与本轮实际
    # 降级到哪家无关：令牌是向主源那条通道要的，而批间隔保护的是**桶**不是结果。
    em_batch = get_provider_chain(type)[0].touches_eastmoney(type, code_list)
    return {
        "type": type,
        "quotes": data.get("quotes", {}),
        "note": data.get("note"),
        "usesEastmoney": em_batch,
    }


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
    type: str = Query(
        ...,
        description="产品类型：stock/fund/bond/crypto/hk/us（可用集合＝列表注册表，未注册者 400）",
    ),
):
    """全量产品列表（供 BFF 同步落库，低频调用）。

    CR9-59（2026-10-04）：`us` 自此可取，但它是**有界子集**（新浪排行名单的前 N 页，
    `US_LIST_PAGES`）且恒带 `degraded`/`note` 声明覆盖面——不是"美股全量"。
    #35／CR9-63（2026-10-05）：这类"有意子集"另带 `intentionalSubset: true`，BFF 的降级
    缩水闸据此放行（没有这个声明的缩水仍按备源劣化挡回＝`web/lib/sync.ts`）。

    CR9-31：响应恒带 `source`（这批数据真正的出网上游），走内部备源时另带
    `degraded`/`note`——覆盖面缩水必须对消费侧可见（R16），否则 BFF 只能猜。
    `count`/`products` 的既有形态不变（新增键，不破坏既有调用方）。
    """
    try:
        provider = get_list_provider(type)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"unsupported list type: {type}")
    try:
        items, meta = list_products_with_meta(provider, type)
    except ProviderNotSupported as e:
        raise HTTPException(status_code=501, detail=str(e))
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"type": type, "count": len(items), "products": items, **meta}


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
def sync_run(
    trigger: str = Query("manual-ui", description="触发来源标注"),
    force: bool = Query(False, description="越过 web 侧的当日幂等闸门（#23），两条腿都带过去"),
):
    """手动触发产品主数据同步（G2：BFF 侧另有 /api/sync 直连入口，此为调度侧）。

    C4（CR7-10，2026-09-25）：异步化——认领后立即返回 `{accepted: true}`，
    同步由后台线程执行（15min+ 级）；进度见 `GET /sync/status`。
    已在跑时返回 `{accepted: false, note: ...}`（原 skipped 语义并入 accepted）。
    `?force=true`（#23(vi)）：当天已经同步过一轮时，默认会被 web 的当日闸门跳过
    （状态位里看得见原因）；确实要重跑才带这个参数，它透传到两条腿的 URL 上。
    """
    return sync_scheduler.run_now(trigger=trigger, force=force)


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
