"""C1（CR7-7）+ CR9-4/CR9-22 离线单测：启动补跑的"让位热点"判据。

背景（2026-09-25 C0 实测实证）：热点补跑（sleep 5s）与同步补跑（sleep 8s）几乎同时
起跑，共用东财令牌桶——同步分页批量占满名额 → pipeline 拿不到 `cooling down` →
当日热点 degraded；且 stock 熔断连坐 hk（4ms 被拒）。C1 的处置是"同步让位热点"。

**CR9-4（2026-09-26）**：C1 原实现把"让位"写成了等**当日有没有 digest 产出**
（`while waited<600: … else: return`，唯一出口是 break）。两种常态下 count 恒为 0：
  ① 02:00–08:30 之间启动——热点侧未到点直接跳过，当日根本不会跑；
  ② 热点跑了但落库 0 行（新闻源全挂 / ingest 被 401 拒）。
两者都会死等到 600s 上限后 `return`，而调度器只在 02:00 触发 ⇒ **当天主数据同步
整日不发生**。修法：让位判据改为"热点正在跑 或 尚未定案"，热点一旦定案
（`scheduler._state["catchUpResolved"]==今天`，跑完/决定不跑/查询失败都算）立即同步。

**CR9-22**：原实现在循环里现编一条 web 查询，且 HTTP 非 2xx 走"继续等"、请求异常
走"直接放行"——同一件事两个方向。现整条删除，故本套件用 ⑦ 断言"不再发这条查询"。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_c1_catchup_yield.py
"""

import os
import sys
import time as _time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
# 自带 UTF-8 输出后，跑本脚本不再需要 PYTHONIOENCODING（errors=replace 兜极端情况）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


import app.sync_scheduler as ss  # noqa: E402
from app.utils.timeutil import beijing_today  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


class _FakeHotspot:
    """hotspot.scheduler 的最小替身：只暴露同步侧要读的那几个键。"""

    def __init__(self, running: bool = False, resolved: str | None = None) -> None:
        self._state = {
            "running": running,
            "lastRun": None,
            "lastResult": None,
            "runs": 0,
            "catchUpResolved": resolved,  # CR9-4 新增的定案标志
        }


def _install_hotspot(fake: _FakeHotspot):
    """把真实 hotspot.scheduler 的 _state 换成替身（同步侧按模块属性读取）。"""
    import app.hotspot.scheduler as hs

    orig_state = hs._state
    hs._state = fake._state  # type: ignore[misc]

    def _restore() -> None:
        hs._state = orig_state  # type: ignore[misc]

    return _restore


def _fast_sleep(counts: dict):
    """把循环里的 sleep(10) 变成计数，不真睡；其余 sleep（如启动等待 8s）压到 10ms。"""
    orig = _time.sleep

    def _sleep(s: float) -> None:
        if float(s) == ss.CATCHUP_POLL_INTERVAL_S:
            counts["polls"] += 1
            if counts.get("on_poll"):
                counts["on_poll"](counts["polls"])
            return
        orig(min(float(s), 0.01))

    return orig, _sleep


def _run_case(fake: _FakeHotspot, on_poll=None, forbid_web_query: bool = False,
              at_hour: int = 9, at_minute: int = 0) -> dict:
    """跑一次 _catch_up_if_needed，返回 {ran, polls}。

    forbid_web_query=True 时把 requests 钉成"一旦被调用就抛"，用来证明 CR9-22
    的那条查询确实被删掉了（而不是留着但走了另一条分支）。

    **时刻必须钉住（CR9-35，09-27 00:4x 实测）**：`_catch_up_if_needed` 开头有一道
    "未到当日调度时刻（默认 02:00）就直接 return"的门。本套件此前用它不存在的假设跑
    ——在 00:00–01:59 之间跑，11 个用例里 8 个被这道门静默吞掉（实测 3/11，全是
    `{n:0, polls:0}`）。默认钉到当天 09:00（已过调度点），需要走"未到点"分支的用例
    显式传 `at_hour/at_minute`。
    """
    ran = {"n": 0}
    counts = {"polls": 0, "on_poll": on_poll}
    restore_hs = _install_hotspot(fake)
    orig_run_now = ss.run_now
    orig_time = _time.sleep
    orig_dt = ss.datetime
    builtins_import = __import__("builtins").__import__

    class _PinnedDatetime:
        """只替 `datetime.now(TZ)`（模块内仅此一处用途），日期仍取真实北京今日。"""

        @staticmethod
        def now(tz=None):
            return orig_dt.now(tz or ss.TZ).replace(
                hour=at_hour, minute=at_minute, second=0, microsecond=0
            )

    ss.datetime = _PinnedDatetime  # type: ignore[misc]
    ss.run_now = lambda trigger="manual": (ran.__setitem__("n", ran["n"] + 1),  # type: ignore[assignment]
                                           ran.__setitem__("trigger", trigger),
                                           {"accepted": True})[2]
    if forbid_web_query:
        import builtins

        def _boom(name, *a, **k):
            if name == "requests":
                raise AssertionError("CR9-22：让位循环不应再查询 web /api/hotspots/ingest")
            return builtins_import(name, *a, **k)

        builtins.__import__ = _boom  # type: ignore[assignment]

    orig_sleep, fast = _fast_sleep(counts)
    _time.sleep = fast  # type: ignore[assignment]
    try:
        ss._catch_up_if_needed()
    finally:
        _time.sleep = orig_sleep  # type: ignore[assignment]
        ss.run_now = orig_run_now  # type: ignore[assignment]
        ss.datetime = orig_dt  # type: ignore[misc]
        if forbid_web_query:
            import builtins

            builtins.__import__ = builtins_import  # type: ignore[assignment]
        restore_hs()
    ran["polls"] = counts["polls"]
    return ran


