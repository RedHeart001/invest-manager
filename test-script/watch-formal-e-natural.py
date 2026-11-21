#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""只读取证正式实例的自然窗口；备份只恢复到新建的独立卷。

用法（先做一次有界探测，再决定是否跨夜守候）：
    python test-script/watch-formal-e-natural.py --date 2026-11-21 --once
    python test-script/watch-formal-e-natural.py --date 2026-11-21

退出码：0=自然判据全满足；2=自然终态已齐但未满足/超时；3=仪器读取失败；
4=参数或输出冲突；130=人工中断。observe-only 不恢复、不写状态文件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
TERMINAL = {"completed", "partial_failed", "failed", "skipped", "rejected", "inconclusive"}
NATURAL_HOTSPOT_TRIGGERS = {"pre-market", "post-market", "daily"}
BACKUP_NAME = re.compile(r"^dev-(\d{8})-(\d{6})\.db$")
TABLES = ["Product", "HotspotDigest", "ResearchReport", "ChatSession", "ChatMessage", "Watchlist", "KlineDaily"]
MAX_ERRORS = 50


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="目标自然日；默认 02:00 前为当天，否则为下一天")
    parser.add_argument("--once", action="store_true", help="有界观测一次，不写库；默认仍写状态")
    parser.add_argument("--observe-only", action="store_true", help="只观测，不写状态、不恢复")
    parser.add_argument("--max-hours", type=float, default=12.0)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-consecutive-errors", type=int, default=3)
    parser.add_argument("--output", type=Path, help="独立状态 JSON；默认按目标日命名")
    parser.add_argument("--log", type=Path, help="独立事件日志；默认按目标日命名")
    parser.add_argument("--backup-dir", type=Path, default=ROOT / "backups")
    parser.add_argument("--ds-image", default="invest-manager-data-service:local")
    parser.add_argument("--formal-ds", default="invest-manager-data-service-1")
    args = parser.parse_args(argv)
    target = args.date or default_target_date().isoformat()
    try:
        date.fromisoformat(target)
    except ValueError as exc:
        parser.error(str(exc))
    args.target = target
    default = ROOT / "data-service" / "runtime" / f"formal-e-natural-watch-{target.replace('-', '')}"
    args.output = (args.output or default.with_suffix(".json")).resolve()
    args.log = (args.log or default.with_suffix(".out")).resolve()
    args.backup_dir = args.backup_dir.resolve()
    args.restore_volume = f"invest-e-restore-{target[5:7]}{target[8:10]}"
    if args.max_hours <= 0 or args.poll_seconds <= 0 or args.max_consecutive_errors <= 0:
        parser.error("max-hours、poll-seconds、max-consecutive-errors 必须为正数")
    return args


def default_target_date():
    now = datetime.now(TZ)
    return now.date() if now.time() < dtime(2, 0) else now.date() + timedelta(days=1)


def run(args, timeout=120):
    result = subprocess.run(
        args, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=True, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {args[:3]}\n"
            f"{result.stdout[-500:]}{result.stderr[-1000:]}"
        )
    return result.stdout.strip()


def ds_get(path, args):
    code = (
        "import json,urllib.request;"
        f"print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000{path}',timeout=20))))"
    )
    return json.loads(run(["docker", "exec", args.formal_ds, "python", "-c", code], timeout=35))


def disk_state(path, args):
    code = f"import json,pathlib;p=pathlib.Path('{path}');print(json.dumps(json.loads(p.read_text()) if p.exists() else {{}}))"
    return json.loads(run(["docker", "exec", args.formal_ds, "python", "-c", code], timeout=35))


def preflight(args):
    run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=20)
    run(["docker", "inspect", args.formal_ds, "--format", "{{.State.Health.Status}}"], timeout=20)
    ds_get("/sync/status", args)
    ds_get("/hotspots/status", args)
    disk_state("/backup/state.json", args)


