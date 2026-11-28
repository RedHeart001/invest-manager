"""CR10-52 离线单测：刷新腿摘要自己落盘，`/sync/status` 不再依赖 Web。

背景（2026-11-28 P2 技术债）：CR10-51 让 DS 重启后按精确 `runId` 从 Web 已持久化的
`refresh-progress` 恢复 `lastRefresh`，功能正确但把观测接口挂到了另一个服务上——
`status()` 在内存结果缺失时每次调用都会走一遍恢复路径，即每次 `GET /sync/status`
都可能打一次 Web `/api/health`。Web 重启中／未就绪时，DS 的观测接口跟着一起瘸。

本套件钉住：

- 刷新腿收尾把结果写进 `sync-refresh-state.json`，形状与 `/sync/status.lastRefresh` 同源；
- 重启后优先读自己的摘要（`lastRefreshSource="disk"`），且**零网络请求**；
- 旧版本没写过摘要时回落到 Web 进度（`lastRefreshSource="web-progress"`），不是删掉一个来源；
- 摘要的 `runId` 与本轮不符（跨日／补试轮／上一轮遗留）⇒ 拒绝冒充本轮；
- 摘要损坏／缺失／非对象 ⇒ 当“没有”，不抛、不改写、不影响其它状态位；
- 写盘失败不改变刷新腿自己的结论。

运行（零出网、零 SQLite、零 Docker）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr10_52_refresh_state_persist.py
"""

import copy
import json
import os
import sys
import tempfile

_STATE_DIR = tempfile.mkdtemp(prefix="cr1052-syncstate-")
os.environ["SYNC_STATE_FILE"] = os.path.join(_STATE_DIR, "sync-state.json")
os.environ["US_LIST_JOB_DIR"] = os.path.join(tempfile.mkdtemp(prefix="cr1052-usjob-"), "job")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import app.sync_scheduler as ss  # noqa: E402

TODAY = ss.beijing_today()
results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _refresh_body(weak: list[str] | None = None, run_id: str | None = None) -> dict:
    weak = weak or []
    rows = [
        {"type": t, "updated": 1, "failedBatches": 1 if t in weak else 0, "failedEmpty": 1 if t in weak else 0}
        for t in ("fund", "stock", "bond", "crypto", "hk")
    ]
    return {"ok": not weak, "tookMs": 10, "results": rows, "runId": run_id or f"daily-{TODAY}"}


class _Resp:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def _reset_marker(**over) -> dict:
    marker = {
        "lastAttemptDate": TODAY,
        "lastAttemptTrigger": "daily",
        "lastAttemptOutcome": "completed",
        "at": "2026-11-28T02:09:12+08:00",
        "lastResult": {"ok": True, "outcome": "completed", "results": [{"type": "fund", "count": 1}]},
    }
    marker.update(over)
    ss._write_marker(copy.deepcopy(marker))
    with ss._lock:
        ss._state["lastResult"] = None
        ss._state["lastRefresh"] = None
    return marker


def _clear_refresh_state() -> None:
    try:
        os.remove(ss._refresh_state_path())
    except OSError:
        pass


def _write(refresh: dict) -> bool:
    return ss._write_refresh_state(refresh)


def test_refresh_leg_writes_state() -> None:
    """刷新腿收尾必须自己落盘，且落的就是它得出的 outcome（不是推测出来的）。"""
    _reset_marker()
    _clear_refresh_state()
    body = _refresh_body(weak=["fund", "hk"])
    ss_web_base_orig = ss._web_base
    ss._web_base = lambda: "http://127.0.0.1:3000"  # type: ignore[assignment]
    import requests

    orig_post_fn = requests.post
    requests.post = lambda *a, **k: _Resp(body)  # type: ignore[assignment]
    try:
        out = ss._refresh_leg("daily")
    finally:
        requests.post = orig_post_fn
        ss._web_base = ss_web_base_orig
    stored = ss.read_refresh_state() or {}
    check("① 刷新腿结果落盘（文件存在且 runId 是本轮）", stored.get("runId") == f"daily-{TODAY}", str(stored)[:160])
    check("①b 落盘那份与返回值同源（outcome/weakTypes/results 一致）",
          stored.get("outcome") == out.get("outcome") == "partial_failed"
          and stored.get("weakTypes") == ["fund", "hk"]
          and len(stored.get("results") or []) == len(out.get("results") or []))
    check("①c 落盘带 finishedAt（事后能判是哪一刻收尾的）", bool(stored.get("finishedAt")))


