"""热点定时调度（P3 / PLAN M1 + 补强）。

- APScheduler BackgroundScheduler，TZ=Asia/Shanghai
- 每日盘前 08:30 / 盘后 16:30 各一次（工作日）
- 启动补跑（P3 补强）：启动时若当日尚无 digest 且已过调度时刻 → 立即补跑一次
- 单飞（single-flight）：并发触发只执行一个
- 每轮收尾把 `lastRun`/`lastResult` 覆写落盘（#34／CR9-62）：`/hotspots/status` 内存空时回落到它
- 起跑前把「今天这台机器起过一轮」落盘（CR9-95＝#68 同族的另一半，10-13 主人的字＝「执行A桶B桶」）：
  启动补跑此前只问「今天有没有 digest」（结果态），于是**跑过但 0 产出／失败**的那一轮
  在每次重启后都会被重买一遍（一整轮 pipeline＝akshare＋东财＋Tavily）。判据换成 date-keyed
  的「试过」，与同步侧 `runtime/sync-state.json` 同形；逃出口＝`POST /hotspots/run`（手动不看这枚）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..utils.timeutil import beijing_today
from .pipeline import run_pipeline

log = logging.getLogger("hotspot.scheduler")

TZ = ZoneInfo("Asia/Shanghai")
PRE_MARKET_HOUR, PRE_MARKET_MINUTE = 8, 30
POST_MARKET_HOUR, POST_MARKET_MINUTE = 16, 30

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()
# catchUpResolved（CR9-4，2026-09-26）：当日补跑是否已"定案"（跑了 / 决定不跑 / 查询失败）。
# 同步补跑要靠它判断"还要不要让位"——若只看"当日有没有 digest 产出"，
# 则 02:00–08:30 启动（热点此刻不跑）与热点跑了但 0 产出这两种情况下，
# 同步会死等到 600s 上限后**整日不跑**。
_state: dict = {
    "running": False,
    "lastRun": None,
    "lastResult": None,
    "runs": 0,
    "catchUpResolved": None,
    # CR9-95：date-keyed 的「试过」三件（与 `sync-state.json` 同名同义）。
    # 它们与 `catchUpResolved` 是两码事——后者不带日期，所以「不许从盘上捞」那条理由只对
    # 它成立；这三件自带日期，读的时候拿它跟今天比，昨天的值自然不生效。
    "lastAttemptDate": None,
    "lastAttemptTrigger": None,
    "lastAttemptOutcome": None,
    "lastAttemptAt": None,
    # 写不进去只 warning（CR9-45），但要在 `/hotspots/status` 上留一枚机器可读位：
    # 判据落不了盘时，「重启不重买」这条保护就是失效的，而它失效的样子是**什么都不发生**。
    "stateWriteFailed": False,
    "catchUpSkipReason": None,
}

STATE_NAME = "hotspot-state.json"


def _state_path() -> str:
    """状态位文件的落点：默认 `data-service/runtime/hotspot-state.json`（该目录已在 `.gitignore`）。

    `HOTSPOT_STATE_FILE` 可整条覆盖——离线单测靠它指向临时目录，不碰仓库里那份真的。
    """
    env = os.environ.get("HOTSPOT_STATE_FILE", "")
    if env:
        return env
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "runtime", STATE_NAME)


def _write_state() -> bool:
    """把 `lastRun`/`lastResult` 与那三件「试过」覆写落盘（先 `.tmp` 再 `os.replace`，读者看不到半截）。

    CR9-95 起它一轮被调两次：起跑前（`_mark_attempt`，此时 outcome=`running`）与收尾
    （`_execute` 的 `finally`，写真结局）。两次都是整份覆写 ⇒ 不需要"读回旧值再合并"。

    为什么 #34 要有这个文件：`lastResult` 此前**只有内存态**，重启即失，于是"08:30 那一轮的
    合并计数"在最需要它的两个时刻都读不到——① 事后任何一次重启之后，② 手动/定时跑完但没人
    守着屏幕的那一刻（一次性读数脚本恰好在后者）。同族先例＝`backup_scheduler` 的 `state.json`
    （#29／CR9-53），口径照抄：**覆写、不回显绝对路径、写不进去只 `log.warning`**
    （CR9-45：观测不得拖垮主功能——连 `json.dump` 遇到将来某个不可序列化的字段都不许把
    这一轮 pipeline 的返回值带崩）。
    """
    path = _state_path()
    payload = {
        "lastRun": _state["lastRun"],
        "lastResult": _state["lastResult"],
        # CR9-95：三件「试过」与 lastRun/lastResult 同住一个文件（不新造第二份状态位）。
        "lastAttemptDate": _state["lastAttemptDate"],
        "lastAttemptTrigger": _state["lastAttemptTrigger"],
        "lastAttemptOutcome": _state["lastAttemptOutcome"],
        "lastAttemptAt": _state["lastAttemptAt"],
    }
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
        _state["stateWriteFailed"] = False
        return True
    except (OSError, TypeError, ValueError) as e:
        log.warning("hotspot state could not be written: %s", e)
        _state["stateWriteFailed"] = True
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def read_state() -> dict | None:
    """读回磁盘那份状态；缺失／损坏／非对象一律当"没有"，**不抛**（观测位不能让 /hotspots/status 500）。"""
    try:
        with open(_state_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _attempt_outcome(result: object) -> str:
    """把一轮的结局压成一个可比较的字面（`run_pipeline` 的返回里没有 `ok`/`outcome` 键）。

    三档＝`failed`（顶层异常，`lastResult` 只剩 `error`）／`zero-items`（跑通了但一条热点都没
    产出＝新闻源全挂或全被去重掉）／`completed`。为什么单分 `zero-items`：它就是"今天试过、
    什么都没落下"那一形——重启后最容易被重买，也最该被一条 curl 读出来。
    """
    if not isinstance(result, dict):
        return "unknown"
    if result.get("error"):
        return "failed"
    items = result.get("items")
    if isinstance(items, list) and not items:
        return "zero-items"
    return "completed"


def _mark_attempt(trigger: str) -> bool:
    """起跑前落「今天这台机器起过一轮」。写点＝**钱已被承诺的那一刻**。

    `run_pipeline` 一进去就开始买上游（新闻三源＋板块映射），所以写在收尾就会留下同步侧
    10-13 18:57 那一形的漏洞：被 kill 的那轮钱已花、盘上无痕迹。
    日期取**起跑时**那一份且此后不被覆写（收尾只改 `lastAttemptOutcome`）⇒ 跨午夜的轮
    不会把昨天的起跑记成今天。
    """
    _state["lastAttemptDate"] = beijing_today()
    _state["lastAttemptTrigger"] = trigger
    _state["lastAttemptOutcome"] = "running"
    _state["lastAttemptAt"] = datetime.now(TZ).isoformat(timespec="seconds")
    return _write_state()


def _set_skip(reason: str | None) -> None:
    """#21 同族：把「这一轮补跑为什么没跑」写进状态位（`log.info` 在 uvicorn 默认配置下不打）。"""
    with _lock:
        _state["catchUpSkipReason"] = reason


