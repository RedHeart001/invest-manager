"""CR10-38 自然窗口监视器离线回归；不访问 Docker、外部源或正式库。"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

PATH = Path(__file__).resolve().parents[2] / "test-script" / "watch-formal-e-natural.py"
SPEC = importlib.util.spec_from_file_location("natural_watch", PATH)
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)
results = []


def check(name, condition):
    results.append(bool(condition))
    print(("OK " if condition else "NG ") + name)


def args_for(tmp, **overrides):
    values = dict(
        target="2026-11-21", observe_only=False, once=False,
        output=Path(tmp) / "state.json", log=Path(tmp) / "events.out",
        backup_dir=Path(tmp) / "backups", restore_volume="invest-e-restore-1121",
        max_consecutive_errors=3,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def natural_sync(outcome="completed"):
    return {"lastAttempt": {"lastAttemptDate": "2026-11-21", "lastAttemptTrigger": "daily", "lastAttemptOutcome": outcome}, "lastResult": {"ok": outcome == "completed"}}


def natural_hotspot(outcome="completed"):
    return {"lastAttempt": {"lastAttemptDate": "2026-11-21", "lastAttemptTrigger": "pre-market", "lastAttemptOutcome": outcome}, "lastResult": {"topics": 2}}


def test_candidate_accounting():
    check("自然 daily 同步可采集", watch.sync_candidate(natural_sync(), "2026-11-21")["outcome"] == "completed")
    check("启动补跑不冒充自然同步", watch.sync_candidate({"lastAttempt": {"lastAttemptDate": "2026-11-21", "lastAttemptTrigger": "startup-catchup", "lastAttemptOutcome": "completed"}}, "2026-11-21") is None)
    check("非目标日不冒充本轮", watch.sync_candidate(natural_sync(), "2026-11-20") is None)
    check("非终态不提前封口", watch.sync_candidate({"lastAttempt": {"lastAttemptDate": "2026-11-21", "lastAttemptTrigger": "daily", "lastAttemptOutcome": "running"}}, "2026-11-21") is None)
    complete = {"naturalSync": {"outcome": "completed"}, "naturalHotspot": {"outcome": "completed"}, "naturalBackup": {"outcome": "completed"}, "independentRestore": {"passed": True}}
    check("自然失败是有效终态但不满足要求", watch.requirements_met({**complete, "naturalSync": {"outcome": "partial_failed"}}, "2026-11-21") is False)
    check("工作日仍要求自然热点", watch.requirements_met(complete, "2026-11-20") is True)
    check("工作日缺热点不得封口", watch.requirements_met({**complete, "naturalHotspot": None}, "2026-11-20") is False)
    check("周六无热点不是失败", watch.hotspot_required("2026-11-21") is False and watch.requirements_met({**complete, "naturalHotspot": None}, "2026-11-21") is True)
    check("周日无热点不是失败", watch.hotspot_required("2026-11-22") is False and watch.requirements_met({**complete, "naturalHotspot": None}, "2026-11-22") is True)
    check("周末仍要求独立恢复", watch.requirements_met({**complete, "naturalHotspot": None, "independentRestore": None}, "2026-11-21") is False)
    check("自然热点与关键词降级分账", watch.hotspot_candidate(natural_hotspot(), "2026-11-21")["trigger"] == "pre-market")
    check("启动热点不计入自然证据", watch.hotspot_candidate({"lastAttempt": {"lastAttemptDate": "2026-11-21", "lastAttemptTrigger": "startup-catchup", "lastAttemptOutcome": "completed"}}, "2026-11-21") is None)


def test_error_cap_and_immediate_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp)
        state = {"targetDate": args.target, "errors": []}
        for _ in range(3):
            watch.record_error(state, "docker denied")
        watch.emit(state, args, "instrument failure persisted")
        saved = json.loads(args.output.read_text(encoding="utf-8"))
        check("仪器错误与重复计数落盘", saved["errors"][0]["repeat"] == 3)
        check("原始错误不被计数替代", "docker denied" in saved["errors"][0]["error"])
        check("每次观测原子写状态且追加日志", args.output.is_file() and "instrument failure persisted" in args.log.read_text(encoding="utf-8"))
        state["consecutiveObservationErrors"] = 3
        with patch.object(watch, "preflight"), patch.object(watch, "observe", side_effect=RuntimeError("denied")), patch.object(watch, "finish", side_effect=lambda state, args, status, note, code: (status, code)):
            result = watch.main(["--date", args.target, "--output", str(args.output), "--log", str(args.log), "--poll-seconds", "0.01"])
        # main 会从已有 unfinished 状态恢复；这里只验证 finish 收到仪器错误。
        check("连续错误形成 instrument-error 非零终态", result == ("instrument-error", 3))


def test_restore_uses_static_readonly_source():
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp, ds_image="image", formal_ds="formal")
        args.backup_dir.mkdir()
        (args.backup_dir / "dev-20261121-033000.db").write_bytes(b"static fixture")
        calls = []
        def fake_run(command, timeout=120):
            calls.append(command)
            if command[:3] == ["docker", "volume", "ls"]:
                return ""
            if command[:2] == ["docker", "run"] and "-c" in command:
                return json.dumps({"integrity": "ok", "tables": {table: 1 for table in watch.TABLES}, "migrations": 12})
            return ""
        with patch.object(watch, "run", side_effect=fake_run), patch.object(watch.sqlite3, "connect") as connect:
            connection = connect.return_value.__enter__.return_value
            connection.execute.return_value.fetchone.side_effect = lambda: ["ok"]
            # 用真实 inspect_db 的形状桩，避免为命令测试建立业务库。
            with patch.object(watch, "inspect_db", return_value={"integrity": "ok", "tables": {table: 1 for table in watch.TABLES}, "migrations": 12}), patch.object(watch.hashlib, "sha256") as sha:
                sha.return_value.hexdigest.return_value = "abc"
                with patch.object(watch.Path, "is_file", return_value=True):
                    watch.restore_backup("dev-20261121-033000.db", args)
        restore = next(command for command in calls if "--restore" in command)
        check("恢复源直接只读挂载", f"{args.backup_dir}:/backup:ro" in restore)
        check("恢复只写新建独立卷", f"{args.restore_volume}:/data" in restore and "--source" in restore)
        check("不生成可写备份副本", not any("copy" in " ".join(map(str, command)).lower() for command in calls))


def test_output_conflict_and_parser():
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp)
        args.output.write_text(json.dumps({"targetDate": "2026-11-20"}), encoding="utf-8")
        try:
            watch.load_state(args)
            loaded = True
        except RuntimeError:
            loaded = False
        check("目标日不符拒绝续写旧回执", not loaded)
        args.output.write_text(json.dumps({"targetDate": args.target, "finishedAt": "done"}), encoding="utf-8")
        try:
            watch.load_state(args)
            loaded = True
        except RuntimeError:
            loaded = False
        check("已完成回执拒绝覆盖", not loaded)
    parsed = watch.parse_args(["--date", "2026-11-21", "--max-consecutive-errors", "3"])
    check("独立输出路径与恢复卷按日隔离", parsed.output.name.endswith("20261121.json") and parsed.restore_volume == "invest-e-restore-1121")


# ---------- CR10-52（2026-11-28 P2）：`collecting` 收尾与本轮刷新的取证齿 ----------


def _sync_with_refresh(outcome="collecting", refresh=None, day="2026-11-21"):
    body = {
        "lastAttempt": {"lastAttemptDate": day, "lastAttemptTrigger": "daily", "lastAttemptOutcome": outcome},
        "lastResult": {"ok": None, "outcome": outcome},
    }
    if refresh is not None:
        body["lastRefresh"] = refresh
    return body


def test_collecting_is_not_terminal():
    """`collecting` 不是失败，但也不是终态——watcher 不许提前封口，也不许把它记成 outcome。

    11-28 的病就在这儿：五类收尾、美股仍在采集时 marker 写 `collecting`；若监督器把
    它当终态，`naturalSync` 会被封成 `collecting` 且 `requirements_met()` 永远为假，
    事后读起来像是"本轮跑了却没过"，而真相是"本轮还没收尾"。
    """
    check("collecting 不进终态名单", "collecting" not in watch.TERMINAL)
    check("collecting 期间不封存 naturalSync", watch.sync_candidate(_sync_with_refresh("collecting"), "2026-11-21") is None)


def test_completed_after_collecting_is_sealed():
    """美股完成后同一日推进到 `completed` ⇒ 此时才封存，且封的是最终结局。"""
    candidate = watch.sync_candidate(_sync_with_refresh("completed"), "2026-11-21")
    check("collecting → completed 后可封存", candidate is not None and candidate["outcome"] == "completed")


def test_refresh_backfilled_without_overwriting_outcome():
    """名单终态先到、刷新腿后收尾 ⇒ 只补 `lastRefresh`，不改已封存的 outcome/results。

    这是 11-28 之后补的那条路：刷新腿要跑约 40 分钟，watcher 常在名单终态那一刻就
    拿到 `completed`，若只封一次就再也不看，`lastRefresh` 会永久是 None——
    fund/hk 的部分失败就此从回执里消失。
    """
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp)
        args.backup_dir.mkdir()
        state = watch.build_state(args)
        # 第一拍：名单终态到了，刷新腿还没写完
        sync1 = _sync_with_refresh("completed", refresh=None)
        hotspot1 = natural_hotspot()
        backup1 = {"trigger": "daily", "outcome": "completed", "lastRun": "2026-11-21T03:30:00+08:00", "ok": True}
        with patch.object(watch, "ds_get", side_effect=lambda path, _a: sync1 if path == "/sync/status" else hotspot1), \
             patch.object(watch, "disk_state", return_value=backup1):
            watch.observe(state, args)
        sealed_outcome = (state.get("naturalSync") or {}).get("outcome")
        check("补记前：名单终态已封存、lastRefresh 仍为 None",
              sealed_outcome == "completed" and (state.get("naturalSync") or {}).get("lastRefresh") is None)
        # 第二拍：刷新腿收尾，带出 fund/hk 缺口
        refresh = {"runId": "daily-2026-11-21", "outcome": "partial_failed", "weakTypes": ["fund", "hk"]}
        sync2 = _sync_with_refresh("completed", refresh=refresh)
        with patch.object(watch, "ds_get", side_effect=lambda path, _a: sync2 if path == "/sync/status" else hotspot1), \
             patch.object(watch, "disk_state", return_value=backup1):
            watch.observe(state, args)
        got = state.get("naturalSync") or {}
        check("补记后：lastRefresh 补上且带 fund/hk 缺口",
              (got.get("lastRefresh") or {}).get("weakTypes") == ["fund", "hk"])
        check("补记不动已封存的 outcome（两件事各记各的）", got.get("outcome") == "completed")
        check("补记留下观测时刻（分得清哪一拍看到的）", bool(got.get("lastRefreshObservedAt")))
        check("补记不把本轮写成全过（缺口在，requirements 仍为假）",
              watch.requirements_met(state, args.target) is False)


def test_previous_round_refresh_not_reused():
    """上一轮的 `lastRefresh` 不许冒充本轮——判据是 `runId`，没有就退回 `finishedAt`。

    进程跨日不重启时 `_state["lastRefresh"]` 会一直挂着昨天的值；照抄它就等于
    把昨天的行情缺口写进今天的回执（或反过来把昨天的问题today 洗成绿的）。
    """
    check("runId 是本轮 ⇒ 采用",
          watch.refresh_for_target(_sync_with_refresh("completed", {"runId": "daily-2026-11-21"}), "2026-11-21") is not None)
    check("runId 是上一轮 ⇒ 拒绝",
          watch.refresh_for_target(_sync_with_refresh("completed", {"runId": "daily-2026-11-20"}), "2026-11-21") is None)
    check("无 runId 但 finishedAt 落在目标日 ⇒ 采用（旧形状兼容）",
          watch.refresh_for_target(_sync_with_refresh("completed", {"finishedAt": "2026-11-21T10:00:00+08:00"}), "2026-11-21") is not None)
    check("无 runId 且 finishedAt 不在目标日 ⇒ 拒绝",
          watch.refresh_for_target(_sync_with_refresh("completed", {"finishedAt": "2026-11-20T10:00:00+08:00"}), "2026-11-21") is None)
    check("两者都没有 ⇒ 当未知，不猜",
          watch.refresh_for_target(_sync_with_refresh("completed", {"outcome": "completed"}), "2026-11-21") is None)


def test_persisted_result_is_enough_without_watcher():
    """watcher 没运行时，持久化结果本身必须足以判读——这是 CR10-52 降级取证的前提。

    `observe()` 只吃 `/sync/status` + `/backup/state.json` 两份持久化读数，
    不要求 watcher 先跑过、也不要求任何本地进程状态。这条钉住"事后取证"这条路
    在代码层面真的成立，而不是只有文档里写了。
    """
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(tmp, target="2026-11-23")
        args.backup_dir.mkdir()
        (args.backup_dir / "dev-20261123-033000.db").write_bytes(b"db")
        state = watch.build_state(args)
        sync = _sync_with_refresh("completed", {"runId": "daily-2026-11-23", "outcome": "completed"}, day="2026-11-23")
        hotspot = {
            "lastAttempt": {"lastAttemptDate": "2026-11-23", "lastAttemptTrigger": "pre-market", "lastAttemptOutcome": "completed"},
            "lastResult": {"topics": 2},
        }
        backup = {"trigger": "daily", "outcome": "completed", "lastRun": "2026-11-23T03:30:00+08:00", "ok": True}
        with patch.object(watch, "ds_get", side_effect=lambda path, _a: sync if path == "/sync/status" else hotspot), \
             patch.object(watch, "disk_state", return_value=backup), \
             patch.object(watch, "restore_backup", return_value={"passed": True}):
            watch.observe(state, args)
        check("无 watcher 历史也能从持久化读数封存本轮",
              (state.get("naturalSync") or {}).get("outcome") == "completed")
        check("同一份持久化读数也能封存备份与恢复",
              (state.get("naturalBackup") or {}).get("outcome") == "completed"
              and (state.get("independentRestore") or {}).get("passed") is True)
        check("三条腿齐了才判满足", watch.requirements_met(state, args.target) is True)


def main():
    test_candidate_accounting()
    test_error_cap_and_immediate_persistence()
    test_restore_uses_static_readonly_source()
    test_output_conflict_and_parser()
    test_collecting_is_not_terminal()
    test_completed_after_collecting_is_sealed()
    test_refresh_backfilled_without_overwriting_outcome()
    test_previous_round_refresh_not_reused()
    test_persisted_result_is_enough_without_watcher()
    passed = sum(results)
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
