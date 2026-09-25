"""C1（CR7-7）离线单测：启动补跑让位热点——同步等热点 pipeline 结束后再跑。

背景（2026-09-25 C0 实测实证）：热点补跑（sleep 5s）与同步补跑（sleep 8s）
几乎同时起跑，共用东财令牌桶——同步分页批量占满名额 → pipeline 拿不到令牌
`cooling down` → 当日热点 degraded；且 stock 熔断连坐 hk（4ms 被拒）。
修复：同步补跑让位——热点在跑/当日无 digest 时轮询等待（10s 间隔，上限 600s），
热点结束后再跑同步。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_c1_catchup_yield.py
"""

import os
import sys
import time as _time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.sync_scheduler as ss  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


class _FakeHotspot:
    """hotspot.scheduler 模块的最小替身（_state 为真实形态的 dict）。"""

    def __init__(self) -> None:
        self._state = {"running": False, "lastRun": None, "lastResult": None, "runs": 0}


def _patch_hotspot(fake_hotspot: _FakeHotspot, digest_count: int):
    """伪造 hotspot_scheduler 模块与 web /api/hotspots/ingest 响应。"""
    import app.hotspot.scheduler as hs

    orig_module_attrs = {
        "_state": hs._state,
        "_reached_schedule_today": getattr(hs, "_reached_schedule_today", None),
    }

    class _Resp:
        ok = True

        def json(self) -> dict:
            return {"count": digest_count}

    fake_requests = types.SimpleNamespace(get=lambda url, params=None, timeout=None: _Resp())
    orig_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __builtins__["__import__"]

    def _fake_import(name, *a, **k):
        if name == "requests":
            return fake_requests
        return orig_import(name, *a, **k)

    import builtins

    orig_builtins_import = builtins.__import__

    def _patched(name, *a, **k):
        if name == "requests":
            return fake_requests
        return orig_builtins_import(name, *a, **k)

    builtins.__import__ = _patched
    # 让 sync_scheduler 里的 `from .hotspot import scheduler as hotspot_scheduler`
    # 拿到替身：hotspot.scheduler 的 _state 换成替身的 dict
    hs._state = fake_hotspot._state  # type: ignore[misc]
    return {
        "restore": lambda: (
            hs.__dict__.update({"_state": orig_module_attrs["_state"]}),
            builtins.__dict__.update({"__import__": orig_builtins_import}),
        )
    }


def test_catchup_yields_to_running_hotspot() -> None:
    """① 热点在跑 → 同步等待；热点结束后同步才触发。"""
    fake = _FakeHotspot()
    fake._state["running"] = True
    patch = _patch_hotspot(fake, digest_count=9)  # 热点跑完会有产出

    ran = {"n": 0}
    orig_run_now = ss.run_now

    def _fake_run_now(trigger: str = "manual") -> dict:
        ran["n"] += 1
        ran["trigger"] = trigger
        return {"accepted": True}

    ss.run_now = _fake_run_now  # type: ignore[assignment]
    orig_sleep = _time.sleep

    # 轮询 sleep(10) 加速：第 2 次 poll 后热点结束（此后 digest 查询返回 9 行）
    polls = {"n": 0}

    def _fast_sleep(s: float) -> None:
        if s == 10.0 or s == 10:
            polls["n"] += 1
            if polls["n"] >= 2:
                fake._state["running"] = False
            return
        orig_sleep(min(s, 0.01))

    _time.sleep = _fast_sleep  # type: ignore[assignment]
    try:
        ss._catch_up_if_needed()
        check("C1：热点结束后同步才触发", ran["n"] == 1 and ran.get("trigger") == "startup-catchup", str(ran))
        check("C1：等待期间轮询了热点状态", polls["n"] == 2, str(polls))
    finally:
        _time.sleep = orig_sleep  # type: ignore[assignment]
        ss.run_now = orig_run_now  # type: ignore[assignment]
        patch["restore"]()


def test_catchup_proceeds_when_digest_exists() -> None:
    """② 当日已有 digest（热点未跑）→ 不等待，直接跑同步。"""
    fake = _FakeHotspot()
    fake._state["running"] = False
    patch = _patch_hotspot(fake, digest_count=5)

    ran = {"n": 0}
    orig_run_now = ss.run_now
    ss.run_now = lambda trigger="manual": (ran.__setitem__("n", ran["n"] + 1), ran.__setitem__("trigger", trigger), {"accepted": True})[2]  # type: ignore[assignment]
    orig_sleep = _time.sleep
    _time.sleep = lambda s: orig_sleep(min(s, 0.01))  # type: ignore[assignment]
    try:
        ss._catch_up_if_needed()
        check("C1：当日已有产出 → 立即同步（零等待）", ran["n"] == 1, str(ran))
    finally:
        _time.sleep = orig_sleep  # type: ignore[assignment]
        ss.run_now = orig_run_now  # type: ignore[assignment]
        patch["restore"]()


def test_catchup_gives_up_after_timeout() -> None:
    """③ 热点长时间不结束 → 600s 上限后放弃本轮（不触发同步）。"""
    fake = _FakeHotspot()
    fake._state["running"] = True  # 始终在跑
    patch = _patch_hotspot(fake, digest_count=0)

    ran = {"n": 0}
    orig_run_now = ss.run_now
    ss.run_now = lambda trigger="manual": (ran.__setitem__("n", ran["n"] + 1), {"accepted": True})[1]  # type: ignore[assignment]
    orig_sleep = _time.sleep

    def _fast_sleep(s: float) -> None:
        pass  # 轮询 sleep 不真睡 → 61 次循环瞬间走完 600s 计数

    _time.sleep = _fast_sleep  # type: ignore[assignment]
    try:
        ss._catch_up_if_needed()
        check("C1：热点永不结束 → 600s 后放弃本轮（不跑同步）", ran["n"] == 0, str(ran))
    finally:
        _time.sleep = orig_sleep  # type: ignore[assignment]
        ss.run_now = orig_run_now  # type: ignore[assignment]
        patch["restore"]()


def test_catchup_before_schedule_skipped() -> None:
    """④ 当日已同步（lastDate=今天）→ 原有跳过语义不变。"""
    from app.utils.timeutil import beijing_today

    orig_run_now = ss.run_now
    ran = {"n": 0}
    ss.run_now = lambda trigger="manual": (ran.__setitem__("n", ran["n"] + 1), {"accepted": True})[1]  # type: ignore[assignment]
    orig_sleep = _time.sleep
    _time.sleep = lambda s: orig_sleep(min(s, 0.01))  # type: ignore[assignment]
    try:
        ss._state["lastDate"] = beijing_today()
        ss._catch_up_if_needed()
        check("C1：当日已同步 → 跳过（不重复）", ran["n"] == 0, str(ran))
    finally:
        _time.sleep = orig_sleep  # type: ignore[assignment]
        ss.run_now = orig_run_now  # type: ignore[assignment]
        ss._state["lastDate"] = None


if __name__ == "__main__":
    test_catchup_yields_to_running_hotspot()
    test_catchup_proceeds_when_digest_exists()
    test_catchup_gives_up_after_timeout()
    test_catchup_before_schedule_skipped()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
