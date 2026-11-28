"""CR10-52 装载护栏离线回归（`test-script/deploy_guard.py`）。

不访问 Docker、数据库、外部源或正式容器：全部喂字典。

为什么这份套件必须存在：装载护栏本身是"判断能不能切／切完有没有被扰动"的仪器。
它一旦常绿（读不到就当通过、缺读数就默认满足），装载夜会得到一份看起来全绿、
实际什么都没验的回执——这正是 11-28 `collecting` 被当终态那一形在部署侧的翻版。
所以每条判据都要有**反向样本**：把输入改成该失败的样子，断言它真的红。

运行（零出网、零 Docker）：
    python data-service/tests/test_cr10_52_deploy_guard.py
"""

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PATH = Path(__file__).resolve().parents[2] / "test-script" / "deploy_guard.py"
SPEC = importlib.util.spec_from_file_location("deploy_guard", PATH)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

DS = guard.DS_CONTAINER
WEB = guard.WEB_CONTAINER
TARGET = "2026-12-01"
results: list[tuple[str, bool]] = []


def check(name: str, condition) -> None:
    results.append((name, bool(condition)))
    print(("OK " if condition else "NG ") + name)


def test_proxy_masking_never_leaks_values():
    """代理只判空：回执里不许出现值本身。"""
    raw = {"HTTP_PROXY": "", "HTTPS_PROXY": "http://user:pass@10.0.0.1:7890",
           "http_proxy": "http://2.2.2.2:1", "SCHEDULERS_ENABLED": "1"}
    masked = guard.mask_env(raw)
    blob = json.dumps(masked, ensure_ascii=False)
    check("凭据不进回执", "user:pass" not in blob)
    check("代理主机不进回执", "10.0.0.1" not in blob and "2.2.2.2" not in blob)
    check("空代理读成 empty", masked["HTTP_PROXY"]["empty"] is True)
    check("非空代理读成非空", masked["HTTPS_PROXY"]["empty"] is False)
    check("大小写两种写法都覆盖",
          guard.judge_proxy_empty(masked)["ok"] is False
          and set(guard.judge_proxy_empty(masked)["nonEmptyKeys"]) == {"HTTPS_PROXY", "http_proxy"})
    check("全空代理判定通过",
          guard.judge_proxy_empty(guard.mask_env({"HTTP_PROXY": "", "HTTPS_PROXY": None}))["ok"] is True)
    check("NO_PROXY 不算破线",
          guard.judge_proxy_empty(guard.mask_env({"HTTP_PROXY": "", "NO_PROXY": "127.0.0.1"}))["ok"] is True)
    check("SCHEDULERS_ENABLED 值保留（判据要逐字比）",
          masked["SCHEDULERS_ENABLED"]["value"] == "1")
    check("其它配置变量只记长度不记值",
          "chars" in masked.get("SYNC_HOUR", {"chars": 0}) and "value" not in masked.get("SYNC_HOUR", {}))
    check("调度开关被关判不通过",
          guard.judge_schedulers_enabled({"SCHEDULERS_ENABLED": {"value": "0"}})["ok"] is False)


def test_collecting_is_not_terminal():
    """11-28 的病根：`collecting` 被当终态。装载前置必须在同一处红。"""
    collecting = {"lastAttempt": {"lastAttemptDate": TARGET, "lastAttemptOutcome": "collecting"}}
    completed = {"lastAttempt": {"lastAttemptDate": TARGET, "lastAttemptOutcome": "completed"}}
    check("collecting 不是终态", guard.judge_sync_terminal(collecting, TARGET)["ok"] is False)
    check("completed 是终态", guard.judge_sync_terminal(completed, TARGET)["ok"] is True)
    check("partial_failed 是终态但语义是失败（仍算已终态）",
          guard.judge_sync_terminal(
              {"lastAttempt": {"lastAttemptDate": TARGET, "lastAttemptOutcome": "partial_failed"}},
              TARGET)["ok"] is True)
    check("前一天 marker 不冒充当日",
          guard.judge_sync_terminal(
              {"lastAttempt": {"lastAttemptDate": "2026-11-30", "lastAttemptOutcome": "completed"}},
              TARGET)["ok"] is False)
    check("空 marker 不默认通过", guard.judge_sync_terminal({}, TARGET)["ok"] is False)
    check("retry=pending 算未清",
          guard.judge_sync_terminal(dict(completed, retry={"state": "pending"}), TARGET)["ok"] is False)
    check("retry=running 算未清",
          guard.judge_sync_terminal(dict(completed, retry={"state": "running"}), TARGET)["ok"] is False)
    check("retry=completed 不算未清",
          guard.judge_sync_terminal(dict(completed, retry={"state": "completed"}), TARGET)["ok"] is True)
    check("同步仍在跑判不通过",
          guard.judge_sync_terminal(dict(completed, running=True), TARGET)["ok"] is False)