def _execute(trigger: str) -> dict:
    """执行 pipeline 并收尾（调用方必须已认领 running 标志）。"""
    # CR9-95：先落「今天起过一轮」再买上游。放在 `_execute` 而不是两个入口
    # （`run_now` 同步／`request_run` 异步）⇒ 只有一处写点，且线程启动失败那一支
    # 根本走不到这里——零成本的失败不该把当天吃掉（与同步侧的回滚同义，形状更简单）。
    _mark_attempt(trigger)
    try:
        result = run_pipeline(trigger=trigger)
        _state["lastRun"] = datetime.now(TZ).isoformat(timespec="seconds")
        _state["lastResult"] = result
        _state["runs"] += 1
        _state["lastAttemptOutcome"] = _attempt_outcome(result)
        log.info("hotspot pipeline done: %s", result)
        return result
    except Exception as e:  # noqa: BLE001 顶层兜底，任务不因异常终止调度
        log.exception("hotspot pipeline failed: %s", e)
        _state["lastResult"] = {"error": f"{type(e).__name__}: {e}"}
        _state["lastAttemptOutcome"] = "failed"
        return _state["lastResult"]
    finally:
        with _lock:
            _state["running"] = False
        _write_state()  # 成功与失败两条出口都要落盘：失败轮同样是要读的那一份


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
    try:
        threading.Thread(target=_execute, args=(trigger,), name="hotspot-manual", daemon=True).start()
    except Exception:  # noqa: BLE001 CR4：线程启动失败要回滚 running，否则永久卡 True
        with _lock:
            _state["running"] = False
        raise
    return {"accepted": True, "note": "已提交后台执行，进度见 /hotspots/status"}


