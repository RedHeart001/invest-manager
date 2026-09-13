"""M5 异步任务注册表（PLAN：FastAPI BackgroundTasks + 内存任务注册表）。

- task_id → {status: running/done/failed, progress, result, error, startedAt, finishedAt}
- 去重（P5 补强）：同一 type+code 当日已有 done → 拒绝重复（每日每标的限 1 次）
- 并发去重：同一 type+code 已有 running → 拒绝
- 线程执行（uvicorn 线程池之外独立线程，不占用请求池）
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import adapter, engine

log = logging.getLogger("research.tasks")

TZ = ZoneInfo("Asia/Shanghai")
MAX_RUNNING = 2

_tasks: dict[str, dict] = {}
_lock = threading.Lock()
_daily_done: dict[str, str] = {}  # "type:code" → 最近成功日期


def _key(type_: str, code: str) -> str:
    return f"{type_}:{code}"


def _evict_expired(max_age_hours: int = 24) -> int:
    """M3/O2：淘汰完成超过 24h 的任务与当日之前的限次记录（防内存无界增长）。"""
    import time as _time

    cutoff = _time.time() - max_age_hours * 3600
    removed = 0
    with _lock:
        for tid in list(_tasks.keys()):
            t = _tasks[tid]
            if t.get("status") in ("done", "failed") and t.get("finishedAt"):
                try:
                    ts = datetime.fromisoformat(t["finishedAt"]).timestamp()
                except Exception:  # noqa: BLE001
                    continue
                if ts < cutoff:
                    _tasks.pop(tid, None)
                    removed += 1
        # _daily_done：键为 "type:code"、值为最近成功日期；
        # 限次判断只比较"== 今天"，因此非今日条目皆可清除
        today = date.today().isoformat()
        for k in list(_daily_done.keys()):
            if _daily_done.get(k) != today:
                _daily_done.pop(k, None)
                removed += 1
    if removed:
        log.info("research tasks evicted: %s", removed)
    return removed


def start_research(type_: str, code: str, name: str = "") -> dict:
    """提交研究任务。返回 {"taskId"} 或 {"rejected": 原因}。"""
    log.warning("start_research called: type_=%r code=%r name=%r", type_, code, name)
    key = _key(type_, code)
    with _lock:
        # 并发去重
        running = [
            t
            for t in _tasks.values()
            if t["status"] == "running" and t["key"] == key
        ]
        if running:
            return {"rejected": "该标的已有研究任务在执行", "taskId": running[0]["id"]}
        # 每日限 1 次（P5 成本管控）
        if _daily_done.get(key) == date.today().isoformat():
            return {
                "rejected": "该标的今日已完成一次深度研究（每日限 1 次）",
                "todayDone": True,
            }
        running_count = sum(1 for t in _tasks.values() if t["status"] == "running")
        if running_count >= MAX_RUNNING:
            return {"rejected": f"当前执行中的研究任务已达上限（{MAX_RUNNING}）"}

        _evict_expired()
        task_id = uuid.uuid4().hex[:16]
        _tasks[task_id] = {
            "id": task_id,
            "key": key,
            "type": type_,
            "code": code,
            "name": name,
            "status": "running",
            "progress": [],
            "result": None,
            "error": None,
            "startedAt": datetime.now(TZ).isoformat(timespec="seconds"),
            "finishedAt": None,
        }

    def _run() -> None:
        started = time.monotonic()

        def on_progress(steps: list) -> None:
            # 无锁快照赋值（GIL 下原子）；由引擎线程在无锁状态下调用，避免与轮询争锁
            _tasks[task_id]["progress"] = steps[-10:]

        def _emit_ingest() -> None:
            """产出落库统一模式：回调 BFF /api/research/ingest 落库（PLAN）。

            P7 修复：① 携带 `x-ingest-token`（容器化强制 INGEST_TOKEN 后，
            缺头会被 BFF 403 拒绝 → 研报静默丢失）；② 显式检查响应码——
            此前 requests 不对 4xx/5xx 抛错，落库失败会被当成成功。
            """
            import os

            import requests

            t = _tasks[task_id]
            web = os.environ.get("WEB_BASE_URL", "http://localhost:3000")
            token = os.environ.get("INGEST_TOKEN", "")
            headers = {"x-ingest-token": token} if token else {}
            payload = {
                "type": type_,
                "code": code,
                "date": date.today().isoformat(),
            }
            if t["status"] == "done" and t["result"]:
                payload["report"] = t["result"]
            else:
                payload["error"] = t.get("error") or "研究失败"
            try:
                res = requests.post(
                    f"{web}/api/research/ingest", json=payload, headers=headers, timeout=30
                )
                if res.status_code >= 300:
                    log.warning(
                        "research ingest rejected: status=%s body=%s",
                        res.status_code,
                        res.text[:200],
                    )
                    # 代码审查修复：落库被拒必须显式标注——此前任务仍为 done，
                    # 用户轮询看到"成功"但 BFF 未收到研报（静默数据丢失）
                    with _lock:
                        t = _tasks[task_id]
                        t["ingestOk"] = False
                        t["ingestNote"] = f"落库被拒：HTTP {res.status_code}"
                else:
                    with _lock:
                        _tasks[task_id]["ingestOk"] = True
            except Exception as e:  # noqa: BLE001 任务状态不受影响，但必须可观测
                log.warning("research ingest callback failed: %s", e)
                with _lock:
                    t = _tasks[task_id]
                    t["ingestOk"] = False
                    t["ingestNote"] = f"落库回调失败：{e}"

        try:
            report = engine.run_research(type_, code, name, on_progress=on_progress)
            with _lock:
                t = _tasks[task_id]
                if report.get("ok"):
                    t["status"] = "done"
                    t["result"] = report
                    _daily_done[key] = date.today().isoformat()
                else:
                    t["status"] = "failed"
                    t["error"] = report.get("error", "研究失败")
                t["finishedAt"] = datetime.now(TZ).isoformat(timespec="seconds")
            _emit_ingest()
            log.info("research task %s finished: %s", task_id, _tasks[task_id]["status"])
        except Exception as e:  # noqa: BLE001 顶层兜底（P5 补强：超时/异常标记 failed）
            log.exception("research task %s crashed", task_id)
            with _lock:
                t = _tasks[task_id]
                t["status"] = "failed"
                t["error"] = f"{type(e).__name__}: {e}"[:300]
                t["finishedAt"] = datetime.now(TZ).isoformat(timespec="seconds")
            _emit_ingest()
        _ = started

    threading.Thread(target=_run, daemon=True).start()
    return {"taskId": task_id}


def get_task(task_id: str) -> dict | None:
    with _lock:
        t = _tasks.get(task_id)
        return dict(t) if t else None


def latest_done(type_: str, code: str) -> dict | None:
    """最近一次 done 的研报（内存注册表内查询；BFF 落库后以库为准）。"""
    key = _key(type_, code)
    with _lock:
        dones = [
            t
            for t in _tasks.values()
            if t["key"] == key and t["status"] == "done" and t["result"]
        ]
        if not dones:
            return None
        return max(dones, key=lambda t: t["startedAt"])["result"]


def statuses() -> dict:
    from .adapter import collect_stats

    with _lock:
        base = {
            "running": sum(1 for t in _tasks.values() if t["status"] == "running"),
            "total": len(_tasks),
            "dailyDone": {k: v for k, v in _daily_done.items() if v == date.today().isoformat()},
        }
    base["collect"] = collect_stats()  # L3：采集线程可观测
    return base