def test_yields_while_hotspot_running() -> None:
    """① 热点在跑 → 等待；跑完并定案后才触发同步（C1 原语义不变）。"""
    fake = _FakeHotspot(running=True, resolved=None)

    def _finish(polls: int) -> None:
        if polls >= 2:  # 第 2 轮：热点结束并定案
            fake._state["running"] = False
            fake._state["catchUpResolved"] = beijing_today()

    r = _run_case(fake, on_poll=_finish)
    check("C1①：热点结束后同步才触发",
          r["n"] == 1 and r.get("trigger") == "startup-catchup", str(r))
    check("C1①：等待期间确实轮询了热点状态", r["polls"] == 2, str(r["polls"]))


def test_proceeds_when_hotspot_resolved_with_output() -> None:
    """② 热点已定案且当日有产出 → 零等待直接同步。"""
    fake = _FakeHotspot(running=False, resolved=beijing_today())
    r = _run_case(fake)
    check("C1②：热点定案且已跑过 → 立即同步（零等待）", r["n"] == 1 and r["polls"] == 0, str(r))


def test_gives_up_when_hotspot_never_finishes() -> None:
    """③ 热点始终在跑 → 600s 上限后放弃本轮（不能压在一个卡死的 pipeline 上）。"""
    fake = _FakeHotspot(running=True, resolved=None)
    r = _run_case(fake)
    check("C1③：热点永不结束 → 到上限放弃本轮（不跑同步）", r["n"] == 0, str(r))
    check("C1③：确实走满了轮询上限", r["polls"] >= int(
        ss.CATCHUP_YIELD_MAX_WAIT_S / ss.CATCHUP_POLL_INTERVAL_S), str(r["polls"]))


def test_skips_when_already_synced_today() -> None:
    """④ 当日已同步（lastDate=今天）→ 跳过（原有语义保持）。"""
    orig_last_date = ss._state.get("lastDate")
    ss._state["lastDate"] = beijing_today()
    try:
        r = _run_case(_FakeHotspot(running=False, resolved=beijing_today()))
        check("C1④：当日已同步 → 跳过（不重复）", r["n"] == 0, str(r))
    finally:
        ss._state["lastDate"] = orig_last_date


def test_cr9_4_before_hotspot_schedule() -> None:
    """⑤ CR9-4 触发路径一：02:00–08:30 启动，热点决定今天不跑（定案、0 产出）。

    旧实现：count 恒 0 → 死等 600s → `return` → **当天同步不发生**。
    新实现：热点已定案 → 立即同步。
    """
    fake = _FakeHotspot(running=False, resolved=beijing_today())  # 决定不跑也算定案
    r = _run_case(fake, forbid_web_query=True)
    check("CR9-4⑤：热点未到点跳过（0 产出）→ 同步照常立即执行", r["n"] == 1 and r["polls"] == 0, str(r))


def test_cr9_4_hotspot_finished_with_zero_rows() -> None:
    """⑥ CR9-4 触发路径二：热点跑了但落库 0 行（新闻源全挂 / ingest 401）。"""
    fake = _FakeHotspot(running=False, resolved=beijing_today())
    fake._state["lastResult"] = {"ok": True, "inserted": 0}  # 跑过，零产出
    r = _run_case(fake, forbid_web_query=True)
    check("CR9-4⑥：热点跑完但 0 行 → 不再死等，同步照常执行", r["n"] == 1, str(r))
    check("CR9-4⑥：定案态生效 = **零轮询死等**（旧实现这里会空转 61 轮到上限）",
          r["polls"] == 0, str(r["polls"]))


def test_cr9_4_never_resolved_still_syncs_at_cap() -> None:
    """⑦ 热点既没在跑也一直没定案（其补跑线程异常/被跳过）→ 到上限**仍要同步**。

    与 ③ 的区别是本判定的落点：仍在跑才放弃，没在跑就不能把当天饿掉。
    """
    fake = _FakeHotspot(running=False, resolved=None)
    r = _run_case(fake)
    check("CR9-4⑦：热点从未定案且未运行 → 到上限仍同步（不是放弃）", r["n"] == 1, str(r))