def sync_candidate(sync, target):
    attempt = sync.get("lastAttempt") or {}
    if attempt.get("lastAttemptDate") != target or attempt.get("lastAttemptTrigger") != "daily":
        return None
    if attempt.get("lastAttemptOutcome") not in TERMINAL:
        return None
    result = sync.get("lastResult") or {}
    return {
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "attemptAt": attempt.get("at") or attempt.get("lastAttemptAt"),
        "trigger": attempt.get("lastAttemptTrigger"),
        "outcome": attempt.get("lastAttemptOutcome"),
        "lastAttemptDate": target,
        "ok": result.get("ok"),
        "failedTypes": result.get("failedTypes"),
        "error": result.get("error"),
        "results": [{k: row.get(k) for k in ["type", "count", "skipped", "outcome", "error"]} for row in result.get("results") or []],
        "lastRefresh": result.get("lastRefresh"),
        "jobs": sync.get("jobs"),
    }


def hotspot_candidate(hotspot, target):
    attempt = hotspot.get("lastAttempt") or {}
    if attempt.get("lastAttemptDate") != target or attempt.get("lastAttemptTrigger") not in NATURAL_HOTSPOT_TRIGGERS:
        return None
    if attempt.get("lastAttemptOutcome") not in TERMINAL:
        return None
    result = hotspot.get("lastResult") or {}
    return {
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "attemptAt": attempt.get("lastAttemptAt"),
        "trigger": attempt.get("lastAttemptTrigger"),
        "outcome": attempt.get("lastAttemptOutcome"),
        "lastAttemptDate": target,
        "topics": result.get("topics"),
        "ingested": result.get("ingested"),
        "degraded": result.get("degraded"),
        "engine": result.get("engine"),
        "newsSources": result.get("newsSources"),
        "jobs": hotspot.get("jobs"),
    }


def find_backup_file(target, last_run, backup_dir):
    try:
        finish = datetime.fromisoformat(str(last_run))
    except (TypeError, ValueError):
        return None
    if finish.tzinfo is None:
        finish = finish.replace(tzinfo=TZ)
    if finish.date().isoformat() != target:
        return None
    best = None
    for path in backup_dir.glob(f"dev-{target.replace('-', '')}-*.db"):
        match = BACKUP_NAME.match(path.name)
        if not match:
            continue
        try:
            started = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=TZ)
        except ValueError:
            continue
        delta = (finish - started).total_seconds()
        if -5 <= delta <= 600 and (best is None or started > best[0]):
            best = (started, path)
    return best[1] if best else None


def backup_candidate(backup, target, backup_dir):
    if backup.get("trigger") != "daily" or backup.get("outcome") not in TERMINAL:
        return None
    path = find_backup_file(target, backup.get("lastRun"), backup_dir)
    if not path and not str(backup.get("lastRun", "")).startswith(target):
        return None
    return {
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "lastRun": backup.get("lastRun"),
        "trigger": backup.get("trigger"),
        "outcome": backup.get("outcome"),
        "ok": backup.get("ok"),
        "kept": backup.get("kept"),
        "backupFile": path.name if path else None,
        "fileExists": bool(path),
        "fileSize": path.stat().st_size if path else None,
    }


def inspect_db(connection):
    return {
        "integrity": connection.execute("pragma integrity_check").fetchone()[0],
        "tables": {table: connection.execute(f'select count(*) from "{table}"').fetchone()[0] for table in TABLES},
        "migrations": connection.execute("select count(*) from _prisma_migrations where finished_at is not null and rolled_back_at is null").fetchone()[0],
    }


