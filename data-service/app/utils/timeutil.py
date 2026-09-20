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

from datetime import date, datetime
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
    from datetime import timedelta

    return (beijing_now().date() + timedelta(days=days)).isoformat()
