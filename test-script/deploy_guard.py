#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""装载前后只读护栏（零出网、零写入）：冻结基线、前置判定、装载后比对。

它要补的缺口：W1～W4 与 CR10-51 两次装载用的基线脚本住在 `.tmp/baseline.py`（gitignored、
45 行），三个毛病都在真装载夜才暴露：

1. **不入库** ⇒ 换机器／清目录就没了，下次只能现场重写一份"看着差不多"的。
2. **把 `HTTP_PROXY`／`HTTPS_PROXY` 的值原样打进回执** ⇒ 违反装载任务书 §3 第 10 条
   "只判空，不打印值"。代理一旦真的配上（W1 显式代理那一轮），回执本身就是凭据泄漏面。
3. **只读数据库** ⇒ 任务书 §4.3 要的美股 `usSnapshotId`、同步 marker、备份 `trigger/label`、
   各任务 `nextRun`、镜像 ID 与 `StartedAt` 全在库之外，`lastRun=null` 这类读数无法判。

本件把一次性手写脚本变成有牙齿的仪器：**判定与采集分离**——`judge_*`／`compare_baselines`
全是纯函数，离线单测直接喂字典；`collect*` 才碰 Docker 与 SQLite。于是"读不到"这种形状
能在没有容器的机器上验，不必等到装载夜。

用法（三条都不写库、不重启、不改配置）：

    # ① 冻结基线（装载前一次、装载后一次，两份分开留证）
    python test-script/deploy_guard.py baseline --phase before --date 2026-12-01 --out <path>

    # ② 前置十条（目标自然日 D 必须显式给，不猜日期）
    python test-script/deploy_guard.py preflight --date 2026-12-01

    # ③ 装载后比对（拿 before 回执当基线）
    python test-script/deploy_guard.py compare --baseline <before.json> --after <after.json>

    # ④ 只验判定逻辑本身（零子进程、零 Docker、零出网）
    python test-script/deploy_guard.py --selftest

`--phase rehearsal` 是**演练**：只验证仪器能在真环境里跑通，回执不得当窗口证据。
它存在的理由与 `before`／`after` 分开——否则演练回执会被后来的自己误读成"已经冻结过基线"。

退出码：0=判定通过；1=判定不通过（有 fail）；2=读数缺失／仪器读不出（不算通过）；4=参数错误。

**边界（别把它读成"部署自动化了"）**：不 build、不 up、不 restart、不 rollback、不写数据库、
不调同步／热点／备份端点。它只回答"现在能不能切"与"切完有没有被扰动"，切与退仍是人的动作。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
BEIJING = timezone(timedelta(hours=8))

DS_CONTAINER = "invest-manager-data-service-1"
WEB_CONTAINER = "invest-manager-web-1"
DB_PATH_IN_CONTAINER = "/data/dev.db"
BACKUP_DIR_IN_CONTAINER = "/backup"
REFRESH_STATE_IN_CONTAINER = "/data/runtime/sync-refresh-state.json"

#: 同步 marker 的终态。`collecting` **不在**里面——11-28 的病根就是把这个中间态当终态，
#: 于是"总状态停在 collecting"这件事在装载前置里读不出来。
TERMINAL_SYNC_OUTCOMES = ("completed", "partial_failed", "failed", "skipped", "rejected", "inconclusive")

#: 代理类变量：**只判空，永不打印值**（任务书 §3 第 10 条）。`NO_PROXY` 不在此列。
PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")
#: 其余配置变量：只记"是否设置／是否为空／长度"，值本身不回显。
CONFIG_ENV_KEYS = (
    "SCHEDULERS_ENABLED", "SYNC_HOUR", "SYNC_MINUTE", "SYNC_CATCHUP",
    "BACKUP_HOUR", "BACKUP_MINUTE", "SYNC_TYPES", "REFRESH_STATE_KEEP", "BACKUP_STALE_HOURS",
)
#: 值不敏感、且判据需要逐字比对的变量（`SCHEDULERS_ENABLED` 翻转＝"验的不是生产形态"）。
NON_SECRET_EXACT_KEYS = ("SCHEDULERS_ENABLED",)

#: 装载后必须逐字不变的数据库字段。行数变化本身不算失败（刷新腿会写 `updatedAt`），
#: 但 A 股集合摘要变化＝发生过整类替换（W2 那条判据）。
DB_INVARIANT_KEYS = ("integrity", "migrations", "stockCodesSha256", "stockNamesSha256", "hotspotDigest")


# ============================================================ 纯判定（离线可测）


def mask_env(raw: dict) -> dict:
    """把环境读成"是否设置／是否为空／长度"，**绝不回显值**。

    代理为空是装载前置的一项；W1 显式代理那一轮之后这里会变成非空，
    回执仍必须是可安全归档的形状。`SCHEDULERS_ENABLED` 例外：它不是秘密，
    而"装载期间有人把它关了"正是要让比对抓到的形状。
    """
    out: dict = {}
    for key in PROXY_ENV_KEYS:
        value = raw.get(key)
        out[key] = {"present": value is not None, "empty": not (value or "").strip()}
    for key in CONFIG_ENV_KEYS:
        value = raw.get(key)
        if key in NON_SECRET_EXACT_KEYS:
            out[key] = {"present": value is not None, "value": value}
        else:
            out[key] = {"present": value is not None, "empty": not (value or "").strip(),
                        "chars": len(value or "")}
    return out


def judge_proxy_empty(env_masked: dict) -> dict:
    """第 10 条前半：代理必须为空。

    `NO_PROXY` 不算破线——它本身就是"不走代理"的白名单，留着才对。
    未设置与空字符串都算"空"；只有真的带着值才算非空。
    """
    offenders = [k for k in PROXY_ENV_KEYS
                 if env_masked.get(k, {}).get("present")
                 and not env_masked.get(k, {}).get("empty", True)]
    return {
        "ok": not offenders,
        "nonEmptyKeys": offenders,
        "note": "只判空，不回显值" + ("；非空键＝" + ", ".join(offenders) if offenders else ""),
    }


def judge_schedulers_enabled(env_masked: dict) -> dict:
    """第 10 条后半：调度开关未被关掉。未设置按代码默认（开启）处理。"""
    value = env_masked.get("SCHEDULERS_ENABLED", {}).get("value")
    ok = value is None or str(value).strip() in ("1", "true", "True", "yes")
    return {"ok": ok, "value": value,
            "note": "未设置按默认开启；显式 0 视为装载期间关了调度"}