def restore_backup(name, args):
    volumes = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines()
    if args.restore_volume in volumes:
        raise RuntimeError(f"restore volume already exists: {args.restore_volume}")
    source = (args.backup_dir / name).resolve()
    if source.parent != args.backup_dir or not source.is_file():
        raise RuntimeError("backup source is missing or outside backup-dir")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro&immutable=1", uri=True) as connection:
        source_view = inspect_db(connection)
    run(["docker", "volume", "create", args.restore_volume])
    run([
        "docker", "run", "--rm", "-v", f"{args.restore_volume}:/data",
        "-v", f"{args.backup_dir}:/backup:ro", "--entrypoint", "python", args.ds_image,
        "-m", "scripts.backup_db", "--restore", f"/backup/{name}", "--source", "/data/dev.db",
    ], timeout=300)
    code = "import json,sqlite3;c=sqlite3.connect('file:/data/dev.db?mode=ro',uri=True);tables=" + repr(TABLES) + ";print(json.dumps({'integrity':c.execute('pragma integrity_check').fetchone()[0],'tables':{t:c.execute('select count(*) from \\\"'+t+'\\\"').fetchone()[0] for t in tables},'migrations':c.execute('select count(*) from _prisma_migrations where finished_at is not null and rolled_back_at is null').fetchone()[0]}))"
    restored = json.loads(run([
        "docker", "run", "--rm", "-v", f"{args.restore_volume}:/data",
        "--entrypoint", "python", args.ds_image, "-c", code,
    ], timeout=120))
    if restored != source_view or restored["integrity"] != "ok" or restored["tables"]["Product"] <= 0:
        raise RuntimeError("independent restore content mismatch")
    return {
        "volume": args.restore_volume, "backupFile": name, "sha256": digest,
        "sourceAndRestored": restored, "passed": True,
        "volumeRetainedForCleanupConfirmation": True,
    }


def load_state(args):
    if not args.output.exists():
        return None
    previous = json.loads(args.output.read_text(encoding="utf-8"))
    if previous.get("targetDate") != args.target:
        raise RuntimeError("output belongs to another target date; refusing to append")
    if previous.get("finishedAt"):
        raise RuntimeError("output is already finished; use a new output path")
    return previous


def build_state(args):
    now = datetime.now(timezone.utc).isoformat()
    previous = load_state(args)
    if previous:
        previous["monitorRuns"] = list(previous.get("monitorRuns") or []) + [{"at": now, "event": "resumed", "pid": os.getpid()}]
        return previous
    return {
        "startedAt": now, "targetDate": args.target, "formalProject": "invest-manager",
        "restoreVolume": args.restore_volume, "naturalSync": None, "naturalHotspot": None,
        "naturalBackup": None, "independentRestore": None, "allRequirementsMet": None,
        "instrumentStatus": "starting", "consecutiveObservationErrors": 0,
        "errors": [], "errorsDropped": 0,
        "monitorRuns": [{"at": now, "event": "started", "pid": os.getpid()}], "finishedAt": None,
    }


def emit(state, args, note):
    state["lastObservationAt"] = datetime.now(timezone.utc).isoformat()
    state["lastNote"] = note
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(args.output)
    with args.log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": state["lastObservationAt"], "note": note}, ensure_ascii=False) + "\n")


def record_error(state, message):
    errors = state.setdefault("errors", [])
    item = str(message)[:500]
    now = datetime.now(timezone.utc).isoformat()
    if errors and errors[-1].get("error") == item:
        errors[-1]["repeat"] = int(errors[-1].get("repeat", 1)) + 1
        errors[-1]["lastAt"] = now
    else:
        errors.append({"at": now, "error": item})
    while len(errors) > MAX_ERRORS:
        errors.pop(0)
        state["errorsDropped"] = int(state.get("errorsDropped", 0)) + 1


def hotspot_required(target):
    """热点调度仅在工作日运行；周末无窗口不是业务失败或仪器缺测。"""
    return date.fromisoformat(target).weekday() < 5


def required_windows(target):
    return ["naturalSync", "naturalBackup"] + (["naturalHotspot"] if hotspot_required(target) else [])


