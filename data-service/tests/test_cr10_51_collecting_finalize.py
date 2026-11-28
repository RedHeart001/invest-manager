"""CR10-51 离线单测：`collecting` 终态收尾。

背景（2026-11-28 自然轮）：02:09 五类收尾时美股仍在持久化采集，marker 正确写
`collecting`；02:26 美股发布并刷新完成后没有人回写同步 marker ⇒ `/sync/status`
永久停在 `collecting`，watcher 等不到终态。本套件钉住：

- 同日、daily、原 `collecting`、美股 `completed` 且刷新完成、五类无错误 ⇒ 推进 completed；
- 五类结果与原始尝试时刻原样保留，只替换 us 占位并增加审计字段；
- 重复调用、美股未完成、原轮失败、跨日、写盘竞态 ⇒ 不推进；
- 不生成补试、不产生网络请求、`lastRefresh` 保持独立可见；
- DS 重启后按精确 `runId` 从 Web 持久化进度恢复行情缺口，不把总状态 completed 当全成功；
- 美股完成回调、主轮写 marker 后竞态、启动恢复三个入口都能触发收尾。

运行（零出网、零 SQLite）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr10_51_collecting_finalize.py
"""

import copy
import json
import os
import sys
import tempfile

os.environ["SYNC_STATE_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="cr1051-syncstate-"), "sync-state.json"
)
os.environ["US_LIST_JOB_DIR"] = os.path.join(
    tempfile.mkdtemp(prefix="cr1051-usjob-"), "job"
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import app.sync_scheduler as ss  # noqa: E402
from app import us_list_job  # noqa: E402

TODAY = ss.beijing_today()
MARKER_AT = "2026-11-28T02:09:12+08:00"
US_COMPLETED_AT = "2026-11-28T02:26:39+08:00"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _base_results() -> list[dict]:
    return [
        {"type": "fund", "count": 28452, "tookMs": 2007},
        {"type": "stock", "count": 5931, "tookMs": 305},
        {"type": "bond", "count": 1068, "tookMs": 108},
        {"type": "crypto", "count": 249, "tookMs": 58},
        {"type": "hk", "count": 4754, "tookMs": 256},
        {
            "type": "us",
            "collecting": True,
            "jobState": "collecting",
            "snapshotId": None,
            "progress": {"requiredPages": 923, "resolvedPages": 923},
            "pendingPages": 0,
        },
    ]


def _marker(**over) -> dict:
    marker = {
        "at": MARKER_AT,
        "lastAttemptDate": TODAY,
        "lastAttemptOutcome": "collecting",
        "lastAttemptTrigger": "daily",
        "lastResult": {
            "ok": None,
            "outcome": "collecting",
            "collectingTypes": ["us"],
            "callbackTimeoutS": 2500,
            "tookMs": 552893,
            "tookMsTotal": 552925,
            "results": _base_results(),
        },
    }
    marker.update(over)
    return marker


def _us_status(**over) -> dict:
    status = {
        "state": "completed",
        "refreshOutcome": "completed",
        "completedDate": TODAY,
        "snapshotId": "20261128-020947-222d09",
        "publishedCount": 3343,
        "lastCompletedAt": US_COMPLETED_AT,
    }
    status.update(over)
    return status


def _write(marker: dict) -> None:
    ss._write_marker(copy.deepcopy(marker))


def _read_raw() -> str:
    with open(ss._sync_state_path(), encoding="utf-8") as f:
        return f.read()


def _reset_marker(marker: dict | None = None) -> dict:
    marker = copy.deepcopy(marker or _marker())
    _write(marker)
    with ss._lock:
        ss._state["lastResult"] = copy.deepcopy(marker.get("lastResult"))
        ss._state["lastRefresh"] = {"outcome": "partial_failed", "weakTypes": ["fund", "hk"]}
        ss._state["retryLastResult"] = None
    return marker


def test_finalize_completed() -> None:
    original = _reset_marker()
    before_rows = copy.deepcopy(original["lastResult"]["results"][:5])
    assert ss._finalize_collecting_from_us(_us_status()) is True
    disk = ss.read_sync_state() or {}
    result = disk.get("lastResult") or {}
    rows = result.get("results") or []
    us = next((r for r in rows if r.get("type") == "us"), {})
    check("① 同日 daily collecting + 美股 completed/刷新完成 ⇒ marker completed",
          disk.get("lastAttemptOutcome") == "completed" and result.get("outcome") == "completed"
          and result.get("ok") is True)
    check("① 五类结果逐项原样保留（只替换 us 占位）",
          rows[:5] == before_rows and len(rows) == 6,
          json.dumps(rows[:5], ensure_ascii=False)[:200])
    check("① us 占位替换为真实发布结果",
          us.get("snapshotId") == "20261128-020947-222d09"
          and us.get("count") == 3343 and us.get("jobState") == "completed"
          and us.get("published") is True and us.get("collecting") is None,
          json.dumps(us, ensure_ascii=False)[:200])
    check("① collectingTypes 已移除，审计字段齐全",
          "collectingTypes" not in result
          and result.get("finalizedFrom") == "collecting"
          and result.get("finalizedAt")
          and result.get("usSnapshotId") == "20261128-020947-222d09"
          and result.get("usCompletedAt") == US_COMPLETED_AT)
    check("① 原始尝试时刻、日期、触发形态不变",
          disk.get("at") == MARKER_AT
          and disk.get("lastAttemptDate") == TODAY
          and disk.get("lastAttemptTrigger") == "daily")
    check("① 内存 lastResult 同步推进（status 不再显示 collecting）",
          (ss._state.get("lastResult") or {}).get("outcome") == "completed")
    st = ss.status()
    check("① lastRefresh 独立保留 fund/hk 缺口，不被总状态 completed 掩盖",
          (st.get("lastRefresh") or {}).get("outcome") == "partial_failed"
          and (st.get("lastRefresh") or {}).get("weakTypes") == ["fund", "hk"])
    check("① 收尾不生成补试", (disk.get("retry") is None) and (st.get("retry") is None))


def test_idempotent() -> None:
    _reset_marker()
    assert ss._finalize_collecting_from_us(_us_status()) is True
    before = _read_raw()
    check("② 重复调用返回 False 且不重复写盘",
          ss._finalize_collecting_from_us(_us_status()) is False and _read_raw() == before)


def test_not_completed_states() -> None:
    for state in ("waiting", "refresh_pending", "publish_unknown", "collecting"):
        _reset_marker()
        before = _read_raw()
        ok = ss._finalize_collecting_from_us(_us_status(state=state, refreshOutcome=None))
        check(f"③ 美股 {state} ⇒ 保持 collecting 且不写盘",
              ok is False and _read_raw() == before)


def test_refresh_not_completed() -> None:
    _reset_marker()
    before = _read_raw()
    ok = ss._finalize_collecting_from_us(_us_status(refreshOutcome="partial_failed"))
    check("④ 美股名单 completed 但行情刷新未完成 ⇒ 不推进",
          ok is False and _read_raw() == before)


def test_original_failure_not_overwritten() -> None:
    marker = _marker(lastAttemptOutcome="partial_failed")
    marker["lastResult"]["outcome"] = "partial_failed"
    marker["lastResult"]["failedTypes"] = ["hk"]
    _reset_marker(marker)
    before = _read_raw()
    check("⑤ 原轮 partial_failed 不被美股完成洗白",
          ss._finalize_collecting_from_us(_us_status()) is False and _read_raw() == before)


def test_other_type_error_blocks() -> None:
    marker = _marker()
    marker["lastResult"]["results"][2]["error"] = "bond failed"
    _reset_marker(marker)
    before = _read_raw()
    check("⑤b 五类中任一 error ⇒ 不推进",
          ss._finalize_collecting_from_us(_us_status()) is False and _read_raw() == before)


def test_cross_day() -> None:
    marker = _marker(lastAttemptDate="2000-01-01")
    _reset_marker(marker)
    before = _read_raw()
    check("⑥ 跨日 collecting 不被今天的美股完成改写",
          ss._finalize_collecting_from_us(_us_status()) is False and _read_raw() == before)
    check("⑥b 美股 completedDate 非今天 ⇒ 不推进",
          ss._finalize_collecting_from_us(_us_status(completedDate="2000-01-01")) is False
          and _read_raw() == before)


def test_retry_preserved() -> None:
    retry = {"date": TODAY, "state": "pending", "types": ["hk"], "notBefore": "x"}
    marker = _marker(retry=retry)
    _reset_marker(marker)
    assert ss._finalize_collecting_from_us(_us_status()) is True
    disk = ss.read_sync_state() or {}
    check("⑦ retry 计划原样保留，不被收尾抹掉或新建", disk.get("retry") == retry)


def test_no_network() -> None:
    _reset_marker()
    calls: list[str] = []

    def _boom(*a, **k):
        calls.append(str(a[0]) if a else "?")
        raise AssertionError("finalize 不得发网络请求")

    import requests

    orig_post, orig_get = requests.post, requests.get
    requests.post = _boom  # type: ignore[assignment]
    requests.get = _boom  # type: ignore[assignment]
    try:
        ok = ss._finalize_collecting_from_us(_us_status())
    finally:
        requests.post, requests.get = orig_post, orig_get
    check("⑧ 收尾零网络请求", ok is True and calls == [], str(calls))


def test_us_refresh_callback() -> None:
    _reset_marker()
    us_list_job._patch_state(
        state="refreshing",
        trigger="daily",
        snapshotId="snap-callback",
        completedDate=None,
        refreshOutcome=None,
        publishedCount=3343,
        lastCompletedAt=None,
    )
    us_list_job._refresh_fn = lambda snapshot_id: {"ok": True, "results": [{"type": "us", "failedBatches": 0}]}
    try:
        saved = us_list_job._refresh_once()
    finally:
        us_list_job._refresh_fn = None
    disk = ss.read_sync_state() or {}
    check("⑨ 美股完成回调触发同步收尾",
          saved.get("state") == "completed"
          and (disk.get("lastAttemptOutcome") == "completed")
          and ((disk.get("lastResult") or {}).get("usSnapshotId") == "snap-callback"))


def test_main_round_race() -> None:
    _reset_marker(_marker())
    completed = _us_status()
    collecting = _us_status(state="collecting", refreshOutcome=None, completedDate=None)
    import requests

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "ok": True,
                "tookMs": 100,
                "results": [
                    {"type": "fund", "count": 1},
                    {"type": "stock", "count": 1},
                    {"type": "bond", "count": 1},
                    {"type": "crypto", "count": 1},
                    {"type": "hk", "count": 1},
                ],
            }

    orig_post = requests.post
    orig_ensure = us_list_job.ensure_running
    orig_status = us_list_job.status
    orig_chain = ss._chain_refresh
    requests.post = lambda *a, **k: _Resp()  # type: ignore[assignment]
    us_list_job.ensure_running = lambda *a, **k: {"started": True, "status": dict(collecting)}  # type: ignore[assignment]
    us_list_job.status = lambda: dict(completed)  # type: ignore[assignment]
    ss._chain_refresh = lambda *a, **k: {"outcome": "completed"}  # type: ignore[assignment]
    saved = dict(ss._state)
    try:
        ss._state["running"] = True
        ss._execute("daily")
    finally:
        requests.post = orig_post
        us_list_job.ensure_running = orig_ensure
        us_list_job.status = orig_status
        ss._chain_refresh = orig_chain
        ss._state.clear()
        ss._state.update(saved)
    disk = ss.read_sync_state() or {}
    check("⑩ 主轮写 collecting 后立即复核：美股已在竞态中完成 ⇒ 当场收尾",
          disk.get("lastAttemptOutcome") == "completed"
          and ((disk.get("lastResult") or {}).get("finalizedFrom") == "collecting"))