def normalize_next_run(raw, target_day: str) -> dict:
    """把 `nextRun` 归一到"是不是目标日那一档"。

    APScheduler 的 `str(next_run_time)` 形如 `2026-12-01 02:00:00+08:00`；这里只比日期，
    不比字面，免得时区写法差异把正确读数判成错。
    """
    text = str(raw or "").strip()
    if not text:
        return {"ok": False, "raw": raw, "reason": "未取到 nextRun（调度器可能没注册）"}
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})", text)
    if not m:
        return {"ok": False, "raw": raw, "reason": "nextRun 字面不是 YYYY-MM-DD HH:MM 形状"}
    day, hhmm = m.group(1), m.group(2) + ":" + m.group(3)
    return {"ok": day == target_day, "day": day, "time": hhmm, "raw": raw,
            "reason": None if day == target_day else "nextRun 日期 %s ≠ 目标日 %s" % (day, target_day)}


def judge_sync_terminal(sync: dict, target_day: str) -> dict:
    """第 4／7 条：当日 marker 已到终态、且没有待执行补试。

    `lastAttempt` 取自 marker（`/sync/status.lastAttempt` 就是盘上那份），
    读的是**持久化**结论而不是本进程内存。
    """
    attempt = (sync or {}).get("lastAttempt") or {}
    outcome = attempt.get("lastAttemptOutcome")
    day = attempt.get("lastAttemptDate")
    problems = []
    if not attempt:
        problems.append("lastAttempt 为空：当日没有尝试记录")
    else:
        if day != target_day:
            problems.append("lastAttemptDate=%s ≠ %s" % (day, target_day))
        if outcome not in TERMINAL_SYNC_OUTCOMES:
            problems.append("lastAttemptOutcome=%s 不是终态（collecting 不算）" % outcome)
    retry = (sync or {}).get("retry")
    retry_state = retry.get("state") if isinstance(retry, dict) else retry
    if retry_state in ("pending", "running"):
        problems.append("retry.state=%s：当日还有待执行补试" % retry_state)
    if (sync or {}).get("running"):
        problems.append("running=true：同步腿仍在跑")
    return {"ok": not problems, "problems": problems, "outcome": outcome,
            "date": day, "retryState": retry_state}


def judge_us_completed(sync: dict, target_day: str) -> dict:
    """第 5 条：美股当日 `state=completed` 且 `completedDate=当天`。

    这条是"重启不会真的去补跑"的关键：`_resume_us_job_if_due` 在
    `completedDate == 今天` 时直接返回（`us_list_job.py:974`、`sync_scheduler.py:1470`）。
    """
    job = (sync or {}).get("usListJob") or {}
    state, day = job.get("state"), job.get("completedDate")
    problems = []
    if state != "completed":
        problems.append("usListJob.state=%s ≠ completed" % state)
    if day != target_day:
        problems.append("usListJob.completedDate=%s ≠ %s" % (day, target_day))
    return {"ok": not problems, "problems": problems, "state": state,
            "completedDate": day, "snapshotId": job.get("snapshotId")}


def judge_backup_fresh(backup_state: dict, now: datetime, stale_hours: int = 26) -> dict:
    """第 8 条：备份新鲜、非空壳、且是自然备份。

    自然备份只认 `trigger=daily`（任务书 §9 第 2 条）；`startup-catchup` 是补备。
    这里把补备判成"不满足第 8 条"，是因为第 8 条要的是"自然备份在"，
    不是"备份系统还能跑"——后者由补备本身证明，属于另一句话。
    """
    last_run = (backup_state or {}).get("lastRun")
    trigger = (backup_state or {}).get("trigger")
    problems, age_hours = [], None
    if not last_run:
        problems.append("lastRun 为空：没有任何备份记录")
    else:
        try:
            stamp = datetime.fromisoformat(str(last_run))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=BEIJING)
            age_hours = round((now - stamp).total_seconds() / 3600, 2)
            if age_hours > stale_hours:
                problems.append("距上次备份 %sh > %sh（陈旧）" % (age_hours, stale_hours))
            if age_hours < 0:
                problems.append("lastRun 在未来（%s），时钟或状态文件可疑" % last_run)
        except (TypeError, ValueError):
            problems.append("lastRun 无法解析：%s" % last_run)
    if trigger != "daily":
        problems.append("trigger=%s ≠ daily（补备不能冒充自然备份）" % trigger)
    if (backup_state or {}).get("ok") is False:
        problems.append("ok=false：上次备份失败")
    return {"ok": not problems, "problems": problems, "lastRun": last_run,
            "trigger": trigger, "ageHours": age_hours}


def judge_hotspot(hotspot: dict, target_day: str, weekday: int) -> dict:
    """第 6 条：工作日要有当日热点终态；周末只要求不在跑。

    `weekday` 用 `date.weekday()` 语义（周一 0、周六 5、周日 6）。
    周末**不人为制造热点**，所以缺记录不是失败。
    """
    attempt = (hotspot or {}).get("lastAttempt") or {}
    running = bool((hotspot or {}).get("running"))
    if weekday >= 5:
        return {"ok": not running, "mode": "weekend",
                "problems": ["周末热点仍在跑"] if running else [],
                "outcome": attempt.get("lastAttemptOutcome")}
    problems = []
    if not attempt:
        problems.append("工作日没有当日热点尝试记录")
    else:
        if attempt.get("lastAttemptDate") != target_day:
            problems.append("热点 lastAttemptDate=%s ≠ %s"
                            % (attempt.get("lastAttemptDate"), target_day))
        if attempt.get("lastAttemptOutcome") not in TERMINAL_SYNC_OUTCOMES:
            problems.append("热点 outcome=%s 不是终态" % attempt.get("lastAttemptOutcome"))
    if running:
        problems.append("热点仍在跑")
    return {"ok": not problems, "problems": problems, "mode": "weekday",
            "outcome": attempt.get("lastAttemptOutcome")}


def container_snapshot(snapshot: dict, container: str) -> dict:
    """取某个容器的读数。

    采集侧把它们放在 `snapshot["containers"][name]`；比对侧原先直接读顶层键，
    于是**真实回执做自比对都会报"Web 已变"**——夹具用扁平形状，正好把这一形藏住了。
    这里统一按嵌套读，顶层只作旧回执的兼容回落。
    """
    nested = ((snapshot or {}).get("containers") or {}).get(container)
    if isinstance(nested, dict):
        return nested
    top = (snapshot or {}).get(container)
    return top if isinstance(top, dict) else {}


def judge_container_unchanged(before: dict, after: dict, container: str) -> dict:
    """`StartedAt` 是"这个容器被顺手重启过"的硬证据。

    镜像 ID 相同但 `StartedAt` 变了，说明有人重启了它——这一窗就不是"只动了 DS"。
    """
    b = container_snapshot(before, container)
    a = container_snapshot(after, container)
    return {
        "before": {"image": b.get("image"), "startedAt": b.get("startedAt"), "health": b.get("health")},
        "after": {"image": a.get("image"), "startedAt": a.get("startedAt"), "health": a.get("health")},
        "imageSame": b.get("image") is not None and b.get("image") == a.get("image"),
        "startedAtSame": b.get("startedAt") is not None and b.get("startedAt") == a.get("startedAt"),
        "healthy": a.get("health") == "healthy",
    }