def _reached_schedule_today(now: datetime) -> bool:
    return (now.hour, now.minute) >= (PRE_MARKET_HOUR, PRE_MARKET_MINUTE)


def _catch_up_if_needed() -> None:
    """P3 补强：重启后若已过调度时刻且当日无 digest → 补跑一次。

    CR9-4（2026-09-26）：无论走哪条出口（未到点跳过 / 已有产出跳过 / 触发补跑 /
    查询失败），都要置 `catchUpResolved=今天`。同步侧要靠它判断"还要不要让位"——
    只看"当日有没有 digest"是不行的：02:00–08:30 启动（热点此刻根本不会跑）与
    热点跑了但 0 产出这两种情况，在 digest 计数上长得一模一样（都是 0），
    于是同步死等到 600s 上限后放弃，**当天主数据同步整日不发生**。
    """
    time.sleep(5)  # 等服务就绪
    try:
        _catch_up_decide()
    finally:
        _state["catchUpResolved"] = beijing_today()


def _catch_up_decide() -> None:
    now = datetime.now(TZ)
    if not _reached_schedule_today(now):
        _set_skip(
            f"before pre-market schedule（now={now:%H:%M} < "
            f"{PRE_MARKET_HOUR:02d}:{PRE_MARKET_MINUTE:02d}）"
        )
        log.info("catch-up skipped: before pre-market schedule")
        return
    # CR9-95：先问盘上那枚 date-keyed 的「试过」，再问 web「今天有没有 digest」。
    # 两问不重复——digest 计数对"跑过但 0 产出／失败"那一形永远答 0，于是每次重启都重买
    # 一整轮 pipeline；「试过」正好补上它。昨天的日期不算数（自带日期 ⇒ 隔夜机器照常补跑）。
    disk = read_state() or {}
    attempt_date = disk.get("lastAttemptDate")
    if attempt_date == beijing_today():
        _set_skip(
            f"already attempted today（磁盘态 lastAttemptDate={attempt_date}"
            f"，trigger={disk.get('lastAttemptTrigger')}"
            f"，outcome={disk.get('lastAttemptOutcome')}）"
            "——今天这台机器已经起过一轮热点，不再重买 pipeline；确要重跑走 POST /hotspots/run"
        )
        log.info("catch-up skipped: already attempted today (%s)", attempt_date)
        return
    try:
        import requests

        import os

        web = os.environ.get("WEB_BASE_URL", "http://localhost:3000")
        r = requests.get(
            f"{web}/api/hotspots/ingest",
            # CR-06：补跑日期与 pipeline 落库口径一致（均北京时间）
            params={"date": beijing_today()},
            timeout=10,
        )
        count = int((r.json() or {}).get("count", 0)) if r.ok else 0
        if count == 0:
            _set_skip(None)  # 真触发补跑 ⇒ 清掉跳过原因（否则状态位变成常驻噪声，#21 🔁 同口径）
            log.info("catch-up: today's digest missing, running pipeline now")
            run_now(trigger="startup-catchup")
        else:
            _set_skip(f"today's digest exists (count={count})")
            log.info("catch-up skipped: today's digest exists (%s)", count)
    except Exception as e:  # noqa: BLE001 web 未启动等情况不影响服务
        # 保持原行为＝不补跑（web 都没起来时，买一整轮上游也无处落库）。这一支同样要置
        # `catchUpResolved`（由 `_catch_up_if_needed` 的 finally 负责）⇒ 同步侧不会死等，
        # 这正是 CR9-4 立「查询失败也算定案」那一档的理由。
        _set_skip(f"catch-up check failed: {type(e).__name__}: {e}")
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
        # CR4（2026-09-15 review）：宿主机睡眠时默认 misfire_grace_time=1s 会让
        # 唤醒后的当日任务被判 misfire 直接跳过（且启动补跑不覆盖"睡眠唤醒"）。
        # 30 分钟宽限 + coalesce 合并积压；单飞锁已能兜住补跑与定时的并发。
        misfire_grace_time=1800,
        coalesce=True,
    )
    _scheduler.add_job(
        lambda: run_now("post-market"),
        CronTrigger(day_of_week="mon-fri", hour=POST_MARKET_HOUR, minute=POST_MARKET_MINUTE),
        id="hotspot-post-market",
        replace_existing=True,
        misfire_grace_time=1800,
        coalesce=True,
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
    # CR9-95：盘上那一份读一次，两处用（`lastAttempt` 与下面的 lastResult 回落）。
    disk = read_state()
    attempt_keys = ("lastAttemptDate", "lastAttemptTrigger", "lastAttemptOutcome", "lastAttemptAt")
    attempt = {k: disk.get(k) for k in attempt_keys} if isinstance(disk, dict) else None
    out = {
        "running": _state["running"],
        "runs": _state["runs"],
        "lastRun": _state["lastRun"],
        "lastResult": _state["lastResult"],
        "jobs": jobs,
        "timezone": str(TZ),
        "fromDisk": False,
        # 「今天这台机器起过一轮」＝只认盘上那份（内存态重启即失，正是要治的那一半）。
        # `lastAttemptFromDisk` 与同步侧同义：盘上有、而本进程一轮没跑 ⇒ 那是上个进程留下的。
        "lastAttempt": attempt if attempt and attempt.get("lastAttemptDate") else None,
        "lastAttemptFromDisk": bool(attempt and attempt.get("lastAttemptDate")) and _state["runs"] == 0,
        "stateWriteFailed": bool(_state.get("stateWriteFailed")),
        "catchUpSkipReason": _state.get("catchUpSkipReason"),
    }
    # #34（CR9-62）：内存为空 ⇒ 回落到磁盘那份并标 `fromDisk=True`，一条 curl 就能把
    # "这个进程跑过"与"上个进程跑过、我重启了"分开（同 #29／CR9-53 的备份状态位）。
    # **刻意只回落 lastRun/lastResult 两件**：`runs` 保持"本进程跑了几轮"的原义（p3 的轮询
    # 条件靠它），`catchUpResolved` 更不许从盘上捞——同步侧拿它判"当日要不要让位"，
    # 昨天的定案值放到今天就是错的。
    # ⚠️ CR9-95 给这条理由划个界：它成立的前提是**那个值不带日期**。`lastAttempt*` 自带
    # `lastAttemptDate`，读的时候就跟今天比（昨天的自然不生效）⇒ 从盘上捞是安全的，
    # 而且必须捞——否则重启后判据又只剩内存态，正是要治的那一半。
    if out["lastResult"] is None:
        last = (disk or {}).get("lastResult")
        if isinstance(last, dict):
            out["lastResult"] = last
            out["lastRun"] = disk.get("lastRun")
            out["fromDisk"] = True
    return out