def requirements_met(state, target):
    windows = required_windows(target)
    if any(state.get(key) is None for key in windows):
        return False
    return all(state[key].get("outcome") == "completed" for key in windows) and bool((state.get("independentRestore") or {}).get("passed"))


def finish(state, args, status, note, code):
    state["allRequirementsMet"] = status == "finished"
    state["finishedAt"] = datetime.now(timezone.utc).isoformat()
    if not args.observe_only:
        emit(state, args, note)
    print(json.dumps({"status": status, "targetDate": args.target, "allRequirementsMet": state["allRequirementsMet"]}, ensure_ascii=False))
    return code


def observe(state, args):
    sync = ds_get("/sync/status", args)
    hotspot = ds_get("/hotspots/status", args)
    backup = disk_state("/backup/state.json", args)
    candidate = sync_candidate(sync, args.target)
    if state.get("naturalSync") is None and candidate:
        state["naturalSync"] = candidate
    candidate = hotspot_candidate(hotspot, args.target)
    if state.get("naturalHotspot") is None and candidate:
        state["naturalHotspot"] = candidate
    candidate = backup_candidate(backup, args.target, args.backup_dir)
    if state.get("naturalBackup") is None and candidate:
        state["naturalBackup"] = candidate
        if candidate["outcome"] == "completed" and not args.observe_only:
            if not candidate["fileExists"]:
                state["naturalBackup"]["fileMissing"] = True
            elif state.get("independentRestore") is None:
                state["independentRestore"] = restore_backup(candidate["backupFile"], args)
    state["consecutiveObservationErrors"] = 0
    state["instrumentStatus"] = "ok"


def main(argv=None):
    args = parse_args(argv)
    state = build_state(args)
    if not args.observe_only:
        emit(state, args, f"watcher started; target natural date {args.target}")
    try:
        preflight(args)
    except Exception as exc:  # noqa: BLE001 仪器失败必须形成有界终态
        state["instrumentStatus"] = "failed"
        state["consecutiveObservationErrors"] = 1
        record_error(state, f"preflight failed: {exc}")
        return finish(state, args, "instrument-error", "preflight failed; no natural result inferred", 3)
    state["instrumentStatus"] = "ok"
    if not args.observe_only:
        emit(state, args, "preflight passed")
    deadline = time.monotonic() + args.max_hours * 3600
    while True:
        try:
            observe(state, args)
            if not args.observe_only:
                emit(state, args, "observation persisted")
            if requirements_met(state, args.target):
                return finish(state, args, "finished", "all target natural requirements met", 0)
            if all(state.get(key) is not None for key in required_windows(args.target)):
                return finish(state, args, "finished-not-met", "all due natural terminal states captured; requirements not met", 2)
            if time.monotonic() >= deadline:
                return finish(state, args, "deadline", "deadline reached without all target windows", 2)
        except KeyboardInterrupt:
            if not args.observe_only:
                emit(state, args, "watcher interrupted by operator")
            return 130
        except Exception as exc:  # noqa: BLE001
            state["consecutiveObservationErrors"] = int(state.get("consecutiveObservationErrors", 0)) + 1
            state["instrumentStatus"] = "degraded"
            record_error(state, exc)
            if not args.observe_only:
                emit(state, args, "observation error; bounded retry")
            if state["consecutiveObservationErrors"] >= args.max_consecutive_errors:
                state["instrumentStatus"] = "failed"
                return finish(state, args, "instrument-error", "consecutive observation error limit reached; no natural result inferred", 3)
        if args.once or args.observe_only:
            print(json.dumps({
                "status": "observed", "targetDate": args.target,
                "sync": state.get("naturalSync"), "hotspot": state.get("naturalHotspot"),
                "backup": state.get("naturalBackup"), "restore": state.get("independentRestore"),
                "instrumentStatus": state.get("instrumentStatus"),
                "errors": state.get("errors", [])[-3:],
            }, ensure_ascii=False, indent=2))
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