def compare_baselines(before: dict, after: dict, target_day: str | None = None) -> dict:
    """装载后比对：抓"整类替换／新 generation／多跑一轮"这三类。

    这里**不把"任何数值变化"一律当失败**，但也不放弃行数判据：装载窗口的前置要求
    下一次同步＝次日 02:00、`runs=0`，所以窗口内本就不该有任何写库动作，六类行数
    必须逐类一致（任务书 §6 第 3 条）。把它当软判据会漏掉"一类减少、另一类增加"
    的互相抵消——那正是整类替换最可能的样子。
    """
    bdb = (before or {}).get("db") or {}
    adb = (after or {}).get("db") or {}
    checks: list[dict] = []

    def ck(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    for key in DB_INVARIANT_KEYS:
        ck("基线不变：%s" % key, bdb.get(key) == adb.get(key),
           "before=%s after=%s" % (bdb.get(key), adb.get(key)))

    bmark = ((before or {}).get("markers") or {}).get("sync") or {}
    amark = ((after or {}).get("markers") or {}).get("sync") or {}
    same_marker = ((bmark.get("lastAttemptDate"), bmark.get("lastAttemptOutcome"), bmark.get("at"))
                   == (amark.get("lastAttemptDate"), amark.get("lastAttemptOutcome"), amark.get("at")))
    ck("同步 marker 未被装载改写", same_marker,
       "before=%s/%s after=%s/%s" % (bmark.get("lastAttemptDate"), bmark.get("lastAttemptOutcome"),
                                     amark.get("lastAttemptDate"), amark.get("lastAttemptOutcome")))

    bus = ((before or {}).get("usListJob") or {}).get("snapshotId")
    aus = ((after or {}).get("usListJob") or {}).get("snapshotId")
    ck("美股无新 generation", bus == aus, "before=%s after=%s" % (bus, aus))

    bfiles = (before or {}).get("backupFiles") or []
    afiles = (after or {}).get("backupFiles") or []
    new_files = sorted(set(afiles) - set(bfiles))
    ck("装载未新增备份文件", not new_files, "新增=%s" % (new_files,))

    # §6 第 7 条后半：`startup-catchup` 补备不是"没有新备份"，而是**启动行为异常**。
    # 两者分开写，否则一份补备回执会以"新备份文件"的身份被当成自然备份。
    abackup = ((after or {}).get("backup") or {})
    ahealth = abackup.get("health") or {}
    astate = abackup.get("state") or {}
    catchup = [label for label, value in (("health.lastRun", ahealth.get("lastRun")),
                                          ("state.lastRun", astate.get("lastRun")))
               if value and value != (((before or {}).get("backup") or {}).get("health") or {}).get("lastRun")
               and value != (((before or {}).get("backup") or {}).get("state") or {}).get("lastRun")]
    new_trigger = astate.get("trigger") if astate.get("trigger") != (((before or {}).get("backup") or {})
                                                                    .get("state") or {}).get("trigger") else None
    startup_suspect = []
    if new_trigger and new_trigger != "daily":
        startup_suspect.append("备份 trigger 变为 %s" % new_trigger)
    ck("装载未触发启动补备", not catchup and not startup_suspect,
       "新备份时刻=%s｜%s" % (catchup, "; ".join(startup_suspect) or "trigger 未变"))

    # §6 第 6 条：热点无新尝试（marker 的日期/结局/时刻三项任一变化都算新尝试）。
    bhot = ((before or {}).get("markers") or {}).get("hotspot") or {}
    ahot = ((after or {}).get("markers") or {}).get("hotspot") or {}
    ck("热点无新尝试",
       (bhot.get("lastAttemptDate"), bhot.get("lastAttemptOutcome"), bhot.get("at"))
       == (ahot.get("lastAttemptDate"), ahot.get("lastAttemptOutcome"), ahot.get("at")),
       "before=%s/%s after=%s/%s" % (bhot.get("lastAttemptDate"), bhot.get("lastAttemptOutcome"),
                                     ahot.get("lastAttemptDate"), ahot.get("lastAttemptOutcome")))

    # §6 第 8 条：`retry` 仍为 null（不能因为装载而清掉或新起一笔补试）。
    bs = (before or {}).get("sync") or {}
    as_ = (after or {}).get("sync") or {}
    ck("retry 未变（仍为 null）",
       json.dumps(bs.get("retry"), sort_keys=True, ensure_ascii=False)
       == json.dumps(as_.get("retry"), sort_keys=True, ensure_ascii=False),
       "before=%s after=%s" % (bs.get("retry"), as_.get("retry")))

    # §6 第 3 条后半：六类行数要逐类比，不能只看总数（一类减一类增会互相抵消）。
    btype = (bdb.get("byType") or {})
    atype = (adb.get("byType") or {})
    ck("六类行数逐类一致", btype == atype,
       "before=%s after=%s" % (json.dumps(btype, ensure_ascii=False, sort_keys=True),
                               json.dumps(atype, ensure_ascii=False, sort_keys=True)))

    bjobs = (before or {}).get("jobs") or {}
    ajobs = (after or {}).get("jobs") or {}
    ck("同步调度时刻未变", bjobs.get("sync") == ajobs.get("sync"),
       "before=%s after=%s" % (bjobs.get("sync"), ajobs.get("sync")))
    ck("备份调度时刻未变", bjobs.get("backup") == ajobs.get("backup"),
       "before=%s after=%s" % (bjobs.get("backup"), ajobs.get("backup")))

    web = judge_container_unchanged(before, after, WEB_CONTAINER)
    ck("Web 镜像与启动时刻未变", web["imageSame"] and web["startedAtSame"],
       "imageSame=%s startedAtSame=%s" % (web["imageSame"], web["startedAtSame"]))

    benv = (before or {}).get("env") or {}
    aenv = (after or {}).get("env") or {}
    proxy = judge_proxy_empty(aenv)
    ck("代理仍为空", proxy["ok"], proxy["note"])
    ck("调度开关未变",
       benv.get("SCHEDULERS_ENABLED", {}).get("value") == aenv.get("SCHEDULERS_ENABLED", {}).get("value"),
       "before=%s after=%s" % (benv.get("SCHEDULERS_ENABLED", {}).get("value"),
                               aenv.get("SCHEDULERS_ENABLED", {}).get("value")))

    # 预期差异：不是失败，但必须被点名，否则回执会显得"什么都没发生"。
    expected = []
    if not web["healthy"]:
        expected.append("Web 装载后未 healthy")
    bimg = container_snapshot(before, DS_CONTAINER).get("image")
    aimg = container_snapshot(after, DS_CONTAINER).get("image")
    if bimg != aimg:
        expected.append("DS 镜像已切换：%s → %s" % (bimg, aimg))

    return {"checks": checks, "expectedDifferences": expected,
            "failed": [c for c in checks if not c["ok"]]}


def preflight(snapshot: dict, target_day: str) -> dict:
    """按装载任务书 §3 十条逐条判，缺读数一律算不通过（不猜、不跳过）。"""
    checks: list[dict] = []

    def ck(idx: int, title: str, ok: bool, detail: str = "") -> None:
        checks.append({"id": idx, "title": title, "ok": bool(ok), "detail": detail})

    read_errors = list((snapshot or {}).get("readErrors") or [])

    git = snapshot.get("git") or {}
    # §3 第 1 条三段：HEAD＝origin/dev、已跟踪工作区干净、无待推提交。
    # 未跟踪的测试产物**不参与判定**（§4.1 明令不得记成代码改动），只写进明细供人看。
    git_ok = (git.get("trackedDirty") == 0
              and git.get("ahead") in (0, None)
              and git.get("behind") in (0, None))
    ck(1, "HEAD＝origin/dev、已跟踪干净、无待推", git_ok,
       "trackedDirty=%s ahead=%s behind=%s 未跟踪=%s sha=%s"
       % (git.get("trackedDirty"), git.get("ahead"), git.get("behind"),
          git.get("untrackedPaths"), git.get("sha")))

    ds = (snapshot.get("containers") or {}).get(DS_CONTAINER) or {}
    web = (snapshot.get("containers") or {}).get(WEB_CONTAINER) or {}
    ck(2, "DS／Web 均 healthy", ds.get("health") == "healthy" and web.get("health") == "healthy",
       "ds=%s web=%s" % (ds.get("health"), web.get("health")))

    sync = snapshot.get("sync") or {}
    ck(3, "同步不在跑、刷新腿未在飞", not sync.get("running"), "running=%s" % sync.get("running"))

    terminal = judge_sync_terminal({"lastAttempt": (snapshot.get("markers") or {}).get("sync"),
                                    "retry": sync.get("retry"), "running": sync.get("running")},
                                   target_day)
    ck(4, "当日 marker 已终态（非 collecting）", terminal["ok"],
       "; ".join(terminal["problems"]) or "%s/%s" % (terminal["date"], terminal["outcome"]))

    us = judge_us_completed({"usListJob": snapshot.get("usListJob")}, target_day)
    ck(5, "美股当日 completed", us["ok"],
       "; ".join(us["problems"]) or "snapshot=%s" % us["snapshotId"])

    try:
        weekday = date.fromisoformat(target_day).weekday()
    except ValueError:
        weekday = 0
    hot = judge_hotspot({"lastAttempt": (snapshot.get("markers") or {}).get("hotspot")}, target_day, weekday)
    ck(6, "热点终态（周末只要求不在跑）", hot["ok"],
       "; ".join(hot["problems"]) or "mode=%s" % hot["mode"])

    retry_state = terminal["retryState"]
    ck(7, "retry 无 pending/running", retry_state not in ("pending", "running"),
       "retry=%s" % retry_state)

    fresh = judge_backup_fresh((snapshot.get("backup") or {}).get("state") or {}, datetime.now(BEIJING))
    ck(8, "备份新鲜且是自然备份", fresh["ok"],
       "; ".join(fresh["problems"]) or "age=%sh" % fresh["ageHours"])

    jobs = snapshot.get("jobs") or {}
    sync_next = normalize_next_run(jobs.get("sync"), target_day)
    backup_next_raw = jobs.get("backup")
    backup_ok = str(backup_next_raw or "").startswith(target_day)
    ck(9, "下一次同步＝%s、备份＝%s" % (target_day, target_day), sync_next["ok"] and backup_ok,
       "sync=%s（%s） backup=%s" % (jobs.get("sync"), sync_next.get("reason") or "ok", backup_next_raw))

    env = snapshot.get("env") or {}
    proxy = judge_proxy_empty(env)
    sched = judge_schedulers_enabled(env)
    env_ok = proxy["ok"] and sched["ok"] and "env" not in read_errors
    ck(10, "代理为空、调度开关未改", env_ok,
       "%s｜SCHEDULERS_ENABLED=%s%s"
       % (proxy["note"], sched["value"], "｜环境读不出" if "env" in read_errors else ""))

    return {
        "targetDate": target_day,
        "collectedAt": (snapshot or {}).get("collectedAt"),
        "checks": checks,
        "readErrors": read_errors,
        "failed": [c for c in checks if not c["ok"]],
        "verdict": "pass" if all(c["ok"] for c in checks) and not read_errors else "stop",
    }


# ============================================================ 采集（碰 Docker／SQLite）


def run(cmd: list, timeout: float = 60.0) -> tuple:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, cwd=str(ROOT))
        return proc.returncode, (proc.stdout or "").strip() or (proc.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001 - 读不到要变成读数，不是崩栈
        return -1, "<%s: %s>" % (type(exc).__name__, exc)


def docker_inspect(container: str) -> dict:
    rc, out = run(["docker", "inspect", container, "--format",
                   "{{.Config.Image}}|{{.State.Health.Status}}|{{.State.StartedAt}}"])
    if rc != 0:
        return {"error": out[:300], "image": None, "health": None, "startedAt": None}
    parts = out.split("|")
    return {"image": parts[0] if len(parts) > 0 else None,
            "health": parts[1] if len(parts) > 1 else None,
            "startedAt": parts[2] if len(parts) > 2 else None}


def container_env(container: str, keys: tuple) -> dict:
    """只把需要的键读回来，不看整份 env（避免顺手把密钥带进回执）。"""
    keys_literal = "[" + ", ".join('"%s"' % k for k in keys) + "]"
    code = ("import json,os;"
            "print(json.dumps({k: os.environ.get(k) for k in " + keys_literal + "}))")
    rc, out = run(["docker", "exec", container, "python", "-c", code])
    if rc != 0:
        return {"_error": out[:300]}
    try:
        loaded = json.loads(out)
    except json.JSONDecodeError:
        return {"_error": "环境读取结果不是 JSON"}
    if not isinstance(loaded, dict):
        return {"_error": "环境读取结果形状不对"}
    return loaded


def ds_get(path: str) -> dict:
    """在 DS 容器内自查本地端点（回环，零上游、零出网）。"""
    code = ("import json,urllib.request;"
            "print(json.dumps(json.load(urllib.request.urlopen("
            "'http://127.0.0.1:8000" + path + "',timeout=10))))")
    rc, out = run(["docker", "exec", DS_CONTAINER, "python", "-c", code], timeout=45)
    if rc != 0:
        return {"_error": out[:400]}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_error": "状态读取结果不是 JSON"}


def read_json_in_container(container: str, path: str) -> dict:
    code = ("import json,pathlib;"
            "p=pathlib.Path(" + repr(path) + ");"
            "print(json.dumps(json.loads(p.read_text()) if p.exists() else {'_absent': True}))")
    rc, out = run(["docker", "exec", container, "python", "-c", code])
    if rc != 0:
        return {"_error": out[:300]}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_error": "状态文件不是 JSON"}


DB_PROBE = """
import hashlib, json, sqlite3
c = sqlite3.connect("file:__DB__?mode=ro", uri=True)
out = {}
by_type = {t: n for t, n in c.execute(
    "SELECT type, COUNT(1) FROM Product GROUP BY type ORDER BY type")}
out["byType"] = by_type
out["productTotal"] = sum(by_type.values())
codes = [r[0] for r in c.execute(
    "SELECT code FROM Product WHERE type='stock' ORDER BY code")]
names = [(r[0], r[1]) for r in c.execute(
    "SELECT code, name FROM Product WHERE type='stock' ORDER BY code")]
out["stockCount"] = len(codes)
out["stockCodesSha256"] = hashlib.sha256("\\n".join(codes).encode()).hexdigest()
out["stockNamesSha256"] = hashlib.sha256(
    "\\n".join(a + "|" + b for a, b in names).encode()).hexdigest()
out["stockNameWithXdDr"] = sum(1 for _, b in names if b and ("XD" in b or "DR" in b))
out["stockNameWithDashUW"] = sum(1 for _, b in names if b and ("-U" in b or "-W" in b))
cols = [r[1] for r in c.execute("PRAGMA table_info(Product)")]
out["pinyinEmpty"] = {}
for col in cols:
    if "pinyin" in col.lower():
        sql = 'SELECT COUNT(1) FROM Product WHERE type=\\'stock\\' AND ("' + col + '" IS NULL OR "' + col + '"=\\'\\')'
        out["pinyinEmpty"][col] = c.execute(sql).fetchone()[0]
out["hotspotDigest"] = c.execute("SELECT COUNT(1) FROM HotspotDigest").fetchone()[0]
out["migrations"] = c.execute(
    "SELECT COUNT(1) FROM _prisma_migrations "
    "WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL").fetchone()[0]
out["integrity"] = c.execute("PRAGMA integrity_check").fetchone()[0]
print(json.dumps(out, ensure_ascii=False))
"""


def db_probe(container: str = DS_CONTAINER) -> dict:
    """只读打开正式库（`mode=ro`；活库在线读不用 `immutable`，那是静态恢复源的写法）。"""
    code = DB_PROBE.replace("__DB__", DB_PATH_IN_CONTAINER)
    rc, out = run(["docker", "exec", container, "python", "-c", code], timeout=180)
    if rc != 0:
        return {"_error": out[:500]}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_error": "数据库读数不是 JSON"}


def list_backup_files(container: str = DS_CONTAINER) -> list:
    code = ("import pathlib;"
            "print('\\n'.join(sorted(p.name for p in pathlib.Path('"
            + BACKUP_DIR_IN_CONTAINER + "').glob('dev-*.db'))))")
    rc, out = run(["docker", "exec", container, "python", "-c", code])
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def refresh_state_probe(container: str = DS_CONTAINER) -> dict:
    """CR10-52 摘要文件在不在。装载前"不在"是预期读数，不是失败。"""
    code = ("import json,pathlib;"
            "p=pathlib.Path('" + REFRESH_STATE_IN_CONTAINER + "');"
            "print(json.dumps({'exists': p.exists(), "
            "'bytes': p.stat().st_size if p.exists() else 0}))")
    rc, out = run(["docker", "exec", container, "python", "-c", code])
    if rc != 0:
        return {"error": out[:200], "exists": None}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"error": "摘要探测结果不是 JSON", "exists": None}