def test_us_job_must_be_same_day():
    """重启不会补跑的依据：`completedDate` 必须是当天。"""
    check("当日完成判通过", guard.judge_us_completed(
        {"usListJob": {"state": "completed", "completedDate": TARGET}}, TARGET)["ok"] is True)
    check("跨日完成判不通过（否则重启会真去补跑）", guard.judge_us_completed(
        {"usListJob": {"state": "completed", "completedDate": "2026-11-30"}}, TARGET)["ok"] is False)
    check("waiting 判不通过", guard.judge_us_completed(
        {"usListJob": {"state": "waiting", "completedDate": None}}, TARGET)["ok"] is False)


def test_backup_freshness_and_accounting():
    now = datetime.fromisoformat("2026-12-01T16:30:00+08:00")
    check("13 小时内新鲜", guard.judge_backup_fresh(
        {"lastRun": "2026-12-01T03:30:08+08:00", "trigger": "daily", "ok": True}, now)["ok"] is True)
    check("超过 26 小时陈旧", guard.judge_backup_fresh(
        {"lastRun": "2026-11-29T03:30:00+08:00", "trigger": "daily", "ok": True}, now)["ok"] is False)
    check("startup-catchup 不冒充自然备份", guard.judge_backup_fresh(
        {"lastRun": "2026-12-01T15:00:00+08:00", "trigger": "startup-catchup", "ok": True}, now)["ok"] is False)
    check("无 lastRun 判不通过", guard.judge_backup_fresh({"trigger": "daily"}, now)["ok"] is False)
    check("lastRun 在未来判可疑", guard.judge_backup_fresh(
        {"lastRun": "2026-12-02T03:30:00+08:00", "trigger": "daily", "ok": True}, now)["ok"] is False)
    check("ok=false 判不通过", guard.judge_backup_fresh(
        {"lastRun": "2026-12-01T03:30:00+08:00", "trigger": "daily", "ok": False}, now)["ok"] is False)
    check("lastRun 不可解析判不通过",
          guard.judge_backup_fresh({"lastRun": "notatime", "trigger": "daily"}, now)["ok"] is False)


def test_hotspot_weekend_semantics():
    weekday_fixture = {"lastAttempt": {"lastAttemptDate": TARGET, "lastAttemptOutcome": "completed"}}
    check("工作日终态通过", guard.judge_hotspot(weekday_fixture, TARGET, 1)["ok"] is True)
    check("工作日缺记录不通过", guard.judge_hotspot({}, TARGET, 1)["ok"] is False)
    check("周末缺记录不是失败", guard.judge_hotspot({}, "2026-12-05", 5)["ok"] is True)
    check("周末热点仍在跑判不通过", guard.judge_hotspot({"running": True}, "2026-12-05", 5)["ok"] is False)
    check("周六周日都按周末口径", guard.judge_hotspot({}, "2026-12-05", 5)["mode"] == "weekend"
          and guard.judge_hotspot({}, "2026-12-06", 6)["mode"] == "weekend")


