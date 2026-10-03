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
- **#29（10-03 断电撞出来的）**：上面那条观测位是**内存态**，进程一死就变 null，于是
  "昨晚到底备过没有"在断电重启后读不出来。⇒ 每轮结果**同时落 `backups/state.json`**
  （失败轮同样落），`health()` 在内存为空时回落到它并标 `fromDisk`。放在 `backups/` 里
  是因为 `rotate()` 只按 `SNAPSHOT_NAME` 删文件 ⇒ 这份状态永远不会被轮换碰掉。
"""

from __future__ import annotations

import json
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

# #29：备份结果的**磁盘状态位**。放在 backups/ 里而不在库里，是因为 `rotate()` 只按
# SNAPSHOT_NAME 删文件 ⇒ 这个文件永远不会被轮换碰掉，而它要回答的恰是"昨晚到底备过没有"。
STATE_NAME = "state.json"

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


def _state_file(outdir: str) -> str:
    return os.path.join(outdir, STATE_NAME)


def _write_state(payload: dict, outdir: str) -> bool:
    """把本轮结果落成磁盘状态（先写 `.tmp` 再 `os.replace`，读者不会看到半截）。

    **观测不得拖垮主功能**：写不进去只 `log.warning`，备份本身与返回值都不受影响。
    载荷里刻意不含绝对路径，也不含 `error` 原文（那句会带源库路径）——`/health` 的
    "不回显路径"这条纪律不能因为落盘而被绕过。
    """
    path = _state_file(outdir)
    tmp = path + ".tmp"
    try:
        os.makedirs(outdir, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
        return True
    except OSError as e:
        log.warning("backup state could not be written to %s: %s", path, e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def read_state(outdir: str | None = None) -> dict | None:
    """读回磁盘状态；文件缺失／损坏一律当"没有"，**不抛**（观测位不能让 /health 500）。"""
    path = _state_file(outdir if outdir is not None else _backup_dir())
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def rotate(outdir: str, keep: int) -> list[str]:
    """按份数轮换：保留最新 `keep` 份，删除更旧的快照文件，返回被删的文件名。

    删主文件时**一并删它的 `-wal`/`-shm`**：备份产物本身是 WAL 库（在线备份 API 会连
    源库的 journal mode 一起复制过来），只删 `.db` 会在目录里留下半套 sidecar，
    而 `BACKUP_KEEP` 承诺的是"份数"，不是"主文件数"。
    """
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
            continue
        for suffix in ("-wal", "-shm"):
            side = os.path.join(outdir, f + suffix)
            if os.path.exists(side):
                try:
                    os.remove(side)
                    removed.append(f + suffix)
                except OSError as e:
                    log.warning("backup rotation could not prune %s: %s", side, e)
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
        last_run = datetime.now(TZ).isoformat(timespec="seconds")
        _state["lastRun"] = last_run
        _state["lastResult"] = result
        _state["runs"] += 1
        _state["running"] = False
        runs = _state["runs"]
    result["tookMsTotal"] = int((time.time() - started) * 1000)
    # #29（10-03 断电实测）：内存那份随进程一起死，"昨晚到底备过没有"就不能只指望它
    # ⇒ 同一份结果落盘；**失败轮同样要落**，否则"没备"仍然不可见。
    result["stateWritten"] = _write_state(
        {
            "lastRun": last_run,
            "ok": result.get("ok"),
            "outcome": result.get("outcome"),
            "runs": runs,
            "trigger": trigger,
            "skippedReason": result.get("skippedReason"),
            "kept": result.get("kept"),
        },
        outdir,
    )
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
    """给 /health 的观测位：最后一次备份的时刻/成败/次数 ＋ **下一档 cron 时刻**。

    为什么必须带 `nextRun`：只看 lastRun/ok/runs 时，"今天还没到 03:30"与"job 根本没注册上"
    在 curl 里长得一模一样（都是 null/0），而后者正是本位要防的那种静默失败。
    **不回显绝对路径。**

    #29 增加的两件事：**内存为空时回落到磁盘那份状态并标 `fromDisk=True`**——断电／重启后
    一条 curl 仍能把"昨晚备过（旧进程写的）"与"这台机从没备过"分开读。代价要说清：
    此时 `runs` 是**那份文件累计的次数**，不是本进程的次数。
    """
    last = _state["lastResult"] or {}
    next_run = None
    if _scheduler is not None:
        jobs = _scheduler.get_jobs()
        if jobs:
            next_run = str(jobs[0].next_run_time)
    out = {
        "lastRun": _state["lastRun"],
        "ok": last.get("ok"),
        "outcome": last.get("outcome"),
        "runs": _state["runs"],
        "nextRun": next_run,
        "fromDisk": False,
    }
    if out["lastRun"] is None:
        disk = read_state()
        if disk:
            out.update(
                {
                    "lastRun": disk.get("lastRun"),
                    "ok": disk.get("ok"),
                    "outcome": disk.get("outcome"),
                    "runs": disk.get("runs"),
                    "fromDisk": True,
                }
            )
    return out