def git_stamp() -> dict:
    """把\"已跟踪改动\"与\"未跟踪产物\"分开数。

    为什么不能只数 `status --porcelain`：本仓库跑完门禁／单测后会留下数百条未跟踪的
    测试产物（`.tmp/**`、`data-service/runtime/**` 等），任务书 §4.1 明确它们**不得记成
    代码改动**。如果护栏拿总条数判\"工作区干净\"，第 1 条会在任何跑过测试的机器上恒红——
    而恒红的判据会逼人删产物去\"凑绿\"，那正是纪律里禁止的动作。
    所以这里分别给出 `trackedDirty`（必须 0）与 `untrackedPaths`（只记录，不判）。
    """
    rc, sha = run(["git", "rev-parse", "HEAD"])
    rc2, all_dirty = run(["git", "status", "--porcelain"])
    rc3, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    rc4, tracked = run(["git", "status", "--porcelain", "--untracked-files=no"])
    rc5, ab = run(["git", "rev-list", "--left-right", "--count", "origin/dev...HEAD"])
    ahead = behind = None
    if rc5 == 0 and ab:
        parts = ab.split()
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            behind, ahead = int(parts[0]), int(parts[1])
    all_lines = [ln for ln in all_dirty.splitlines() if ln.strip()] if rc2 == 0 else []
    tracked_lines = [ln for ln in tracked.splitlines() if ln.strip()] if rc4 == 0 else []
    return {
        "sha": sha.splitlines()[0] if rc == 0 and sha else None,
        "branch": branch.splitlines()[0] if rc3 == 0 else None,
        "trackedDirty": len(tracked_lines),
        "trackedPaths": tracked_lines[:20],
        "untrackedPaths": max(len(all_lines) - len(tracked_lines), 0),
        "allDirtyPaths": len(all_lines),
        "ahead": ahead,
        "behind": behind,
        "origin": "origin/dev",
    }