def test_refresh_recovery_after_restart() -> None:
    marker = _marker(lastAttemptOutcome="completed")
    marker["lastResult"]["outcome"] = "completed"
    _reset_marker(marker)
    with ss._lock:
        ss._state["lastResult"] = None
        ss._state["lastRefresh"] = None
    progress = {
        "runId": f"daily-{TODAY}",
        "outcome": "completed",
        "startedAt": "2026-11-27T18:09:12.938Z",
        "finishedAt": "2026-11-27T18:24:30.819Z",
        "done": [
            {"type": "fund", "updated": 24460, "failedBatches": 2, "failedEmpty": 2},
            {"type": "hk", "updated": 3162, "failedBatches": 10, "failedEmpty": 10},
        ],
    }
    calls: list[str | None] = []
    orig_progress = ss._refresh_progress
    ss._refresh_progress = lambda run_id=None: calls.append(run_id) or copy.deepcopy(progress)  # type: ignore[assignment]
    try:
        st = ss.status()
    finally:
        ss._refresh_progress = orig_progress
    refresh = st.get("lastRefresh") or {}
    check("⑫ DS 重启后按精确 runId 恢复 Web 持久化刷新结果",
          calls == [f"daily-{TODAY}"] and refresh.get("outcome") == "partial_failed"
          and refresh.get("weakTypes") == ["fund", "hk"]
          and refresh.get("recoveredFromWebProgress") is True
          and st.get("lastRefreshFromWebProgress") is True)
    check("⑫ 原始逐类 failedBatches/failedEmpty 不被总状态 completed 吞掉",
          [r.get("failedBatches") for r in refresh.get("results") or []] == [2, 10]
          and [r.get("failedEmpty") for r in refresh.get("results") or []] == [2, 10])

    orig_progress = ss._refresh_progress
    ss._refresh_progress = lambda run_id=None: {**copy.deepcopy(progress), "runId": "daily-2000-01-01"}  # type: ignore[assignment]
    try:
        recovered = ss._recover_last_refresh()
    finally:
        ss._refresh_progress = orig_progress
    check("⑫b runId 不匹配时不拿别轮结果冒充本轮", recovered is None)


