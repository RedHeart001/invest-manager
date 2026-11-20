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
    check("自然失败是有效终态但不满足要求", watch.requirements_met({"naturalSync": {"outcome": "partial_failed"}, "naturalHotspot": {"outcome": "completed"}, "naturalBackup": {"outcome": "completed"}, "independentRestore": {"passed": True}}) is False)
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


def main():
    test_candidate_accounting()
    test_error_cap_and_immediate_persistence()
    test_restore_uses_static_readonly_source()
    test_output_conflict_and_parser()
    passed = sum(results)
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