def parse_jobs_next_run(jobs: list) -> dict:
    """把 `/sync/status.jobs` 收成 `{id: nextRun}`。空清单＝调度器没注册上。"""
    out = {}
    for job in jobs or []:
        if isinstance(job, dict) and job.get("id"):
            out[str(job["id"])] = job.get("nextRun")
    return out


def collect(phase: str, target_day: str | None = None,
            ds_container: str = DS_CONTAINER, web_container: str = WEB_CONTAINER) -> dict:
    """采一份完整读数。`phase` 只影响回执标注，不影响采集内容。"""
    sync = ds_get("/sync/status")
    hotspot = ds_get("/hotspots/status")
    health = ds_get("/health")
    env_raw = container_env(ds_container, PROXY_ENV_KEYS + CONFIG_ENV_KEYS)
    jobs = parse_jobs_next_run(sync.get("jobs") or [])
    backup_health = (health.get("dbBackup") or {}) if isinstance(health, dict) else {}
    backup_state = read_json_in_container(ds_container, BACKUP_DIR_IN_CONTAINER + "/state.json")

    read_errors = []
    if "_error" in sync:
        read_errors.append("sync")
    if "_error" in hotspot:
        read_errors.append("hotspot")
    if "_error" in env_raw:
        read_errors.append("env")
    if "_error" in backup_state:
        read_errors.append("backupState")

    snapshot = {
        "phase": phase,
        "targetDate": target_day,
        "collectedAt": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "readErrors": read_errors,
        "git": git_stamp(),
        "db": db_probe(ds_container),
        "containers": {ds_container: docker_inspect(ds_container),
                       web_container: docker_inspect(web_container)},
        "markers": {"sync": sync.get("lastAttempt") or {},
                    "hotspot": hotspot.get("lastAttempt") or {}},
        "usListJob": sync.get("usListJob") or {},
        "sync": {"running": sync.get("running"),
                 "runs": sync.get("runs"),
                 "retry": sync.get("retry"),
                 "skippedReason": sync.get("skippedReason"),
                 "lastRefreshSource": sync.get("lastRefreshSource"),
                 "lastRefreshOutcome": (sync.get("lastRefresh") or {}).get("outcome"),
                 "weakTypes": (sync.get("lastRefresh") or {}).get("weakTypes")},
        "backup": {"health": backup_health, "state": backup_state},
        "backupFiles": list_backup_files(ds_container),
        "jobs": {"sync": jobs.get("daily-product-sync"),
                 "allSyncJobs": jobs,
                 "backup": (backup_health or {}).get("nextRun"),
                 "backupStaleCheck": (backup_health or {}).get("staleCheckNextRun")},
        "env": mask_env(env_raw),
        "refreshState": refresh_state_probe(ds_container),
    }
    if "_error" in snapshot["db"]:
        read_errors.append("db")
        snapshot["readErrors"] = read_errors
    return snapshot


