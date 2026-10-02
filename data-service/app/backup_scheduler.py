"""SQLite 每日备份调度（P7 的**调度侧缺口**，10-02 主人点头落地）。

背景（10-01 全项目审计实测）：`dev.db` 是 63 MB 单文件、**零备份**——
`scripts/backup_db.py` 有实现、也有自己的单测（`tests/test_backup_db.py`），但三个
scheduler 里没有一处引用它，`backups/` 目录是空的。单机自托管 ⇒ 这是全项目
后果最不可逆的一条：库一坏就没有第二次。

设计（与 `sync_scheduler` 同形，改动面刻意最小）：
- BackgroundScheduler，每日一次，默认 **03:30**（02:00 同步 + 刷新腿预算 2400s 的最坏
  收尾是 03:00，备份排在两者之后、不与它们争写锁）
- **没有启动补跑**：错过一轮备份不影响任何功能，下一夜自然再来；加补跑的代价是
  "为跑门禁重启一次 ds 就顺手复制 63 MB"
- 取快照走 `backup_db.backup()` 的**只读 URI + sqlite3 在线备份 API**——WAL 库直接
  `cp` 会得到撕裂快照，这是 P7 三轮补强已定死的口径，本文件不重复实现
- 份数轮换由 `BACKUP_KEEP` 控制（默认 7 份 ≈ 441 MB 磁盘）
- 失败面两条，都是本轮已验证过的仪器口径：`log.warning`（uvicorn 默认配置下 warning
  可见、`log.info` 完全不打 ⇒ 见门槛⑤）＋ `/health` 的 `dbBackup` 观测位
  （**只报最后时刻与成没成，不回显绝对路径**）
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from scripts.backup_db import backup

log = logging.getLogger("backup.scheduler")

TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_BACKUP_HOUR = 3
DEFAULT_BACKUP_MINUTE = 30
DEFAULT_KEEP = 7

# 容器内的既定挂载点（compose：prisma-data:/data、./backups:/backup）。
# dev 侧这两个路径不存在 ⇒ 回落到仓库内真实位置，见 _source_db()/_backup_dir()。
CONTAINER_DB = "/data/dev.db"
CONTAINER_BACKUP_DIR = "/backup"

# 只认这个命名模式的产物（backup_db.backup 生成 dev-<日期>-<时间>.db，
# 字典序即时间序）⇒ 轮换永不碰目录里的手工存放物或恢复前的 .pre-restore-* 文件。
SNAPSHOT_NAME = re.compile(r"^dev-\d{8}-\d{6}\.db$")

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()
_state: dict = {"running": False, "lastRun": None, "lastResult": None, "runs": 0}


def _repo_root() -> Path:
    # app/backup_scheduler.py → data-service/ → 仓库根
    return Path(__file__).resolve().parents[2]


def _source_db() -> str:
    """要备份的库：`DB_PATH` 优先，其次容器挂载点，最后 dev 的 `web/prisma/dev.db`。

    回落链必须存在：`backup()` 对不存在的源只往 stderr 打一行就返回 ""，
    ⇒ 路径配错的备份 job 会**每晚静默 no-op**，而它的唯一表现是"目录一直是空的"。
    """
    env = os.environ.get("DB_PATH", "").strip()
    if env:
        return env
    if os.path.exists(CONTAINER_DB):
        return CONTAINER_DB
    return str(_repo_root() / "web" / "prisma" / "dev.db")


def _backup_dir() -> str:
    """备份落点：`BACKUP_DIR` 优先，其次容器挂载点，最后仓库根 `backups/`（已 gitignore）。"""
    env = os.environ.get("BACKUP_DIR", "").strip()
    if env:
        return env
    if os.path.isdir(CONTAINER_BACKUP_DIR):
        return CONTAINER_BACKUP_DIR
    return str(_repo_root() / "backups")


def _keep() -> int:
    try:
        n = int(os.environ.get("BACKUP_KEEP", str(DEFAULT_KEEP)))
    except ValueError:
        return DEFAULT_KEEP
    return max(1, n)


def _hour_minute() -> tuple[int, int]:
    """调度时刻（env BACKUP_HOUR / BACKUP_MINUTE 可覆盖，非法值回落默认）。"""
    try:
        hour = int(os.environ.get("BACKUP_HOUR", str(DEFAULT_BACKUP_HOUR)))
    except ValueError:
        hour = DEFAULT_BACKUP_HOUR
    try:
        minute = int(os.environ.get("BACKUP_MINUTE", str(DEFAULT_BACKUP_MINUTE)))
    except ValueError:
        minute = DEFAULT_BACKUP_MINUTE
    return max(0, min(hour, 23)), max(0, min(minute, 59))


def rotate(outdir: str, keep: int) -> list[str]:
    """按份数轮换：保留最新 `keep` 份，删除更旧的快照文件，返回被删的文件名。"""
    if not os.path.isdir(outdir):
        return []
    names = sorted(f for f in os.listdir(outdir) if SNAPSHOT_NAME.match(f))
    removed: list[str] = []
    for f in names[: max(0, len(names) - max(1, keep))]:
        try:
            os.remove(os.path.join(outdir, f))
            removed.append(f)
        except OSError as e:  # Windows 上句柄未释放时会锁文件：删不掉≠备份失败
            log.warning("backup rotation could not prune %s: %s", f, e)
    return removed


def run_once(trigger: str = "scheduled") -> dict:
    """做一份一致性快照并按份数轮换（调用方须保证单飞）。"""
    started = time.time()
    src = _source_db()
    outdir = _backup_dir()
    keep = _keep()
    result: dict

    if not os.path.exists(src):
        result = {
            "ok": False,
            "outcome": "failed",
            "skippedReason": "source-not-found",
            "error": f"源库不存在：{src}",
        }
        log.warning("db backup skipped: source db not found (%s)", src)
    else:
        dest = backup(src, outdir)  # 失败返回 ""（损坏源/校验不过，产物已由其自行清理）
        if not dest:
            result = {
                "ok": False,
                "outcome": "failed",
                "error": "backup() 返回空——源损坏或完整性校验未过（stderr 有原话）",
            }
            log.warning("db backup failed: source=%s outdir=%s", src, outdir)
        else:
            pruned = rotate(outdir, keep)
            kept = len([f for f in os.listdir(outdir) if SNAPSHOT_NAME.match(f)])
            result = {
                "ok": True,
                "outcome": "completed",
                "trigger": trigger,
                "bytes": os.path.getsize(dest),
                "kept": kept,
                "pruned": len(pruned),
            }
            if kept > keep:
                # 删不干净（文件被占）时说出来，别让"份数早就超了"变成静默的磁盘增长
                log.warning("db backup kept %d > BACKUP_KEEP=%d", kept, keep)

    with _lock:
        _state["lastRun"] = datetime.now(TZ).isoformat(timespec="seconds")
        _state["lastResult"] = result
        _state["runs"] += 1
        _state["running"] = False
    result["tookMsTotal"] = int((time.time() - started) * 1000)
    return result


def request_run(trigger: str = "manual") -> dict:
    """手动触发（后台执行，立即返回）——与 /sync/run、/hotspots/run 同形。"""
    with _lock:
        if _state["running"]:
            return {"accepted": False, "note": "db backup already running"}
        _state["running"] = True
    try:
        threading.Thread(
            target=run_once, args=(trigger,), name="db-backup-manual", daemon=True
        ).start()
    except Exception:  # noqa: BLE001 线程起不来要回滚 running，否则永久卡 True
        with _lock:
            _state["running"] = False
        raise
    return {"accepted": True, "note": "已提交后台执行，结果见 /health 的 dbBackup"}


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    hour, minute = _hour_minute()
    _scheduler = BackgroundScheduler(timezone=str(TZ))
    _scheduler.add_job(
        lambda: run_once("daily"),
        CronTrigger(hour=hour, minute=minute),
        id="daily-db-backup",
        replace_existing=True,
        misfire_grace_time=1800,
        coalesce=True,
    )
    _scheduler.start()
    log.info("db backup scheduler started: daily %02d:%02d (Asia/Shanghai)", hour, minute)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def health() -> dict:
    """给 /health 的观测位：最后一次备份的时刻/成败/累计次数，**不回显路径**。"""
    last = _state["lastResult"] or {}
    return {
        "lastRun": _state["lastRun"],
        "ok": last.get("ok"),
        "runs": _state["runs"],
    }
