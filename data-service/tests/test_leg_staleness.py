"""CR10-1 离线单测：三条腿「整夜根本没跑」变成读时自证的机器可读判据。

背景（10-19／10-20／10-21 三夜同一形，`FIX-LEDGER.md`「本轮不做」观察项①）：腿的
`skippedReason` 只住内存，而**擦掉它的那次重启正是丢腿的原因**；备份腿早有先例
（`backup_scheduler.py` 的 `fresh`／`stale-Nh`／`no-state`／`unreadable-state`），同步腿与
热点腿没有 ⇒ 连丢三夜在盘上读不出来（`sync-state.json` 停在 10-19、库里没有新快照，而
没有任何一格说话）。

处置＝把「这条腿本来该在什么时候之前跑过」放进两处**已经在读盘上 marker** 的只读
`status()`，不新造作业、不新造进程（进程不在就没资格报警）。verdict 词表与备份腿同字面。

⚠️ 本套件刻意**不设** `LIMITER_STATE_FILE`（反面教材＝`test_p6_mcp.py:22-25`：它把限流账
指进临时目录，于是自己那发真报价哪本账都读不到＝账外账）；并逐次核对仓库里那两份真
marker 的 mtime 没被写过。

运行方式（无需任何服务在跑、零出网）：
    PYTHONPATH=. .venv/Scripts/python tests/test_leg_staleness.py
"""

import json
import os
import sys
import tempfile
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# 隔离＝交付物的一部分（CR9-94 那一课）：两份真 marker 带着今天的日期，假轮若写进真文件
# 会静默挡掉当天合法的补跑。先把落点指进临时目录，再 import app。
_TMPDIR = tempfile.mkdtemp(prefix="cr101-leg-staleness-")
os.environ["SYNC_STATE_FILE"] = os.path.join(_TMPDIR, "sync-state.json")
os.environ["HOTSPOT_STATE_FILE"] = os.path.join(_TMPDIR, "hotspot-state.json")
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REAL_MARKERS = [
    os.path.join(_APP_DIR, "runtime", "sync-state.json"),
    os.path.join(_APP_DIR, "runtime", "hotspot-state.json"),
]
_MTIME_BEFORE = {p: (os.path.getmtime(p) if os.path.exists(p) else None) for p in _REAL_MARKERS}
_LIMITER_ENV_BEFORE = os.environ.get("LIMITER_STATE_FILE")

import requests  # noqa: E402