# ============================================================ 输出


def show_preflight(result: dict) -> None:
    print("\n== 前置十条（目标自然日 %s）==" % result["targetDate"])
    for c in result["checks"]:
        print("  [%s] %2d. %s｜%s" % ("PASS" if c["ok"] else "STOP", c["id"], c["title"], c["detail"]))
    if result["readErrors"]:
        print("\n  读数缺失：%s ⇒ 这些项不能当通过" % ", ".join(result["readErrors"]))
    print("\n  判定：%s%s" % (result["verdict"],
                             "（全部满足，可进入切换）" if result["verdict"] == "pass"
                             else "（%d 条不满足 ⇒ 不动容器）" % len(result["failed"])))


def show_compare(result: dict) -> None:
    print("\n== 装载后比对 ==")
    for c in result["checks"]:
        print("  [%s] %s｜%s" % ("PASS" if c["ok"] else "FAIL", c["name"], c["detail"]))
    if result["expectedDifferences"]:
        print("\n  预期差异（不是失败，但必须点名）：")
        for item in result["expectedDifferences"]:
            print("    - %s" % item)
    print("\n  判定：%s" % ("通过" if not result["failed"]
                           else "%d 条不通过 ⇒ 评估回退" % len(result["failed"])))


# ============================================================ 离线自检


