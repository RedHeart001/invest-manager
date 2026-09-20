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
    try:
        r = requests.post(f"{_web_base()}/api/sync", timeout=1800)
        if r.status_code >= 300:
            result = {"error": f"HTTP {r.status_code}", "body": r.text[:200]}
            log.warning("daily sync rejected: status=%s body=%s", r.status_code, r.text[:200])
        else:
            body = r.json() or {}
            result = {"ok": True, "tookMs": body.get("tookMs"), "results": body.get("results")}
            log.info("daily sync done: %s", result)
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
    """手动/补跑触发（同步执行；已有任务在跑则跳过）。"""
    with _lock:
        if _state["running"]:
            return {"skipped": True, "note": "daily sync already running"}
        _state["running"] = True
    return _execute(trigger)


def _catch_up_if_needed() -> None:
    """重启后若已过当日调度时刻且当日未同步 → 补跑一次。"""
    time.sleep(8)  # 等 web 就绪（web 侧迁移/启动）
    hour, minute = _sync_hour_minute()
    now = datetime.now(TZ)
    if (now.hour, now.minute) < (hour, minute):
        log.info("sync catch-up skipped: before schedule")
        return
    if _state.get("lastDate") == beijing_today():
        log.info("sync catch-up skipped: already synced today")
        return
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