def test_recover_prefers_disk_and_needs_no_network() -> None:
    """重启后首选自己的摘要，且**一次网络都不发**——这是这条技术债的判据本体。"""
    _reset_marker()
    _clear_refresh_state()
    ss._write_refresh_state(
        {"runId": f"daily-{TODAY}", "outcome": "partial_failed", "weakTypes": ["fund", "hk"],
         "finishedAt": "2026-11-28T10:24:30+08:00", "results": [{"type": "fund", "failedBatches": 2}]}
    )
    calls: list[str] = []

    def _boom(*a, **k):
        calls.append(str(a[0]) if a else "?")
        raise AssertionError("有摘要时不得回头问 Web")

    import requests

    orig_post, orig_get = requests.post, requests.get
    requests.post = _boom  # type: ignore[assignment]
    requests.get = _boom  # type: ignore[assignment]
    try:
        st = ss.status()
    finally:
        requests.post, requests.get = orig_post, orig_get
    refresh = st.get("lastRefresh") or {}
    check("② 重启后从自己落盘的摘要恢复", refresh.get("outcome") == "partial_failed"
          and refresh.get("weakTypes") == ["fund", "hk"] and refresh.get("recoveredFromDisk") is True)
    check("②b 恢复来源可分辨（disk，不冒充 web-progress）",
          st.get("lastRefreshSource") == "disk" and st.get("lastRefreshFromWebProgress") is False)
    check("②c 恢复过程零网络请求（观测接口不再依赖 Web）", calls == [], str(calls))
    check("②d 逐类缺口不被总状态 completed 吞掉",
          [r.get("failedBatches") for r in refresh.get("results") or []] == [2])


def test_fallback_to_web_when_no_disk_state() -> None:
    """旧版本没写过摘要 ⇒ 仍能按 runId 从 Web 读回；这是次选，不是被删掉的来源。"""
    _reset_marker()
    _clear_refresh_state()
    progress = {
        "runId": f"daily-{TODAY}", "outcome": "completed",
        "finishedAt": "2026-11-28T10:24:30+08:00",
        "done": [{"type": "fund", "updated": 1, "failedBatches": 2, "failedEmpty": 2}],
    }
    orig = ss._refresh_progress
    ss._refresh_progress = lambda run_id=None: copy.deepcopy(progress)  # type: ignore[assignment]
    try:
        st = ss.status()
    finally:
        ss._refresh_progress = orig
    check("③ 无摘要时回落 Web 进度，来源标 web-progress",
          (st.get("lastRefresh") or {}).get("recoveredFromWebProgress") is True
          and st.get("lastRefreshSource") == "web-progress"
          and st.get("lastRefreshFromWebProgress") is True)


def test_run_id_must_match() -> None:
    """摘要的 runId 与本轮不符 ⇒ 不许冒充（跨日、补试轮、上一轮遗留三形）。"""
    _reset_marker()
    _write({"runId": "daily-2000-01-01", "outcome": "partial_failed", "weakTypes": ["hk"]})
    orig = ss._refresh_progress
    ss._refresh_progress = lambda run_id=None: None  # type: ignore[assignment]
    try:
        got = ss._recover_last_refresh()
    finally:
        ss._refresh_progress = orig
    check("④ 跨日摘要不被拿来回填今天", got is None, str(got)[:160])

    _reset_marker(lastAttemptTrigger="daily-retry")
    _write({"runId": f"daily-{TODAY}", "outcome": "completed"})
    orig = ss._refresh_progress
    ss._refresh_progress = lambda run_id=None: None  # type: ignore[assignment]
    try:
        got_retry = ss._recover_last_refresh()
    finally:
        ss._refresh_progress = orig
    check("④b 补试轮不会读成自然轮那份摘要", got_retry is None, str(got_retry)[:160])