def selftest() -> int:
    """只验判定逻辑：不碰 Docker、不碰库、不出网。"""
    results = []

    def ck(name: str, cond) -> None:
        results.append(bool(cond))
        print("  %s %s" % ("PASS" if cond else "FAIL", name))

    # ① 代理脱敏：值绝不回显，空与非空判别正确
    raw = {"HTTP_PROXY": "", "HTTPS_PROXY": "http://user:pass@10.0.0.1:7890",
           "SCHEDULERS_ENABLED": "1"}
    masked = mask_env(raw)
    blob = json.dumps(masked, ensure_ascii=False)
    ck("代理空串读成 empty", masked["HTTP_PROXY"]["empty"] is True)
    ck("代理非空读成非空", masked["HTTPS_PROXY"]["empty"] is False)
    ck("脱敏结果不含代理主机", "10.0.0.1" not in blob)
    ck("脱敏结果不含凭据", "user:pass" not in blob)
    ck("SCHEDULERS_ENABLED 保留原值（判据要逐字比）", masked["SCHEDULERS_ENABLED"]["value"] == "1")
    # 同一份 mask 里 `HTTPS_PROXY` 是非空的 ⇒ 整体必须判不通过；"全空才通过"另用一份全空样本。
    ck("含非空代理时整体判不通过",
       judge_proxy_empty(masked)["ok"] is False
       and "HTTPS_PROXY" in judge_proxy_empty(masked)["nonEmptyKeys"])
    ck("全空代理判通过（空串与未设都算空）",
       judge_proxy_empty(mask_env({"HTTP_PROXY": "", "HTTPS_PROXY": None}))["ok"] is True)
    ck("NO_PROXY 不算破线",
       judge_proxy_empty(mask_env({"HTTP_PROXY": "", "NO_PROXY": "127.0.0.1"}))["ok"] is True)
    ck("六位代理变量全覆盖（http_proxy 小写也算）",
       judge_proxy_empty(mask_env({"http_proxy": "http://1.2.3.4:1"}))["ok"] is False)
    ck("SCHEDULERS_ENABLED=0 判不通过",
       judge_schedulers_enabled({"SCHEDULERS_ENABLED": {"value": "0"}})["ok"] is False)
    ck("SCHEDULERS_ENABLED 未设按默认开启",
       judge_schedulers_enabled({"SCHEDULERS_ENABLED": {"value": None}})["ok"] is True)

    # ② collecting 不是终态（11-28 的病根）
    collecting = {"lastAttempt": {"lastAttemptDate": "2026-12-01", "lastAttemptOutcome": "collecting"}}
    completed = {"lastAttempt": {"lastAttemptDate": "2026-12-01", "lastAttemptOutcome": "completed"}}
    ck("collecting 判不终态", judge_sync_terminal(collecting, "2026-12-01")["ok"] is False)
    ck("completed 判终态", judge_sync_terminal(completed, "2026-12-01")["ok"] is True)
    ck("跨日 marker 不冒充当日", judge_sync_terminal(
        {"lastAttempt": {"lastAttemptDate": "2026-11-30", "lastAttemptOutcome": "completed"}},
        "2026-12-01")["ok"] is False)
    ck("待执行补试算未清",
       judge_sync_terminal(dict(completed, retry={"state": "pending"}), "2026-12-01")["ok"] is False)
    ck("已完成补试不算未清",
       judge_sync_terminal(dict(completed, retry={"state": "completed"}), "2026-12-01")["ok"] is True)
    ck("空 marker 判不通过而不是默认通过", judge_sync_terminal({}, "2026-12-01")["ok"] is False)
    ck("同步仍在跑判不通过",
       judge_sync_terminal(dict(completed, running=True), "2026-12-01")["ok"] is False)

    # ③ 美股完成判据
    ck("美股当日 completed 判通过", judge_us_completed(
        {"usListJob": {"state": "completed", "completedDate": "2026-12-01"}}, "2026-12-01")["ok"] is True)
    ck("美股跨日完成不算（重启会补跑）", judge_us_completed(
        {"usListJob": {"state": "completed", "completedDate": "2026-11-30"}}, "2026-12-01")["ok"] is False)
    ck("美股 waiting 判不通过", judge_us_completed(
        {"usListJob": {"state": "waiting", "completedDate": None}}, "2026-12-01")["ok"] is False)

    # ④ 备份新鲜度与分账
    now = datetime.fromisoformat("2026-12-01T16:30:00+08:00")
    ck("daily 且 13 小时内判新鲜", judge_backup_fresh(
        {"lastRun": "2026-12-01T03:30:08+08:00", "trigger": "daily", "ok": True}, now)["ok"] is True)
    ck("超过 26 小时判陈旧", judge_backup_fresh(
        {"lastRun": "2026-11-29T03:30:00+08:00", "trigger": "daily", "ok": True}, now)["ok"] is False)
    ck("startup-catchup 不冒充自然备份", judge_backup_fresh(
        {"lastRun": "2026-12-01T15:00:00+08:00", "trigger": "startup-catchup", "ok": True}, now)["ok"] is False)
    ck("lastRun 为空判不通过", judge_backup_fresh({"trigger": "daily"}, now)["ok"] is False)
    ck("未来时刻判可疑", judge_backup_fresh(
        {"lastRun": "2026-12-02T03:30:00+08:00", "trigger": "daily", "ok": True}, now)["ok"] is False)
    ck("ok=false 判不通过", judge_backup_fresh(
        {"lastRun": "2026-12-01T03:30:00+08:00", "trigger": "daily", "ok": False}, now)["ok"] is False)
    ck("无时区 lastRun 按北京时补全", judge_backup_fresh(
        {"lastRun": "2026-12-01T03:30:00", "trigger": "daily", "ok": True}, now)["ageHours"] == 13.0)

    # ⑤ 热点：工作日严格、周末只要求不在跑
    ck("工作日热点终态判通过", judge_hotspot(
        {"lastAttempt": {"lastAttemptDate": "2026-12-01", "lastAttemptOutcome": "completed"}},
        "2026-12-01", 1)["ok"] is True)
    ck("工作日缺热点判不通过", judge_hotspot({}, "2026-12-01", 1)["ok"] is False)
    ck("周末无热点不是失败", judge_hotspot({}, "2026-12-05", 5)["ok"] is True)
    ck("周末热点仍在跑判不通过", judge_hotspot({"running": True}, "2026-12-05", 5)["ok"] is False)

    # ⑥ nextRun 归一：不比字面、只比日期
    ck("nextRun 同日期判通过（不挑格式）",
       normalize_next_run("2026-12-01 02:00:00+08:00", "2026-12-01")["ok"] is True)
    ck("nextRun 换日判不通过",
       normalize_next_run("2026-12-02 02:00:00+08:00", "2026-12-01")["ok"] is False)
    ck("nextRun 为空判不通过（调度器没注册）", normalize_next_run(None, "2026-12-01")["ok"] is False)
    ck("nextRun 非时间字面判不通过",
       normalize_next_run("Select-Object failed", "2026-12-01")["ok"] is False)

    # ⑦ 比对：预期差异不算失败，整类替换算失败
    before = {
        "db": {"integrity": "ok", "migrations": 12, "stockCodesSha256": "aaa",
               "stockNamesSha256": "bbb", "hotspotDigest": 63, "productTotal": 43000,
               "byType": {"fund": 28000, "stock": 5900, "hk": 4700}},
        "markers": {"sync": {"lastAttemptDate": "2026-11-30",
                             "lastAttemptOutcome": "completed", "at": "T1"},
                    "hotspot": {"lastAttemptDate": "2026-11-30",
                                "lastAttemptOutcome": "completed", "at": "H1"}},
        "usListJob": {"snapshotId": "snap-1"},
        "backupFiles": ["dev-20261130-033000.db"],
        "backup": {"health": {"lastRun": "2026-11-30T03:30:00+08:00"},
                   "state": {"lastRun": "2026-11-30T03:30:00+08:00", "trigger": "daily"}},
        "sync": {"retry": None},
        "jobs": {"sync": "2026-12-01 02:00", "backup": "2026-12-01 03:30"},
        "containers": {
            DS_CONTAINER: {"image": "img-old", "startedAt": "T0", "health": "healthy"},
            WEB_CONTAINER: {"image": "web-img", "startedAt": "W0", "health": "healthy"},
        },
        "env": {"SCHEDULERS_ENABLED": {"value": "1"},
                "HTTP_PROXY": {"present": True, "empty": True}},
    }
    after_ok = json.loads(json.dumps(before))
    after_ok["containers"][DS_CONTAINER] = {"image": "img-new", "startedAt": "T9", "health": "healthy"}

    clean = compare_baselines(before, after_ok)
    ck("干净装载：无失败项", not clean["failed"])
    ck("DS 换镜像被记为预期差异",
       any("DS 镜像已切换" in e for e in clean["expectedDifferences"]))
    ck("同一份快照自比对应无失败项（防容器键口径漂移）",
       not compare_baselines(before, json.loads(json.dumps(before)))["failed"])
    ck("扁平旧形状可读（兼容回落）",
       container_snapshot({WEB_CONTAINER: {"image": "x"}}, WEB_CONTAINER).get("image") == "x")

    after_replaced = json.loads(json.dumps(after_ok))
    after_replaced["db"]["stockCodesSha256"] = "changed"
    ck("A 股集合被整类替换 ⇒ 判失败",
       any("stockCodesSha256" in c["name"] for c in compare_baselines(before, after_replaced)["failed"]))

    after_web = json.loads(json.dumps(after_ok))
    after_web["containers"][WEB_CONTAINER]["startedAt"] = "W9"
    ck("Web 被顺手重启 ⇒ 判失败",
       any("Web 镜像与启动时刻未变" in c["name"]
           for c in compare_baselines(before, after_web)["failed"]))

    after_newbak = json.loads(json.dumps(after_ok))
    after_newbak["backupFiles"] = after_newbak["backupFiles"] + ["dev-20261201-160000.db"]
    ck("装载期间冒出新备份 ⇒ 判失败",
       any("新增备份文件" in c["name"]
           for c in compare_baselines(before, after_newbak)["failed"]))

    after_newgen = json.loads(json.dumps(after_ok))
    after_newgen["usListJob"]["snapshotId"] = "snap-2"
    ck("美股出现新 generation ⇒ 判失败",
       any("美股无新 generation" in c["name"]
           for c in compare_baselines(before, after_newgen)["failed"]))

    after_marker = json.loads(json.dumps(after_ok))
    after_marker["markers"]["sync"]["at"] = "T2"
    ck("装载改写同步 marker ⇒ 判失败",
       any("同步 marker 未被装载改写" in c["name"]
           for c in compare_baselines(before, after_marker)["failed"]))

    after_hotspot = json.loads(json.dumps(after_ok))
    after_hotspot["markers"]["hotspot"]["at"] = "H2"
    ck("装载期间热点冒出新尝试 ⇒ 判失败",
       any("热点无新尝试" in c["name"]
           for c in compare_baselines(before, after_hotspot)["failed"]))

    after_catchup = json.loads(json.dumps(after_ok))
    after_catchup["backup"]["state"]["trigger"] = "startup-catchup"
    after_catchup["backup"]["state"]["lastRun"] = "2026-12-01T15:00:00+08:00"
    ck("启动补备被判为启动行为异常（不冒充自然备份）",
       any("启动补备" in c["name"]
           for c in compare_baselines(before, after_catchup)["failed"]))

    after_retry = json.loads(json.dumps(after_ok))
    after_retry["sync"]["retry"] = {"state": "pending"}
    ck("装载后冒出补试计划 ⇒ 判失败",
       any("retry 未变" in c["name"]
           for c in compare_baselines(before, after_retry)["failed"]))

    after_swap = json.loads(json.dumps(after_ok))
    after_swap["db"]["byType"] = {"fund": 28001, "stock": 5899, "hk": 4700}
    after_swap["db"]["productTotal"] = 43000  # 总数不变，但两类互相抵消
    ck("一类减一类增（总数不变）⇒ 仍判失败",
       any("六类行数逐类一致" in c["name"]
           for c in compare_baselines(before, after_swap)["failed"]))

    # ⑧ 前置：读数缺失时不许判通过
    empty_result = preflight({"git": {"trackedDirty": 0}}, "2026-12-01")
    ck("空读数前置判 stop", empty_result["verdict"] == "stop")
    ck("空读数时十条都留下记录", len(empty_result["checks"]) == 10)
    ck("读数缺失进 readErrors", preflight({"readErrors": ["env"]}, "2026-12-01")["verdict"] == "stop")
    ck("环境读不出时第 10 条判不通过",
       [c for c in preflight({"readErrors": ["env"]}, "2026-12-01")["checks"] if c["id"] == 10][0]["ok"] is False)
    ck("环境读不出时不能只看代理列表就绿",
       judge_proxy_empty(mask_env({}))["ok"] is True)  # 单看确实为空 ⇒ 必须靠 readErrors 兜

    # ⑨ git 判据：未跟踪测试产物不判红，待推提交要判红（§4.1 与 §3 第 1 条）
    def git_check(tracked=0, ahead=0, behind=0):
        result = preflight({"git": {"trackedDirty": tracked, "ahead": ahead, "behind": behind,
                                    "untrackedPaths": 662}}, "2026-12-01")
        return [c for c in result["checks"] if c["id"] == 1][0]

    ck("未跟踪 662 条不阻断第 1 条", git_check()["ok"] is True)
    ck("已跟踪有改动 ⇒ 第 1 条判不通过", git_check(tracked=1)["ok"] is False)
    ck("有未推提交 ⇒ 第 1 条判不通过", git_check(ahead=2)["ok"] is False)
    ck("落后 origin/dev ⇒ 第 1 条判不通过", git_check(behind=1)["ok"] is False)
    ck("明细里写明未跟踪数（不隐藏）", "未跟踪=662" in git_check()["detail"])

    passed = sum(1 for ok in results if ok)
    print("===== %d/%d 通过 =====" % (passed, len(results)))
    return 0 if passed == len(results) else 1