def test_next_run_parsing():
    check("同日期通过（不挑格式）",
          guard.normalize_next_run("2026-12-01 02:00:00+08:00", TARGET)["ok"] is True)
    check("换日不通过", guard.normalize_next_run("2026-12-02 02:00:00+08:00", TARGET)["ok"] is False)
    check("空值不通过（调度器没注册）", guard.normalize_next_run(None, TARGET)["ok"] is False)
    check("非时间字面不通过", guard.normalize_next_run("Select-Object failed", TARGET)["ok"] is False)
    check("T 分隔也能读", guard.normalize_next_run("2026-12-01T02:00:00", TARGET)["ok"] is True)


def _baseline():
    return {
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
            DS: {"image": "img-old", "startedAt": "T0", "health": "healthy"},
            WEB: {"image": "web-img", "startedAt": "W0", "health": "healthy"},
        },
        "env": {"SCHEDULERS_ENABLED": {"value": "1"},
                "HTTP_PROXY": {"present": True, "empty": True}},
    }


def test_compare_catches_real_regressions_only():
    before = _baseline()
    after = json.loads(json.dumps(before))
    after["containers"][DS] = {"image": "img-new", "startedAt": "T9", "health": "healthy"}
    clean = guard.compare_baselines(before, after)
    check("干净装载无失败项", not clean["failed"])
    check("DS 换镜像记为预期差异",
          any("DS 镜像已切换" in item for item in clean["expectedDifferences"]))

    # 只为回归：采集侧把容器读数放在 `containers` 下，比对侧曾按顶层键读，
    # 导致**真实回执自比对都会报"Web 已变"**。这条断言专门钉住那个形状。
    self_cmp = guard.compare_baselines(before, json.loads(json.dumps(before)))
    check("同一份快照自比对应无失败项（防容器键口径漂移）", not self_cmp["failed"])
    check("扁平旧形状也能读（兼容回落）",
          guard.container_snapshot({WEB: {"image": "x"}}, WEB).get("image") == "x")
    check("嵌套优先于扁平", guard.container_snapshot(
        {"containers": {WEB: {"image": "nested"}}, WEB: {"image": "flat"}}, WEB)["image"] == "nested")

    replaced = json.loads(json.dumps(after))
    replaced["db"]["stockCodesSha256"] = "changed"
    check("A 股整类替换判失败",
          any("stockCodesSha256" in c["name"]
              for c in guard.compare_baselines(before, replaced)["failed"]))

    web_restart = json.loads(json.dumps(after))
    web_restart["containers"][WEB]["startedAt"] = "W9"
    check("Web 被重启判失败",
          any("Web 镜像与启动时刻未变" in c["name"]
              for c in guard.compare_baselines(before, web_restart)["failed"]))

    new_backup = json.loads(json.dumps(after))
    new_backup["backupFiles"] = new_backup["backupFiles"] + ["dev-20261201-160000.db"]
    check("装载期间冒出新备份判失败",
          any("新增备份文件" in c["name"]
              for c in guard.compare_baselines(before, new_backup)["failed"]))

    new_gen = json.loads(json.dumps(after))
    new_gen["usListJob"]["snapshotId"] = "snap-2"
    check("美股新 generation 判失败",
          any("美股无新 generation" in c["name"]
              for c in guard.compare_baselines(before, new_gen)["failed"]))

    marker_moved = json.loads(json.dumps(after))
    marker_moved["markers"]["sync"]["at"] = "T2"
    check("marker 被改写判失败",
          any("同步 marker 未被装载改写" in c["name"]
              for c in guard.compare_baselines(before, marker_moved)["failed"]))

    cron_moved = json.loads(json.dumps(after))
    cron_moved["jobs"]["sync"] = "2026-12-01 03:00"
    check("调度时刻被改判失败",
          any("同步调度时刻未变" in c["name"]
              for c in guard.compare_baselines(before, cron_moved)["failed"]))

    hotspot_fired = json.loads(json.dumps(after))
    hotspot_fired["markers"]["hotspot"]["at"] = "H2"
    check("装载期间热点冒出新尝试判失败",
          any("热点无新尝试" in c["name"]
              for c in guard.compare_baselines(before, hotspot_fired)["failed"]))

    catchup = json.loads(json.dumps(after))
    catchup["backup"]["state"] = {"lastRun": "2026-12-01T15:00:00+08:00",
                                  "trigger": "startup-catchup"}
    check("启动补备判为启动行为异常",
          any("启动补备" in c["name"]
              for c in guard.compare_baselines(before, catchup)["failed"]))

    retry_plan = json.loads(json.dumps(after))
    retry_plan["sync"]["retry"] = {"state": "pending"}
    check("装载后冒出补试计划判失败",
          any("retry 未变" in c["name"]
              for c in guard.compare_baselines(before, retry_plan)["failed"]))

    swap = json.loads(json.dumps(after))
    swap["db"]["byType"] = {"fund": 28001, "stock": 5899, "hk": 4700}
    check("一类减一类增（总数不变）仍判失败",
          any("六类行数逐类一致" in c["name"]
              for c in guard.compare_baselines(before, swap)["failed"]))

    proxy_set = json.loads(json.dumps(after))
    proxy_set["env"]["HTTP_PROXY"] = {"present": True, "empty": False}
    check("装载时偷偷加代理判失败",
          any("代理仍为空" in c["name"]
              for c in guard.compare_baselines(before, proxy_set)["failed"]))

    sched_off = json.loads(json.dumps(after))
    sched_off["env"]["SCHEDULERS_ENABLED"] = {"value": "0"}
    check("装载时关调度判失败",
          any("调度开关未变" in c["name"]
              for c in guard.compare_baselines(before, sched_off)["failed"]))