def test_natural_round_survives_retry_round() -> None:
    """自然轮与补试轮各占一槽：补试写盘不许盖掉自然轮那份缺口。

    这是"每天最多补一次"这条策略的直接后果：02:30 补试轮会跑第二次刷新腿，
    若两份写同一个键，重启后自然轮的 fund/hk 缺口就再也读不回来了——
    CR10-51 修好的"缺口不被总状态掩盖"会从这个入口复发。
    """
    _reset_marker()
    _clear_refresh_state()
    natural = {"runId": f"daily-{TODAY}", "outcome": "partial_failed", "weakTypes": ["fund", "hk"]}
    retry = {"runId": f"retry-{TODAY}", "outcome": "completed"}
    ss._write_refresh_state(natural)
    ss._write_refresh_state(retry)
    check("⑧ 两轮各存一份，自然轮缺口仍在",
          (ss.read_refresh_state(f"daily-{TODAY}") or {}).get("weakTypes") == ["fund", "hk"])
    check("⑧b 补试轮自己那份也在",
          (ss.read_refresh_state(f"retry-{TODAY}") or {}).get("outcome") == "completed")
    check("⑧c 不带 runId 读回最新一条（补试轮刚写过）",
          (ss.read_refresh_state() or {}).get("runId") == f"retry-{TODAY}")
    orig = ss._refresh_progress
    ss._refresh_progress = lambda run_id=None: None  # type: ignore[assignment]
    try:
        got = ss._recover_last_refresh()
    finally:
        ss._refresh_progress = orig
    check("⑧d 重启恢复仍取自然轮那份（marker 是 daily）",
          (got or {}).get("runId") == f"daily-{TODAY}" and (got or {}).get("weakTypes") == ["fund", "hk"])

    # 同 runId 重跑 ⇒ 替换而不是追加（否则同一个 runId 会读出旧的那次）
    ss._write_refresh_state({"runId": f"daily-{TODAY}", "outcome": "completed"})
    check("⑧e 同 runId 重复写＝替换（以最后一次为准）",
          (ss.read_refresh_state(f"daily-{TODAY}") or {}).get("outcome") == "completed")

    # 轮次上限：写超过 KEEP 份后只留最近几份
    for i in range(ss.REFRESH_STATE_KEEP + 3):
        ss._write_refresh_state({"runId": f"manual-sweep-{i}", "outcome": "completed"})
    kept = (ss._read_refresh_doc().get("runs") or [])
    check("⑧f 摘要文件按 REFRESH_STATE_KEEP 截断（不无限长）",
          len(kept) == ss.REFRESH_STATE_KEEP, f"kept={len(kept)}")


def test_broken_state_is_silent() -> None:
    """摘要损坏／非对象 ⇒ 当没有，不抛、不写、不影响 marker 与 lastRefresh 其它来源。"""
    _reset_marker()
    path = ss._refresh_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ not json")
    check("⑤ 损坏的摘要读回 None（不抛）", ss.read_refresh_state() is None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    check("⑤b 非对象摘要读回 None", ss.read_refresh_state() is None)
    marker_before = ss.read_sync_state()
    orig = ss._refresh_progress
    ss._refresh_progress = lambda run_id=None: None  # type: ignore[assignment]
    try:
        st = ss.status()
    finally:
        ss._refresh_progress = orig
    check("⑤c 摘要坏了不影响 marker 与 status 可用性",
          ss.read_sync_state() == marker_before and st.get("lastRefresh") is None)


def test_write_failure_does_not_change_outcome() -> None:
    """写盘失败只留痕，刷新腿的结论一字不动（观测通道不得拖垮主功能）。"""
    _reset_marker()
    _clear_refresh_state()
    orig_write = ss._write_refresh_state
    orig_base = ss._web_base
    ss._write_refresh_state = lambda refresh: False  # type: ignore[assignment]
    ss._web_base = lambda: "http://127.0.0.1:3000"  # type: ignore[assignment]
    import requests

    orig_post_fn = requests.post
    requests.post = lambda *a, **k: _Resp(_refresh_body())  # type: ignore[assignment]
    try:
        out = ss._refresh_leg("daily")
    finally:
        requests.post = orig_post_fn
        ss._write_refresh_state = orig_write
        ss._web_base = orig_base
    check("⑥ 写盘失败不改变刷新腿结论", out.get("outcome") == "completed" and out.get("runId") == f"daily-{TODAY}")


def test_state_stays_inside_isolated_dir() -> None:
    """隔离是交付物的一部分：两份状态都必须落在 `SYNC_STATE_FILE` 的同级临时目录。"""
    base = os.path.dirname(os.environ["SYNC_STATE_FILE"])
    check("⑦ 摘要在 marker 同级目录（离线单测不写仓库 runtime/）",
          os.path.dirname(ss._refresh_state_path()) == base,
          f"{ss._refresh_state_path()} vs {base}")
    check("⑦b 文件名不与 marker 同名（两份状态不互相覆盖）",
          os.path.basename(ss._refresh_state_path()) != os.path.basename(ss._sync_state_path()))


def main() -> int:
    test_refresh_leg_writes_state()
    test_recover_prefers_disk_and_needs_no_network()
    test_fallback_to_web_when_no_disk_state()
    test_run_id_must_match()
    test_natural_round_survives_retry_round()
    test_broken_state_is_silent()
    test_write_failure_does_not_change_outcome()
    test_state_stays_inside_isolated_dir()
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