def test_startup_hook() -> None:
    _reset_marker()
    called: list[bool] = []
    orig_sleep = ss.time.sleep
    orig_resume = us_list_job.resume_on_startup
    orig_due = ss._resume_us_job_if_due
    orig_finalize = ss._finalize_collecting_from_us
    ss.time.sleep = lambda _s: None  # type: ignore[assignment]
    us_list_job.resume_on_startup = lambda: {"started": False}  # type: ignore[assignment]
    ss._resume_us_job_if_due = lambda: None  # type: ignore[assignment]
    ss._finalize_collecting_from_us = lambda *a, **k: called.append(True) or True  # type: ignore[assignment]
    try:
        ss._resume_us_job_after_start()
    finally:
        ss.time.sleep = orig_sleep
        us_list_job.resume_on_startup = orig_resume
        ss._resume_us_job_if_due = orig_due
        ss._finalize_collecting_from_us = orig_finalize
    check("⑪ DS 启动恢复入口调用收尾检查", called == [True])


def main() -> int:
    test_finalize_completed()
    test_idempotent()
    test_not_completed_states()
    test_refresh_not_completed()
    test_original_failure_not_overwritten()
    test_other_type_error_blocks()
    test_cross_day()
    test_retry_preserved()
    test_no_network()
    test_us_refresh_callback()
    test_main_round_race()
    test_refresh_recovery_after_restart()
    test_startup_hook()
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