def test_cr9_22_stale_resolved_from_previous_day() -> None:
    """⑧ 反向对照：定案态必须是**今天**，昨天的 `catchUpResolved` 不算数。

    （若把它当数，跨天重启时同步会在热点真要跑的时候抢先起跑 → 回到 CR7-7 的连坐。）
    """
    fake = _FakeHotspot(running=False, resolved="2026-01-01")
    r = _run_case(fake)
    check("CR9-4⑧：昨日定案不生效（轮询等待，直到上限后同步）",
          r["n"] == 1 and r["polls"] >= int(
              ss.CATCHUP_YIELD_MAX_WAIT_S / ss.CATCHUP_POLL_INTERVAL_S), str(r))


def test_cr9_35_before_schedule_gate_skips_without_polling() -> None:
    """⑨ CR9-35：未到当日调度时刻（默认 02:00）→ 立即跳过，不轮询也不同步。

    这条分支此前**没有任何用例覆盖**：整套 _catch_up_if_needed 测试都在真实墙上时钟
    上跑，00:00–01:59 之间执行时全部用例被这道门吞掉（09-27 00:4x 实测 3/11、
    失败详情一律 `{n:0, polls:0}`）。补上分支覆盖 + 把时刻钉住，两件事一起做。
    """
    fake = _FakeHotspot(running=False, resolved=beijing_today())
    r = _run_case(fake, at_hour=1, at_minute=30)
    check("CR9-35⑨：未到调度时刻 → 立即跳过（不同步、零轮询）",
          r["n"] == 0 and r["polls"] == 0, str(r))
    # 反向对照：同一时刻若已过调度点（SYNC_HOUR=0），必须照常走到同步
    os.environ["SYNC_HOUR"] = "0"
    os.environ["SYNC_MINUTE"] = "0"
    try:
        r2 = _run_case(fake, at_hour=1, at_minute=30)
        check("CR9-35⑨🔁：调度时刻改 00:00 后同一时刻立即同步（证明判定读的是调度点）",
              r2["n"] == 1 and r2["polls"] == 0, str(r2))
    finally:
        os.environ.pop("SYNC_HOUR", None)
        os.environ.pop("SYNC_MINUTE", None)


def test_sync_catchup_off_switch() -> None:
    """⑩ #16（2026-10-01 主人点头）：`SYNC_CATCHUP=off` 只关启动补跑，不关每日 cron。

    这条开关存在的理由就是本套件反复踩的那个耦合：补跑判据与 cron 时刻读同一组
    `SYNC_HOUR/SYNC_MINUTE` ⇒ 过去起一个"不顺手补跑"的 ds 只能撒谎挪时刻，而挪掉的
    正是当晚那档 cron，还得记得在挪到的时刻前停服务。所以断言必须**两条一起**：
    off 确实拦住补跑，且 off **没有**改变 cron 时刻。
    """
    fake = _FakeHotspot(running=False, resolved=beijing_today())
    os.environ["SYNC_CATCHUP"] = "off"
    os.environ["SYNC_HOUR"] = "3"
    os.environ["SYNC_MINUTE"] = "30"
    try:
        r = _run_case(fake, at_hour=9, at_minute=0)
        check("#16⑩：SYNC_CATCHUP=off → 已过调度点也不补跑（零轮询、不 sleep）",
              r["n"] == 0 and r["polls"] == 0, str(r))
        check("#16⑩：off 不得改变 cron 时刻（_sync_hour_minute 仍读配置）",
              ss._sync_hour_minute() == (3, 30), str(ss._sync_hour_minute()))
        # 🔁 反向：同一时刻同一状态，开关回到默认 on 必须照常补跑
        os.environ.pop("SYNC_CATCHUP", None)
        r2 = _run_case(fake, at_hour=9, at_minute=0)
        check("#16⑩：不设开关（默认 on）同一场景照常同步（证明 off 不是恒假桩）",
              r2["n"] == 1 and r2["polls"] == 0, str(r2))
    finally:
        os.environ.pop("SYNC_CATCHUP", None)
        os.environ.pop("SYNC_HOUR", None)
        os.environ.pop("SYNC_MINUTE", None)


def main() -> int:
    test_yields_while_hotspot_running()
    test_proceeds_when_hotspot_resolved_with_output()
    test_gives_up_when_hotspot_never_finishes()
    test_skips_when_already_synced_today()
    test_cr9_4_before_hotspot_schedule()
    test_cr9_4_hotspot_finished_with_zero_rows()
    test_cr9_4_never_resolved_still_syncs_at_cap()
    test_cr9_22_stale_resolved_from_previous_day()
    test_cr9_35_before_schedule_gate_skips_without_polling()
    test_sync_catchup_off_switch()
    passed = sum(1 for _n, ok, _d in results if ok)
    fails = [x for x in results if not x[1]]
    for name, _ok, detail in fails:
        print(f"[FAIL] {name}  <- {detail[:160]}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
