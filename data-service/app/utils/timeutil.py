"""北京时间工具（CR-06，本轮 code review）。

背景：web 侧统一用北京时间（`web/lib/time.ts` 的 `beijingToday()`）建立/查询
`(type, code, date)` 与 digest 日期；而 data-service 此前用本地时区的
`date.today()`。两者在 TZ≠Asia/Shanghai 的部署下（本地开发 / 异机 / UTC 容器）
会错位——北京时间 00:00–08:00 区间内 data-service 会产出"昨天"的日期，导致：
  - 研报回调 upsert 命中前一天 → web 记录的 running 行永久 running；
  - `_daily_done` 每日限额错位（当天可能放行两次或误拒）；
  - 热点 digest 落到错误日期。

本模块把"业务日期"统一为北京时间，供 pipeline / scheduler / research 复用。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def beijing_now() -> datetime:
    """当前北京时间（带 tzinfo）。"""
    return datetime.now(TZ)


def beijing_today() -> str:
    """今天（北京时间，YYYY-MM-DD）。"""
    return beijing_now().date().isoformat()


def beijing_today_date() -> date:
    """今天（北京时间，date 对象）。"""
    return beijing_now().date()


def beijing_shift_days(days: int) -> str:
    """北京时间今天往前（负）/往后（正）偏移 N 天，YYYY-MM-DD。"""
    return (beijing_now().date() + timedelta(days=days)).isoformat()


_LOOKBACK_DAYS = 14  # 最长假期／周末链的兜底跨度；超出就当仪器读不出


def _due_on(day: date, weekdays_only: bool) -> bool:
    return not (weekdays_only and day.weekday() >= 5)


def _prev_due_day(day: date, weekdays_only: bool) -> date:
    probe = day - timedelta(days=1)
    while not _due_on(probe, weekdays_only):
        probe -= timedelta(days=1)
    return probe


def leg_staleness(
    attempt_date: object,
    *,
    hour: int,
    minute: int,
    weekdays_only: bool = False,
    instrument_ok: bool = True,
    now: datetime | None = None,
) -> dict:
    """这条腿「本来该在什么时候之前跑过」＋「最后一次真跑到今天是几天前」——读时算，不靠进程活着。

    丢腿的原因是关机而不是睡眠，而进程不在就没资格报警 ⇒ 唯一的取证时机是**下一次开机后来读**，
    所以判据必须长在只读的 `status()` 里，而不是长在一个可能压根没起来的作业上。

    verdict 词表刻意与备份腿同字面（`backup_scheduler` 的 `fresh`／`stale-Nh`／`no-state`／
    `unreadable-state`）：同一件事在三条腿上不该有四个名字。
    """
    now = now or datetime.now(TZ)
    today = now.date()

    obligation: date | None = None
    expected_by: str | None = None
    probe = today
    for _ in range(_LOOKBACK_DAYS):
        if _due_on(probe, weekdays_only):
            moment = datetime.combine(probe, time(hour, minute), tzinfo=TZ)
            if now >= moment:
                obligation, expected_by = probe, moment.isoformat(timespec="minutes")
                break
        probe -= timedelta(days=1)

    age_days: int | None = None
    attempt: date | None = None
    if isinstance(attempt_date, date):
        attempt = attempt_date
    elif isinstance(attempt_date, str) and attempt_date:
        try:
            attempt = date.fromisoformat(attempt_date)
        except ValueError:
            attempt = None
    verdict: str
    if attempt is None:
        verdict = "unreadable" if attempt_date else "never"
    else:
        age_days = (today - attempt).days
        if obligation is None or attempt >= obligation:
            verdict = "not-yet-due" if obligation is None else "fresh"
        elif obligation == today and attempt == _prev_due_day(obligation, weekdays_only):
            verdict = "missed-today"
        else:
            verdict = "stale-%dd" % age_days
    if not instrument_ok:
        # 写不进／读不出 ⇒ 盘上那份不能用来判新鲜度；不许用省略冒充「没问题」。
        verdict = "instrument-untrusted"
    return {
        "verdict": verdict,
        "ageDays": age_days,
        "expectedBy": expected_by,
        "lastAttemptDate": attempt.isoformat() if attempt else None,
    }
