"""SQLite 每日备份调度（P7 的**调度侧缺口**，10-02 主人点头落地）。

背景（10-01 全项目审计实测）：`dev.db` 是 63 MB 单文件、**零备份**——
`scripts/backup_db.py` 有实现、也有自己的单测（`tests/test_backup_db.py`），但三个
scheduler 里没有一处引用它，`backups/` 目录是空的。单机自托管 ⇒ 这是全项目
后果最不可逆的一条：库一坏就没有第二次。

设计（与 `sync_scheduler` 同形，改动面刻意最小）：
- BackgroundScheduler，每日一次，默认 **03:30**（02:00 同步 + 刷新腿预算 2400s 的最坏
  收尾是 03:00，备份排在两者之后、不与它们争写锁）
- **起服务时查一次、落后就补一份（#37／CR9-65，主人 10-05 的字＝"备份起服务的时候就检查，
  落后就补一份"）**——原先这里写的是"**没有启动补跑**：错过一轮备份不影响任何功能"，
  而实测把这句话的代价改成了别的形状：10-03 与 10-05 两夜机器睡着 ⇒ 03:30 那枚 cron
  根本没触发，`backups/` 停在 10-04 03:30，而那期间库里做过整表删旧插新。⇒ 门限取
  **26 小时**（错过一次每日备份＋2 小时容差）：同一天内为跑门禁重启 N 次仍然不会复制
  63 MB，这正是原注释担心的那件事，它由门限挡着、不由"干脆不补"挡着
- **30 天以上的留存直接删**（他的字＝"落后一个月的冗余缓存就直接删除"，且**不留底**）；
  按**文件名里的时刻**判而不是 mtime，且**只在新备份成功之后**才删——顺序反过来时一次失败
  就能把备份清零，那比多占几十 MB 严重得多
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
from datetime import datetime, timedelta
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
# #37／CR9-65（主人 10-05 的字）：**补**与**删**是两个门限，不是一个——
# 落后 26 小时（错过一次每日 03:30 ＋ 2 小时容差）就起服务补一份；
# 留存超过 30 天的一律删掉、不留底（正常节奏下 BACKUP_KEEP=3 会让文件活不过 3 天，
# 这一档只在"机器长期不开、留下的全是一个月前的"时命中）。
DEFAULT_STALE_HOURS = 26
DEFAULT_MAX_AGE_DAYS = 30

# 容器内的既定挂载点（compose：prisma-data:/data、./backups:/backup）。
# dev 侧这两个路径不存在 ⇒ 回落到仓库内真实位置，见 _source_db()/_backup_dir()。
CONTAINER_DB = "/data/dev.db"
CONTAINER_BACKUP_DIR = "/backup"

# 只认这个命名模式的产物（backup_db.backup 生成 dev-<日期>-<时间>.db，
# 字典序即时间序）⇒ 轮换永不碰目录里的手工存放物或恢复前的 .pre-restore-* 文件。
SNAPSHOT_NAME = re.compile(r"^dev-(\d{8})-(\d{6})\.db$")

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


def _stale_hours() -> int:
    """#37：起服务补跑的门限（env `BACKUP_STALE_HOURS`，非法值回落默认 26 小时）。"""
    try:
        n = int(os.environ.get("BACKUP_STALE_HOURS", str(DEFAULT_STALE_HOURS)))
    except ValueError:
        return DEFAULT_STALE_HOURS
    return max(1, n)


def _max_age_days() -> int:
    """#37：留存删除的门限（env `BACKUP_MAX_AGE_DAYS`，非法值回落默认 30 天）。"""
    try:
        n = int(os.environ.get("BACKUP_MAX_AGE_DAYS", str(DEFAULT_MAX_AGE_DAYS)))
    except ValueError:
        return DEFAULT_MAX_AGE_DAYS
    return max(1, n)


def _name_time(name: str) -> datetime | None:
    """从快照文件名里取出产出时刻（带本时区）；名字不合规返回 None。"""
    m = SNAPSHOT_NAME.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=TZ)
    except ValueError:
        return None


