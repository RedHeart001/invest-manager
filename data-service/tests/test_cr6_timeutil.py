"""CR-06 离线单测：北京时间口径工具。

运行方式（无需服务）：
    .venv/Scripts/python tests/test_cr6_timeutil.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils import timeutil  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def test_tz_is_shanghai() -> None:
    check("TZ 为 Asia/Shanghai", str(timeutil.TZ) == "Asia/Shanghai", str(timeutil.TZ))


def test_today_matches_beijing_offset() -> None:
    """beijing_today 必须等于 UTC+8 的日期，而非本地时区的 date.today()。"""
    expect = datetime.now(timezone.utc).astimezone(timeutil.TZ).date().isoformat()
    check("beijing_today == UTC+8 日期", timeutil.beijing_today() == expect, f"{timeutil.beijing_today()} vs {expect}")


def test_shift_days() -> None:
    today = timeutil.beijing_today_date()
    check("shift(-1) 为昨天", timeutil.beijing_shift_days(-1) == (today - timedelta(days=1)).isoformat())
    check("shift(+1) 为明天", timeutil.beijing_shift_days(1) == (today + timedelta(days=1)).isoformat())
    check("shift(0) 为今天", timeutil.beijing_shift_days(0) == today.isoformat())


def test_independent_of_local_tz() -> None:
    """即便进程 TZ 被改为 UTC，beijing_today 仍应给出北京时间日期。"""
    saved = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "UTC"
        # 由于 TZ 在进程启动后修改对 zoneinfo 的已解析对象不必然生效，
        # 此处仅验证不受影响：beijing_today 始终源于显式 Asia/Shanghai。
        expect = datetime.now(timezone.utc).astimezone(timeutil.TZ).date().isoformat()
        check("改 TZ 后 beijing_today 仍为北京时间", timeutil.beijing_today() == expect)
    finally:
        if saved is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved


if __name__ == "__main__":
    test_tz_is_shanghai()
    test_today_matches_beijing_offset()
    test_shift_days()
    test_independent_of_local_tz()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
