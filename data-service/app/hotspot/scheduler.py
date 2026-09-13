"""热点定时调度（P3 / PLAN M1 + 补强）。

- APScheduler BackgroundScheduler，TZ=Asia/Shanghai
- 每日盘前 08:30 / 盘后 16:30 各一次（工作日）
- 启动补跑（P3 补强）：启动时若当日尚无 digest 且已过调度时刻 → 立即补跑一次
- 单飞（single-flight）：并发触发只执行一个
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .pipeline import run_pipeline

log = logging.getLogger("hotspot.scheduler")

TZ = ZoneInfo("Asia/Shanghai")
PRE_MARKET_HOUR, PRE_MARKET_MINUTE = 8, 30
POST_MARKET_HOUR, POST_MARKET_MINUTE = 16, 30

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()
_state: dict = {"running": False, "lastRun": None, "lastResult": None, "runs": 0}


def _execute(trigger: str) -> dict:
    """执行 pipeline 并收尾（调用方必须已认领 running 标志）。"""
    try:
        result = run_pipeline(trigger=trigger)
        _state["lastRun"] = datetime.now(TZ).isoformat(timespec="seconds")
        _state["lastResult"] = result
        _state["runs"] += 1
        log.info("hotspot pipeline done: %s", result)
        return result
    except Exception as e:  # noqa: BLE001 顶层兜底，任务不因异常终止调度
        log.exception("hotspot pipeline failed: %s", e)
        _state["lastResult"] = {"error": f"{type(e).__name__}: {e}"}
        return _state["lastResult"]
    finally:
        with _lock:
            _state["running"] = False


def _single_flight(trigger: str) -> dict | None:
    """同步单飞：认领失败返回 None（已有任务在跑）。"""
    with _lock:
        if _state["running"]:
            return None
        _state["running"] = True
    return _execute(trigger)


def run_now(trigger: str = "manual") -> dict:
    result = _single_flight(trigger)
    if result is None:
        return {"skipped": True, "note": "hotspot pipeline already running"}
    return result


def request_run(trigger: str = "manual") -> dict:
    """M4：手动触发异步化——认领后由后台线程执行，立即返回。

    认领（置 running=True）在本函数完成；线程只做执行与收尾。
    （修复记录：此前线程内再次走 _single_flight 会因 running 已置位而
    直接返回 → 任务永不执行且 running 永久卡死。）
    """
    with _lock:
        if _state["running"]:
            return {"accepted": False, "note": "hotspot pipeline already running"}
        _state["running"] = True
    threading.Thread(target=_execute, args=(trigger,), name="hotspot-manual", daemon=True).start()
    return {"accepted": True, "note": "已提交后台执行，进度见 /hotspots/status"}


def _reached_schedule_today(now: datetime) -> bool:
    return (now.hour, now.minute) >= (PRE_MARKET_HOUR, PRE_MARKET_MINUTE)


def _catch_up_if_needed() -> None:
    """P3 补强：重启后若已过调度时刻且当日无 digest → 补跑一次。"""
    time.sleep(5)  # 等服务就绪
    now = datetime.now(TZ)
    if not _reached_schedule_today(now):
        log.info("catch-up skipped: before pre-market schedule")
        return
    try:
        import requests

        import os

        web = os.environ.get("WEB_BASE_URL", "http://localhost:3000")
        r = requests.get(
            f"{web}/api/hotspots/ingest",
            params={"date": date.today().isoformat()},
            timeout=10,
        )
        count = int((r.json() or {}).get("count", 0)) if r.ok else 0
        if count == 0:
            log.info("catch-up: today's digest missing, running pipeline now")
            run_now(trigger="startup-catchup")
        else:
            log.info("catch-up skipped: today's digest exists (%s)", count)
    except Exception as e:  # noqa: BLE001 web 未启动等情况不影响服务
        log.warning("catch-up check failed: %s", e)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone=str(TZ))
    _scheduler.add_job(
        lambda: run_now("pre-market"),
        CronTrigger(day_of_week="mon-fri", hour=PRE_MARKET_HOUR, minute=PRE_MARKET_MINUTE),
        id="hotspot-pre-market",
        replace_existing=True,
    )
    _scheduler.add_job(
        lambda: run_now("post-market"),
        CronTrigger(day_of_week="mon-fri", hour=POST_MARKET_HOUR, minute=POST_MARKET_MINUTE),
        id="hotspot-post-market",
        replace_existing=True,
    )
    _scheduler.start()
    threading.Thread(target=_catch_up_if_needed, daemon=True).start()
    log.info(
        "hotspot scheduler started: pre-market %02d:%02d / post-market %02d:%02d (Asia/Shanghai)",
        PRE_MARKET_HOUR,
        PRE_MARKET_MINUTE,
        POST_MARKET_HOUR,
        POST_MARKET_MINUTE,
    )


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
        "lastResult": _state["lastResult"],
        "jobs": jobs,
        "timezone": str(TZ),
    }