def purge_old(outdir: str, max_age_days: int) -> list[str]:
    """把留存超过 `max_age_days` 的快照连 `-wal`/`-shm` 一起删掉，返回被删的文件名。

    #37（主人 10-05 的字＝"落后一个月的冗余缓存就直接删除"，且明确**不留底**）。
    两条口径写死在这里：
    - **按文件名里的时刻判、不按 mtime**：sidecar 与任何一次手工复制都会改 mtime，
      而文件名是产出那一刻定死的（字典序即时间序）。
    - **只有新备份成功后才调用**（见 `run_once` 的成功分支）：顺序反过来时，一次
      "源损坏／校验不过"的失败就能把备份清零，那比多占几十 MB 严重得多。
    `state.json` 不匹配 `SNAPSHOT_NAME` ⇒ 永不被删（#29 那条"轮换不碰状态位"继续成立）。
    """
    if not os.path.isdir(outdir):
        return []
    cutoff = datetime.now(TZ) - timedelta(days=max_age_days)
    removed: list[str] = []
    for f in sorted(os.listdir(outdir)):
        ts = _name_time(f)
        if ts is None or ts >= cutoff:
            continue
        try:
            os.remove(os.path.join(outdir, f))
            removed.append(f)
        except OSError as e:  # Windows 句柄未释放时删不掉：删不掉≠备份失败
            log.warning("backup purge could not remove %s: %s", f, e)
            continue
        for suffix in ("-wal", "-shm"):
            side = os.path.join(outdir, f + suffix)
            if os.path.exists(side):
                try:
                    os.remove(side)
                    removed.append(f + suffix)
                except OSError as e:
                    log.warning("backup purge could not remove %s: %s", side, e)
    return removed


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
            # #37：留存删除排在这里，不是巧合——**这一行只在 `backup()` 成功之后才会走到**，
            # 于是"新的一份已经在盘上"是删除的前置条件（失败分支根本不进这个 else）。
            aged = purge_old(outdir, _max_age_days())
            kept = len([f for f in os.listdir(outdir) if SNAPSHOT_NAME.match(f)])
            result = {
                "ok": True,
                "outcome": "completed",
                "trigger": trigger,
                "bytes": os.path.getsize(dest),
                "kept": kept,
                "pruned": len(pruned),
                "aged": len(aged),
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


def startup_catch_up() -> dict:
    """起服务时查一次：错过每日备份就当场补一份（#37／CR9-65，主人 10-05 的字）。

    返回值只用于日志与断言，**不进 `/health`**——那一位已经有 `lastRun`/`ok`/`outcome`
    在说话，再加一个键只会让"这份是补的"和"这份是准的"混在一起；要说清是谁做的，
    `trigger="startup-catchup"` 已经落在结果载荷与 `state.json` 里。

    判"落后"的三种情况：`state.json` 不存在（这台机从没备过）／载荷读不出来或时刻字段
    不合法／落后超过 `BACKUP_STALE_HOURS`（默认 26 小时＝错过一次 03:30 ＋ 2 小时容差）。
    **后两种一律按落后处理**：漏一次备份的代价是不可逆的，多复制一份 63 MB 不是。
    同日里为跑门禁重启 N 次都不会触发——门限挡的正是本文件头原来那句
    "加补跑的代价是为重启就顺手复制 63 MB"（10-02 的保留决定，已被实测改口）。
    """
    try:
        outdir = _backup_dir()
        state = read_state(outdir)
        stale_h = _stale_hours()
        last_raw = (state or {}).get("lastRun")
        last_ts: datetime | None = None
        if last_raw:
            try:
                parsed = datetime.fromisoformat(str(last_raw))
                last_ts = parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)
            except ValueError:
                last_ts = None
        if last_ts is None:
            reason = "no-state" if state is None else "unreadable-state"
            age_h = None
        else:
            age_h = int((datetime.now(TZ) - last_ts).total_seconds() // 3600)
            reason = "fresh" if age_h < stale_h else "stale-%dh" % age_h
        if reason == "fresh":
            log.info(
                "backup startup check: last backup %dh ago (< %dh) ⇒ 不补跑", age_h, stale_h
            )
            return {"triggered": False, "reason": reason, "ageHours": age_h}
        got = request_run("startup-catchup")
        # 这条用 warning：uvicorn 默认配置下 log.info 完全不打（门槛⑤ 记过的老账），
        # 而"起服务时补了一份"必须第二天还能从日志里读出来。
        log.warning(
            "backup startup check: %s ⇒ 补一份（accepted=%s）", reason, got.get("accepted")
        )
        return {
            "triggered": True,
            "reason": reason,
            "ageHours": age_h,
            "accepted": got.get("accepted"),
        }
    except Exception as e:  # noqa: BLE001 补跑不许拖垮起服务（CR9-45 同族）
        log.warning("backup startup check failed: %s", e)
        return {"triggered": False, "reason": "error"}


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
    # #37：cron 只覆盖"那一刻机器醒着且 ds 在跑"——10-03 与 10-05 两夜它两次都没触发，
    # 而盘上不会有任何一句话说"今天没有备份"。⇒ 起服务时补一次检查，把"错过"变成"补上"。
    # 放在 start 之后：job 先注册上，补跑这一份的 `nextRun` 才是可读的。
    startup_catch_up()


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
