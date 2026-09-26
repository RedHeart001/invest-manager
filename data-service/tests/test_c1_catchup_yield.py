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


def _run_case(fake: _FakeHotspot, on_poll=None, forbid_web_query: bool = False) -> dict:
    """跑一次 _catch_up_if_needed，返回 {ran, polls}。

    forbid_web_query=True 时把 requests 钉成"一旦被调用就抛"，用来证明 CR9-22
    的那条查询确实被删掉了（而不是留着但走了另一条分支）。
    """
    ran = {"n": 0}
    counts = {"polls": 0, "on_poll": on_poll}
    restore_hs = _install_hotspot(fake)
    orig_run_now = ss.run_now
    orig_time = _time.sleep
    builtins_import = __import__("builtins").__import__

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


def main() -> int:
    test_yields_while_hotspot_running()
    test_proceeds_when_hotspot_resolved_with_output()
    test_gives_up_when_hotspot_never_finishes()
    test_skips_when_already_synced_today()
    test_cr9_4_before_hotspot_schedule()
    test_cr9_4_hotspot_finished_with_zero_rows()
    test_cr9_4_never_resolved_still_syncs_at_cap()
    test_cr9_22_stale_resolved_from_previous_day()
    passed = sum(1 for _n, ok, _d in results if ok)
    fails = [x for x in results if not x[1]]
    for name, _ok, detail in fails:
        print(f"[FAIL] {name}  <- {detail[:160]}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