import app.hotspot.scheduler as hs  # noqa: E402
import app.sync_scheduler as ss  # noqa: E402
from app.utils.timeutil import TZ, beijing_shift_days, beijing_today, leg_staleness  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _at(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


# 2026-10 的星期实算过再写：17/18＝周六日、19＝一、21＝三、24/25＝周六日、26＝一。
WED_EVE = _at(2026, 10, 21, 17, 40)
WED_EARLY = _at(2026, 10, 21, 1, 30)
MON_EARLY = _at(2026, 10, 26, 6, 0)
MON_LATE = _at(2026, 10, 26, 9, 0)
SAT_NOON = _at(2026, 10, 24, 12, 0)


def test_pure_matrix() -> None:
    """同步腿（每天 02:00，weekdays_only=False）的六格。"""
    a = leg_staleness("2026-10-21", hour=2, minute=0, now=WED_EVE)
    check("今天跑过 ⇒ fresh", a["verdict"] == "fresh", str(a))
    check("fresh 的 ageDays＝0", a["ageDays"] == 0, str(a))
    b = leg_staleness("2026-10-20", hour=2, minute=0, now=WED_EVE)
    check("昨天跑过而今天已到期 ⇒ missed-today", b["verdict"] == "missed-today", str(b))
    c = leg_staleness("2026-10-19", hour=2, minute=0, now=WED_EVE)
    check("落下两天 ⇒ stale-2d（ageDays 从今天算，不从义务日算）",
          c["verdict"] == "stale-2d" and c["ageDays"] == 2, str(c))
    d = leg_staleness(None, hour=2, minute=0, now=WED_EVE)
    check("盘上什么都没有 ⇒ never（不是 unreadable）",
          d["verdict"] == "never" and d["ageDays"] is None, str(d))
    e = leg_staleness("", hour=2, minute=0, now=WED_EVE)
    check("空串同样 never", e["verdict"] == "never", str(e))
    f = leg_staleness("2026-13-45", hour=2, minute=0, now=WED_EVE)
    check("坏日期 ⇒ unreadable", f["verdict"] == "unreadable", str(f))
    g = leg_staleness(date(2026, 10, 21), hour=2, minute=0, now=WED_EVE)
    check("date 对象与字符串同解", g["verdict"] == "fresh", str(g))
    h = leg_staleness("2026-10-22", hour=2, minute=0, now=WED_EVE)
    check("时钟歪了（未来日期）不误报，读成 fresh", h["verdict"] == "fresh", str(h))


def test_not_yet_due_is_silent() -> None:
    """未到点不许吵——这一格是"误报"与"漏报"的分界。"""
    a = leg_staleness("2026-10-20", hour=2, minute=0, now=WED_EARLY)
    check("01:30 读：昨天跑过 ⇒ fresh（义务仍是昨天那一轮）",
          a["verdict"] == "fresh" and a["ageDays"] == 1, str(a))
    b = leg_staleness("2026-10-19", hour=2, minute=0, now=WED_EARLY)
    check("01:30 读：前天跑过 ⇒ 仍报 stale（今天未到点不等于没事）",
          b["verdict"] == "stale-2d", str(b))
    check("义务时刻带时区落到分钟",
          a["expectedBy"] == "2026-10-20T02:00+08:00", repr(a["expectedBy"]))
    c = leg_staleness(None, hour=2, minute=0, now=WED_EVE)
    check("never 也把义务时刻交出来（读的人要知道本该发生什么）",
          c["expectedBy"] == "2026-10-21T02:00+08:00", repr(c["expectedBy"]))


def test_weekend_chain() -> None:
    """热点腿（工作日 08:30）：周末链条不能被读成丢腿。"""
    a = leg_staleness("2026-10-23", hour=8, minute=30, weekdays_only=True, now=MON_EARLY)
    check("周一 06:00 读上周五的产出 ⇒ fresh（ageDays 3 但没到期）",
          a["verdict"] == "fresh" and a["ageDays"] == 3, str(a))
    b = leg_staleness("2026-10-23", hour=8, minute=30, weekdays_only=True, now=MON_LATE)
    check("周一 09:00（已过 08:30）读上周五 ⇒ missed-today",
          b["verdict"] == "missed-today", str(b))
    c = leg_staleness("2026-10-22", hour=8, minute=30, weekdays_only=True, now=MON_LATE)
    check("周一 09:00 读上周四（落下整条周五） ⇒ stale-4d",
          c["verdict"] == "stale-4d" and c["ageDays"] == 4, str(c))
    d = leg_staleness("2026-10-23", hour=8, minute=30, weekdays_only=True, now=SAT_NOON)
    check("周六读周五 ⇒ fresh＝周末不许报警", d["verdict"] == "fresh", str(d))
    e = leg_staleness("2026-10-21", hour=8, minute=30, weekdays_only=True, now=SAT_NOON)
    check("周六读周三（缺了周五） ⇒ stale-3d", e["verdict"] == "stale-3d", str(e))
    f = leg_staleness("2026-10-21", hour=2, minute=0, now=SAT_NOON)
    check("同一天同一份读数，同步腿不看周末（它每天都跑）",
          f["verdict"] == "stale-3d", str(f))


def test_instrument_override() -> None:
    """写不进／读不出 ⇒ 不能拿盘上那份判新鲜度，也不许用省略冒充。"""
    a = leg_staleness("2026-10-21", hour=2, minute=0, now=WED_EVE, instrument_ok=False)
    check("instrument_ok=False 覆盖一切 ⇒ instrument-untrusted",
          a["verdict"] == "instrument-untrusted", str(a))
    check("覆盖时其余字段照给（读数不消失，只是不可信）",
          a["lastAttemptDate"] == "2026-10-21" and a["ageDays"] == 0, str(a))


def _write_sync_marker(payload: dict) -> None:
    with open(os.environ["SYNC_STATE_FILE"], "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _write_hotspot_marker(payload: dict) -> None:
    with open(os.environ["HOTSPOT_STATE_FILE"], "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _reset_states() -> None:
    for st in (ss._state, hs._state):
        for k in ("markerWriteFailed", "markerReadError", "stateWriteFailed"):
            st[k] = False
    for p in (os.environ["SYNC_STATE_FILE"], os.environ["HOTSPOT_STATE_FILE"]):
        if os.path.exists(p):
            os.remove(p)


def test_wiring_sync() -> None:
    """/sync/status 那一格真接上了（与时钟、与星期无关的三枚断言）。"""
    _reset_states()
    got = ss.status()["legStaleness"]
    check("无 marker ⇒ status 报 never", got["verdict"] == "never", str(got))
    _write_sync_marker({"lastAttemptDate": beijing_today()})
    check("今天试过 ⇒ status 报 fresh",
          ss.status()["legStaleness"]["verdict"] == "fresh", str(ss.status()["legStaleness"]))
    _write_sync_marker({"lastAttemptDate": beijing_shift_days(-9)})
    got9 = ss.status()["legStaleness"]
    check("九天前 ⇒ status 报 stale-9d（这一格与今天几点几分星期几无关）",
          got9["verdict"] == "stale-9d" and got9["ageDays"] == 9, str(got9))
    ss._state["markerWriteFailed"] = True
    check("markerWriteFailed ⇒ status 那格转 instrument-untrusted",
          ss.status()["legStaleness"]["verdict"] == "instrument-untrusted", "")
    ss._state["markerWriteFailed"] = False
    ss._state["markerReadError"] = "boom"
    check("markerReadError 同样算仪器不可信",
          ss.status()["legStaleness"]["verdict"] == "instrument-untrusted", "")
    check("四枚子键齐全",
          set(ss.status()["legStaleness"]) == {"verdict", "ageDays", "expectedBy", "lastAttemptDate"},
          str(set(ss.status()["legStaleness"])))


def test_wiring_hotspot() -> None:
    """/hotspots/status 那一格：一条 marker 服务两条腿，义务取盘前那一枚。"""
    _reset_states()
    check("无 marker ⇒ never", hs.status()["legStaleness"]["verdict"] == "never", "")
    _write_hotspot_marker({"lastAttemptDate": beijing_today(), "lastAttemptTrigger": "pre-market"})
    check("今天跑过 ⇒ fresh", hs.status()["legStaleness"]["verdict"] == "fresh", "")
    _write_hotspot_marker({"lastAttemptDate": beijing_shift_days(-9)})
    got9 = hs.status()["legStaleness"]
    check("九天前 ⇒ stale-9d", got9["verdict"] == "stale-9d" and got9["ageDays"] == 9, str(got9))
    hs._state["stateWriteFailed"] = True
    check("stateWriteFailed ⇒ instrument-untrusted",
          hs.status()["legStaleness"]["verdict"] == "instrument-untrusted", "")


def test_status_makes_no_network_call() -> None:
    """只读判据不许花额度：把 requests 换成"记一笔就抛"，跑完清单必须是空的。"""
    calls: list[str] = []
    orig_get, orig_post = requests.get, requests.post

    def _boom(*a, **k):
        calls.append(f"{a[0] if a else k}")
        raise AssertionError("status() 出网了")

    requests.get = requests.post = _boom  # type: ignore[assignment]
    try:
        _reset_states()
        _write_sync_marker({"lastAttemptDate": beijing_shift_days(-3)})
        _write_hotspot_marker({"lastAttemptDate": beijing_shift_days(-3)})
        s = ss.status()
        h = hs.status()
    finally:
        requests.get, requests.post = orig_get, orig_post
    check("两枚 status 跑完，网络调用清单为空", calls == [], str(calls))
    check("而且两份 verdict 都读出来了",
          s["legStaleness"]["verdict"].startswith(("stale", "missed"))
          and h["legStaleness"]["verdict"].startswith(("stale", "missed", "fresh")),
          f"{s['legStaleness']}｜{h['legStaleness']}")


def test_no_off_book_accounting() -> None:
    """反面教材＝p6：把限流账指进临时目录 ⇒ 自己那发真报价哪本账都读不到。"""
    check("本套件没有动 LIMITER_STATE_FILE",
          os.environ.get("LIMITER_STATE_FILE") == _LIMITER_ENV_BEFORE,
          repr(os.environ.get("LIMITER_STATE_FILE")))
    still = {p: (os.path.getmtime(p) if os.path.exists(p) else None) for p in _REAL_MARKERS}
    check("仓库里那两份真 marker 的 mtime 全程未变（假轮没写进真文件）",
          still == _MTIME_BEFORE, f"{_MTIME_BEFORE} -> {still}")
    check("落点确实被指进了临时目录（不在 runtime/ 里）",
          os.environ["SYNC_STATE_FILE"].startswith(_TMPDIR)
          and os.environ["HOTSPOT_STATE_FILE"].startswith(_TMPDIR), "")


def _legacy_no_verdict(attempt_date):
    """CR10-1 之前唯一存在的问法：「今天跑过吗」。摘掉新判据就只剩它。"""
    return "fresh" if attempt_date == beijing_today() else None


def test_removal_drift_pair() -> None:
    """🔁 C34：旧问法对「落下九天」与「盘上什么都没有」给同一个答案＝瞎。"""
    nine = beijing_shift_days(-9)
    check("🔁 摘掉新判据后两枚输入同值（旧仪器读不出丢了几夜）",
          _legacy_no_verdict(nine) == _legacy_no_verdict(None) is None,
          f"{_legacy_no_verdict(nine)} vs {_legacy_no_verdict(None)}")
    fresh = leg_staleness(nine, hour=2, minute=0)
    never = leg_staleness(None, hour=2, minute=0)
    check("真判据把两者分名（stale-Nd ⇔ never）",
          fresh["verdict"].startswith("stale-") and never["verdict"] == "never"
          and fresh["verdict"] != never["verdict"], f"{fresh} vs {never}")
    check("新判据也不是恒真：三格输入三个不同 verdict",
          len({leg_staleness(x, hour=2, minute=0)["verdict"]
               for x in (beijing_today(), nine, None)}) == 3, "")


def main() -> int:
    test_pure_matrix()
    test_not_yet_due_is_silent()
    test_weekend_chain()
    test_instrument_override()
    test_wiring_sync()
    test_wiring_hotspot()
    test_status_makes_no_network_call()
    test_no_off_book_accounting()
    test_removal_drift_pair()
    passed = sum(1 for _n, ok, _d in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"[FAIL] {name}  <- {detail}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