# ============================================================ CLI


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selftest", action="store_true", help="只验判定逻辑")
    sub = parser.add_subparsers(dest="cmd")

    p_base = sub.add_parser("baseline", help="冻结只读基线")
    p_base.add_argument("--phase", default="before", choices=["before", "after", "rehearsal"])
    p_base.add_argument("--date", help="目标自然日（只写进回执）")
    p_base.add_argument("--out", type=Path, required=True)

    p_pre = sub.add_parser("preflight", help="按 §3 十条判现在能不能切")
    p_pre.add_argument("--date", required=True, help="目标自然日 YYYY-MM-DD（必须显式给）")

    p_cmp = sub.add_parser("compare", help="装载后比对")
    p_cmp.add_argument("--baseline", type=Path, required=True)
    p_cmp.add_argument("--after", type=Path, required=True)
    p_cmp.add_argument("--date")

    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.cmd == "baseline":
        snapshot = collect(args.phase, args.date)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("回执：%s" % args.out)
        if args.phase == "rehearsal":
            print("⚠ phase=rehearsal：这是仪器演练回执，**不是**装载窗口基线，不得用于 compare")
        if snapshot.get("readErrors"):
            print("⚠ 读数缺失：%s（这份基线不完整，不能当基线用）" % ", ".join(snapshot["readErrors"]))
            return 2
        print("基线完整：Product=%s、完整性=%s、迁移=%s"
              % (snapshot["db"].get("productTotal"), snapshot["db"].get("integrity"),
                 snapshot["db"].get("migrations")))
        return 0

    if args.cmd == "preflight":
        try:
            date.fromisoformat(args.date)
        except ValueError:
            print("--date 不是合法日期：%s" % args.date)
            return 4
        result = preflight(collect("preflight", args.date), args.date)
        show_preflight(result)
        out = ROOT / "data-service" / "runtime" / (
            "deploy-guard-preflight-%s.json" % args.date.replace("-", ""))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("回执：%s" % out)
        return 0 if result["verdict"] == "pass" else 1

    if args.cmd == "compare":
        before = json.loads(args.baseline.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
        for label, snap in (("baseline", before), ("after", after)):
            if (snap or {}).get("phase") == "rehearsal":
                print("拒绝比对：%s 是 phase=rehearsal 的演练回执，不是装载窗口基线" % label)
                return 4
        result = compare_baselines(before, after, args.date)
        show_compare(result)
        return 0 if not result["failed"] else 1

    parser.print_help()
    return 4


if __name__ == "__main__":
    sys.exit(main())