def test_preflight_never_passes_on_missing_readings():
    empty = guard.preflight({"git": {"dirtyPaths": 0}}, TARGET)
    check("空读数判 stop", empty["verdict"] == "stop")
    check("十条都留下记录（不静默跳过）", len(empty["checks"]) == 10)
    check("十条编号连续", [c["id"] for c in empty["checks"]] == list(range(1, 11)))

    env_unreadable = guard.preflight({"readErrors": ["env"]}, TARGET)
    check("环境读不出 ⇒ stop", env_unreadable["verdict"] == "stop")
    env_check = [c for c in env_unreadable["checks"] if c["id"] == 10][0]
    check("环境读不出 ⇒ 第 10 条判不通过", env_check["ok"] is False)
    check("环境读不出时明细写明原因", "读不出" in env_check["detail"])

    full = {
        "git": {"trackedDirty": 0, "ahead": 0, "behind": 0, "untrackedPaths": 662, "sha": "abc"},
        "containers": {DS: {"health": "healthy"}, WEB: {"health": "healthy"}},
        "sync": {"running": False, "retry": None},
        "markers": {"sync": {"lastAttemptDate": "2026-12-01", "lastAttemptOutcome": "completed"},
                    "hotspot": {"lastAttemptDate": "2026-12-01", "lastAttemptOutcome": "completed"}},
        "usListJob": {"state": "completed", "completedDate": "2026-12-01"},
        "backup": {"state": {"lastRun": datetime.now(guard.BEIJING).isoformat(timespec="seconds"),
                             "trigger": "daily", "ok": True}},
        "jobs": {"sync": "2026-12-01 02:00", "backup": "2026-12-01 03:30"},
        "env": guard.mask_env({"HTTP_PROXY": "", "HTTPS_PROXY": "", "SCHEDULERS_ENABLED": "1"}),
    }
    # 2026-12-01 是周二 ⇒ 工作日口径
    ok_result = guard.preflight(full, TARGET)
    check("读数齐全且对齐 ⇒ pass", ok_result["verdict"] == "pass")
    check("未跟踪 662 条测试产物不阻断（§4.1）",
          [c for c in ok_result["checks"] if c["id"] == 1][0]["ok"] is True)

    dirty = json.loads(json.dumps(full))
    dirty["git"]["trackedDirty"] = 3
    check("已跟踪工作区不干净 ⇒ stop", guard.preflight(dirty, TARGET)["verdict"] == "stop")

    ahead = json.loads(json.dumps(full))
    ahead["git"]["ahead"] = 1
    check("有未推提交 ⇒ stop", guard.preflight(ahead, TARGET)["verdict"] == "stop")

    behind = json.loads(json.dumps(full))
    behind["git"]["behind"] = 1
    check("落后 origin/dev ⇒ stop", guard.preflight(behind, TARGET)["verdict"] == "stop")

    wrong_day = json.loads(json.dumps(full))
    wrong_day["jobs"]["sync"] = "2026-12-02 02:00"
    check("下一次同步不是目标日 ⇒ stop", guard.preflight(wrong_day, TARGET)["verdict"] == "stop")

    catchup_backup = json.loads(json.dumps(full))
    catchup_backup["backup"]["state"]["trigger"] = "startup-catchup"
    check("补备冒充自然备份 ⇒ stop", guard.preflight(catchup_backup, TARGET)["verdict"] == "stop")


