"""产品主数据每日同步调度（G2 / 批次 D，本轮 code review）。

背景：M2 要求「每日全量同步产品列表到 Product」，但此前 APScheduler 只调度热点，
`/api/sync` 只能手动触发 → 主数据（A股/基金/转债/加密列表）不自动更新，
搜索与分类浏览会逐渐过期。

设计（复用热点调度的基础设施与约定）：
- BackgroundScheduler，TZ=Asia/Shanghai
- 每日一次，默认 02:00（盘后/凌晨，避开交易时段与外部源限流高峰；env 可覆盖）
- 回调 web BFF `POST /api/sync`（data-service 不直连库，产出落库统一模式）
- 单飞：同进程内不并发；失败只记录不抛出（不影响调度继续）
- 启动补跑：重启后若当日未同步且已过调度时刻则补跑一次（与热点一致）

说明：同步本身由 web 侧 `lib/sync.ts` 执行（拉 data-service `/products` → 落库 →
重建 FTS → 刷新行情快照），data-service 只负责"按时触发"。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .utils.timeutil import beijing_today

log = logging.getLogger("sync.scheduler")

TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_SYNC_HOUR = 2
DEFAULT_SYNC_MINUTE = 0

# C1/CR9-4：启动补跑让位热点的轮询参数（上限 10min，与热点侧 300s 预算 + 单飞相称）
CATCHUP_POLL_INTERVAL_S = 10.0
CATCHUP_YIELD_MAX_WAIT_S = 600.0

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()
_state: dict = {"running": False, "lastRun": None, "lastDate": None, "lastResult": None, "runs": 0}


def _sync_hour_minute() -> tuple[int, int]:
    """调度时刻（env SYNC_HOUR / SYNC_MINUTE 可覆盖，非法值回落默认）。"""
    try:
        hour = int(os.environ.get("SYNC_HOUR", str(DEFAULT_SYNC_HOUR)))
    except ValueError:
        hour = DEFAULT_SYNC_HOUR
    try:
        minute = int(os.environ.get("SYNC_MINUTE", str(DEFAULT_SYNC_MINUTE)))
    except ValueError:
        minute = DEFAULT_SYNC_MINUTE
    return max(0, min(hour, 23)), max(0, min(minute, 59))


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:3000")


def _execute(trigger: str) -> dict:
    """回调 web /api/sync 并收尾（调用方须已认领 running）。"""
    import requests

    started = time.time()
    result: dict
    # C3（CR7-9，2026-09-25）：C0 实测全 5 类型 9.6~13 分钟 → 1800s（30min）保留
    # 约 2.3 倍余量，维持不变。
    try:
        r = requests.post(f"{_web_base()}/api/sync", timeout=1800)
        if r.status_code >= 300:
            result = {"error": f"HTTP {r.status_code}", "body": r.text[:200]}
            log.warning("daily sync rejected: status=%s body=%s", r.status_code, r.text[:200])
        else:
            body = r.json() or {}
            results = body.get("results") or []
            failed = [str(x.get("type")) for x in results if isinstance(x, dict) and x.get("error")]
            # CR9-28：web 侧返回的是真 ok（`results.every(r => !r.error)`），
            # 此前这里硬写 `ok: True` → 5 类里 4 类失败也被记成"同步成功"
            # （09-26 实测：lastResult.ok=true，而 stock/bond/crypto/hk 全带 error）。
            # 状态失真会让"看 /sync/status 判断今天是否要补跑"这条唯一路径失效。
            result = {"ok": bool(body.get("ok")), "tookMs": body.get("tookMs"), "results": results}
            if failed:
                result["failedTypes"] = failed
                # 失败类型不自动重试是有意取舍：整轮同步实测 9.6~13min，
                # 反复重试会持续占东财源族（CR7-7/C1 的让位逻辑同样怕这个）。
                # 因此只把缺口显式暴露出来，交给人/下次调度决定。
                result["note"] = (
                    f"部分类型失败：{', '.join(failed)}——lastDate 已置位，"
                    f"本轮不自动重试；需要时可 POST /sync/run 或等下次调度"
                )
                log.warning("daily sync partially failed: ok=false failedTypes=%s", failed)
            else:
                log.info("daily sync done: %s", result)
    except requests.exceptions.ReadTimeout as e:
        # C3-③（CR7-9，2026-09-25）：**读超时 ≠ 同步失败**——web 侧仍在后台执行
        # （ds 只是不再等结果），且 lastDate 已在下方置位不再重跑。此前把这种情况
        # 记成 error 会与"实际已成功的同步"矛盾（状态失真）。改为中性标注：
        # ok=True + note 说明 + error 字段保留原始异常供排查。
        result = {
            "ok": True,
            "note": (
                "回调读超时（同步可能仍在 web 侧完成，请查 /api/sync 结果或 "
                "Product.updatedAt）——本条非失败标记"
            ),
            "error": f"{type(e).__name__}: {e}",
        }
        log.warning("daily sync callback read timeout (sync may still complete on web side): %s", e)
    except Exception as e:  # noqa: BLE001 调度不因单次失败而中断
        result = {"error": f"{type(e).__name__}: {e}"}
        log.warning("daily sync failed: %s", e)

    with _lock:
        _state["lastRun"] = datetime.now(TZ).isoformat(timespec="seconds")
        _state["lastDate"] = beijing_today()
        _state["lastResult"] = result
        _state["runs"] += 1
        _state["running"] = False
    result["tookMsTotal"] = int((time.time() - started) * 1000)
    return result


def run_now(trigger: str = "manual") -> dict:
    """手动/补跑触发（C4/CR7-10 异步化，2026-09-25 拍板）。

    此前在请求线程内同步跑完整个同步（15min+ 级），HTTP 请求全程挂着；
    照 `hotspot/scheduler.request_run` 模板改：认领 running 后由后台线程
    执行，立即返回 `{accepted}`。线程启动失败须回滚 running（CR4 同类修复：
    否则永久卡 True，后续手动触发全部 skipped）。
    进度观测：`GET /sync/status`（running 字段 + 最近一次 results）。
    """
    with _lock:
        if _state["running"]:
            return {"accepted": False, "note": "daily sync already running"}
        _state["running"] = True
    try:
        threading.Thread(target=_execute, args=(trigger,), name="sync-manual", daemon=True).start()
    except Exception:  # noqa: BLE001 CR4：线程启动失败要回滚 running，否则永久卡 True
        with _lock:
            _state["running"] = False
        raise
    return {"accepted": True, "note": "已提交后台执行，进度见 /sync/status"}


def _catch_up_if_needed() -> None:
    """重启后若已过当日调度时刻且当日未同步 → 补跑一次。

    C1（CR7-7，2026-09-25）：与热点补跑（hotspot/scheduler._catch_up_if_needed，
    sleep 5s 先起跑）共用东财令牌桶——同步的分页批量会长时间占满 min_interval=5s，
    pipeline 的 `_EM.acquire(timeout=15)` 拿不到名额即抛 cooling down，
    HOTSPOT_PIPELINE_TIMEOUT_S=300 预算被等待吃光 → 当日热点 degraded。
    C0 实测（2026-09-25）当场实证：stock 熔断 → hk 4ms 被拒（同源族连坐）。

    处置：**同步让位热点**——热点 pipeline 在跑或尚未产出当日 digest 时等待；
    热点结束后（或当日已有产出）再跑同步。轮询上限 10 分钟：热点侧自身有
    300s 预算 + 单飞，超上限按超时放弃本轮补跑（下个调度周期 02:00 再试）。
    """
    time.sleep(8)  # 等 web 就绪（web 侧迁移/启动）
    hour, minute = _sync_hour_minute()
    now = datetime.now(TZ)
    if (now.hour, now.minute) < (hour, minute):
        log.info("sync catch-up skipped: before schedule")
        return
    if _state.get("lastDate") == beijing_today():
        log.info("sync catch-up skipped: already synced today")
        return

    # C1（CR7-7）让位热点。**CR9-4/CR9-22 修正（2026-09-26）**：
    # 原实现等的是"当日有没有 digest 产出"，那个判据在两种常态下永远不满足——
    #   ① 02:00–08:30 之间启动：热点侧 `scheduler._catch_up_decide` 未到点直接跳过，
    #      当日不会有任何产出；
    #   ② 热点跑了但落库 0 行（新闻源全挂 / ingest 被 401 拒）。
    # 两者都表现为 count==0，于是 `while … else: return` 死等满 600s 后**整轮放弃**，
    # 而调度器只在 02:00 触发 ⇒ 当天主数据同步根本不发生。
    # 现改为只让位给"真的会与之争抢东财令牌"的热点：**正在跑** 或 **尚未定案**；
    # 热点一旦定案（跑完/决定不跑/查询失败）就立即同步，不再反推它有没有产出。
    # 顺带删掉这条 web 查询——原来 HTTP 非 2xx 走"继续等"、请求异常走"直接放行"，
    # 同一件事两种方向（CR9-22）。
    from .hotspot import scheduler as hotspot_scheduler

    today = beijing_today()
    waited = 0.0
    while waited < CATCHUP_YIELD_MAX_WAIT_S:
        st = hotspot_scheduler._state
        if not st["running"]:
            if st.get("catchUpResolved") == today:
                log.info("sync catch-up: hotspot resolved for today, no need to yield")
                break
            log.info("sync catch-up: hotspot not started/resolved (%.0fs)...", waited)
        else:
            log.info("sync catch-up: hotspot pipeline running (%.0fs)...", waited)
        time.sleep(CATCHUP_POLL_INTERVAL_S)
        waited += CATCHUP_POLL_INTERVAL_S
    else:
        # 到上限：热点仍在跑 → 放弃本轮（不能压在一个卡死的 pipeline 上）；
        # 热点没在跑却迟迟没定案（其补跑线程异常/被跳过）→ 照常同步，别把当天饿掉。
        if hotspot_scheduler._state["running"]:
            log.warning(
                "sync catch-up: hotspot still running after %.0fs, giving up this round",
                CATCHUP_YIELD_MAX_WAIT_S,
            )
            return
        log.warning(
            "sync catch-up: hotspot never resolved within %.0fs, syncing anyway",
            CATCHUP_YIELD_MAX_WAIT_S,
        )

    # 无法确知"当日是否已同步"（同步状态在 web 侧，未持久化）→ 保守补跑一次：
    # 单飞 + 空载荷保护（C1）已能兜住重复同步的安全性。
    log.info("sync catch-up: running daily sync now")
    run_now(trigger="startup-catchup")


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    hour, minute = _sync_hour_minute()
    _scheduler = BackgroundScheduler(timezone=str(TZ))
    _scheduler.add_job(
        lambda: run_now("daily"),
        CronTrigger(hour=hour, minute=minute),
        id="daily-product-sync",
        replace_existing=True,
        misfire_grace_time=1800,
        coalesce=True,
    )
    _scheduler.start()
    threading.Thread(target=_catch_up_if_needed, daemon=True, name="sync-catchup").start()
    log.info("product sync scheduler started: daily %02d:%02d (Asia/Shanghai)", hour, minute)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> dict:
    jobs = []
    if _scheduler is not None:
        for j in _scheduler.get_jobs():
            jobs.append({"id": j.id, "nextRun": str(j.next_run_time)})
    return {
        "running": _state["running"],
        "runs": _state["runs"],
        "lastRun": _state["lastRun"],
        "lastDate": _state["lastDate"],
        "lastResult": _state["lastResult"],
        "jobs": jobs,
        "timezone": str(TZ),
    }