def test_rehearsal_receipt_refused_as_baseline():
    """演练回执不得被当成装载窗口基线——否则"演过一次"会变成"已经冻结过"的假证据。"""
    import io
    import json as _json
    import tempfile
    from contextlib import redirect_stdout

    with tempfile.TemporaryDirectory() as tmp:
        revisit = Path(tmp) / "before.json"
        after = Path(tmp) / "after.json"
        reveal = Path(tmp) / "reveal.json"
        # 包一层假 collect：只换 phase 字段，避免碰 Docker。
        original = guard.collect
        try:
            guard.collect = lambda phase, target=None, **kw: {
                "phase": phase, "targetDate": target, "collectedAt": "2026-12-01T16:30:00+08:00",
                "readErrors": [], "git": {"trackedDirty": 0, "ahead": 0, "behind": 0},
                "db": {"integrity": "ok", "migrations": 12, "stockCodesSha256": "a",
                       "stockNamesSha256": "b", "hotspotDigest": 63},
                "containers": {}, "markers": {"sync": {}, "hotspot": {}},
                "usListJob": {}, "sync": {}, "backup": {"state": {}},
                "backupFiles": [], "jobs": {}, "env": {}, "refreshState": {},
            }
            with redirect_stdout(io.StringIO()):
                guard.main(["baseline", "--phase", "rehearsal", "--date", TARGET, "--out", str(revisit)])
                guard.main(["baseline", "--phase", "before", "--date", TARGET, "--out", str(after)])
        finally:
            guard.collect = original

        saved = _json.loads(revisit.read_text(encoding="utf-8"))
        check("演练回执带 phase=rehearsal", saved.get("phase") == "rehearsal")

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = guard.main(["compare", "--baseline", str(revisit), "--after", str(after)])
        check("拿演练回执做 compare 被拒绝", code == 4)
        check("拒绝理由写明是演练回执", "演练回执" in buffer.getvalue())

        buffer2 = io.StringIO()
        with redirect_stdout(buffer2):
            code2 = guard.main(["compare", "--baseline", str(after), "--after", str(revisit)])
        check("演练回执也不能当 after", code2 == 4)


def test_selftest_of_guard_passes():
    """护栏自带的 `--selftest` 必须独立绿：它是装载夜唯一的即时自检入口。"""
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = guard.selftest()
    output = buffer.getvalue()
    check("护栏自检 exit=0", code == 0)
    check("护栏自检逐条全过", "FAIL" not in output)
    check("护栏自检有收尾计数", "通过 =====" in output)


def main() -> int:
    test_proxy_masking_never_leaks_values()
    test_collecting_is_not_terminal()
    test_us_job_must_be_same_day()
    test_backup_freshness_and_accounting()
    test_hotspot_weekend_semantics()
    test_next_run_parsing()
    test_compare_catches_real_regressions_only()
    test_preflight_never_passes_on_missing_readings()
    test_rehearsal_receipt_refused_as_baseline()
    test_selftest_of_guard_passes()
    passed = sum(1 for _, ok in results if ok)
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
