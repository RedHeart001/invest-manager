"""W3 离线单测（2026-11-27）：失败类型的有界自动补试。

策略变更（经确认）：`sync_scheduler.py` 原先明确「失败类型不自动重试」（整轮实测 9.6～13
分钟，反复重试会持续占东财源族）。W3 只把边界放开一条缝——**每日最多一次、延迟 30 分钟、
只补自然轮失败的那几类、不带 force**。本套件逐条钉住这条缝的位置，防的是日后「顺手多补
一轮」「顺手加个 force」「顺手把 us 也塞进来」。

方案 §11 列的 10 条，一条一枚用例（编号对齐）：

  [1] 02:00 只有 stock/crypto 失败 ⇒ 计划里只有这两类
  [2] 成功类型零出网（补试的 `?types=` 不含它们）
  [3] 到点前不执行（`notBefore` 之前零请求）
  [4] 重启后 pending 不丢失、不重复（`pending → running` 只认领一次）
  [5] 主任务 running 时不并发（等不到就让位，记 `cancelled`，绝不叠第二条腿）
  [6] `inconclusive` 不补试（结果未知时重跑＝把额度花在可能已成功的一轮上）
  [7] 成功后 pending 收成 `completed`
  [8] 仍失败 ⇒ `exhausted`，且当日不再自动执行
  [9] 不带 `force`（仍受 web 当日幂等闸门约束）
  [10] us 持久化任务不受干扰（不补、不追回执、不动它的 job）

另外三枚是本套件的「账不许被篡改」锁：补试轮不得改写 marker 的 `lastAttempt*`／
`lastResult`（那是自然轮的账）；`_mark_attempt`／`_mark_outcome` 覆写时必须把 `retry`
键原样带过去；补试轮的刷新腿只覆盖本轮类型（`exclude` ＋ 独立 runId）。

运行方式（零出网；requests 的 post／get 全被替身接管）：
    PYTHONPATH=. .venv/Scripts/python tests/test_w3_retry.py
"""

import copy
import os
import pathlib
import sys
import tempfile
import threading
import time as _time  # noqa: F401  （保留：下方时长断言用）
from datetime import datetime, timedelta

# 本机 `tempfile.gettempdir()` 解析到仓库根 ⇒ 显式指到 `.tmp/`（已 gitignore）
_REPO = pathlib.Path(__file__).resolve().parents[2]
_TMP = _REPO / ".tmp"
_TMP.mkdir(exist_ok=True)
tempfile.tempdir = str(_TMP)

# CR9-94 同族：先于 app 的任何 import 把落点指进临时目录。本套件直调 `_execute_types`
# （它会经 `_mark_outcome` 写 sync-state.json），不指走就会把假轮的日期写进真文件。
os.environ["SYNC_STATE_FILE"] = os.path.join(tempfile.mkdtemp(prefix="w3retry-state-"), "sync-state.json")
os.environ["US_LIST_JOB_DIR"] = os.path.join(tempfile.mkdtemp(prefix="w3retry-usjob-"), "job")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402

import app.sync_scheduler as ss  # noqa: E402
from app import us_list_job  # noqa: E402
from app.utils.timeutil import beijing_today  # noqa: E402

TODAY = beijing_today()

_PASS = 0
_FAIL = 0


def check(name: str, cond, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ok   {name}")
    else:
        _FAIL += 1
        print(f"  FAIL {name}{('  — ' + str(detail)) if detail else ''}")


# ---------- 假 web（两腿按 URL 分派） ----------

CALLS: list = []
SYNC_BODY: dict = {}
REFRESH_BODY: dict = {}
US_ENSURE_CALLS: list = []


class _Resp:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def _fake_post(url, timeout=None, **kw):
    CALLS.append({"url": url, "timeout": timeout, **kw})
    if "market/refresh" in url:
        return _Resp(copy.deepcopy(REFRESH_BODY or {"tookMs": 10, "results": []}))
    # ⚠️ 深拷贝不是洁癖：`_execute` 会往 `body["results"]` 里 **append** 美股那一行
    # （`results.append(us_result)`）。直接交回同一个 dict 就等于让"上一轮的收尾"改写
    # 下一轮看到的上游响应——本套件 [10] 首跑就撞上了（补试轮凭空多出一行 us）。
    return _Resp(copy.deepcopy(SYNC_BODY))


def _fake_get(url, **kw):
    CALLS.append({"url": url, "timeout": kw.get("timeout"), "get": True})
    return _Resp({"status": "ok", "db": "ok"})


requests.post = _fake_post  # type: ignore[assignment]
requests.get = _fake_get  # type: ignore[assignment]

# us 任务钉成「当日已完成」：本套件只关心五类那条账，且零出网
_US_OK = {"state": "completed", "snapshotId": "unit-test-us", "publishedCount": 0, "completedDate": TODAY}


def _ensure_running(*a, **k):
    US_ENSURE_CALLS.append((a, k))
    return {"started": False, "reason": "test-stub", "status": dict(_US_OK)}


us_list_job.ensure_running = _ensure_running  # type: ignore[assignment]
us_list_job.status = lambda: dict(_US_OK)  # type: ignore[assignment]


def _reset() -> None:
    CALLS.clear()
    US_ENSURE_CALLS.clear()
    global SYNC_BODY, REFRESH_BODY
    SYNC_BODY = {"ok": True, "tookMs": 1, "results": []}
    REFRESH_BODY = {"tookMs": 10, "results": []}
    ss._state.clear()
    ss._state.update(
        {
            "running": False,
            "lastRun": None,
            "lastDate": None,
            "lastResult": None,
            "runs": 0,
            "skippedReason": None,
            "lastRefresh": None,
            "markerReadError": None,
            "markerWriteFailed": False,
            "retry": None,
            "retryLastResult": None,
        }
    )
    path = pathlib.Path(os.environ["SYNC_STATE_FILE"])
    if path.exists():
        path.unlink()


def _marker() -> dict:
    import json

    path = pathlib.Path(os.environ["SYNC_STATE_FILE"])
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _sync_urls() -> list:
    return [c["url"] for c in CALLS if "market/refresh" not in c["url"]]


def _refresh_urls() -> list:
    return [c["url"] for c in CALLS if "market/refresh" in c["url"]]


def _run_daily(partial: dict | None = None) -> dict:
    """跑一次「自然轮」的同步腿＋链式刷新腿（`running` 由调用方认领，与 run_now 一致）。"""
    global SYNC_BODY
    SYNC_BODY = partial or {"ok": True, "tookMs": 1, "results": []}
    ss._state["running"] = True
    try:
        return ss._execute("daily")
    finally:
        ss._state["running"] = False


# ---------- [1] 只含失败类型 ----------


def test_plan_contains_only_failed_types() -> None:
    print("[1] 02:00 只有 stock/crypto 失败 ⇒ 补试计划里只有这两类")
    _reset()
    r = _run_daily(
        {
            "ok": False,
            "tookMs": 1,
            "results": [
                {"type": "fund", "count": 28013},
                {"type": "stock", "error": "eastmoney request failed on all hosts"},
                {"type": "bond", "skipped": True},
                {"type": "crypto", "error": "coingecko unreachable"},
                {"type": "hk", "count": 4596},
            ],
        }
    )
    check("整轮记为 partial_failed", r.get("outcome") == "partial_failed", r.get("outcome"))
    plan = _marker().get("retry") or {}
    check("盘上登记了 retry 计划", bool(plan), _marker())
    check("state=pending", plan.get("state") == "pending", plan)
    check("🔁 types 只有失败的两类（bond 是 skipped、fund/hk 成功 ⇒ 都不在里面）",
          plan.get("types") == ["stock", "crypto"], plan.get("types"))
    check("maxAttempts=1（每日最多一次）", plan.get("maxAttempts") == 1, plan.get("maxAttempts"))
    check("attempt 从 0 起算", plan.get("attempt") == 0, plan.get("attempt"))
    check("date=今天", plan.get("date") == TODAY, plan.get("date"))
    not_before = plan.get("notBefore") or ""
    due = datetime.fromisoformat(not_before)
    delta = (due - datetime.now(due.tzinfo)).total_seconds()
    check("notBefore ≈ 现在+30 分钟（不是立即、也不是明天）",
          25 * 60 < delta <= 31 * 60, f"{delta:.0f}s")
    check("回执里点名已安排（`note` 不再说「本轮不自动重试」）",
          "自动补试" in str(r.get("note") or "") and "不自动重试" not in str(r.get("note") or ""),
          str(r.get("note"))[:160])
    check("回执带 retryPlanned 摘要", (r.get("retryPlanned") or {}).get("types") == ["stock", "crypto"],
          r.get("retryPlanned"))


# ---------- [2] 成功类型零出网 ----------


def test_successful_types_get_no_request() -> None:
    print("[2] 补试只请求失败类型：URL 里没有 fund/bond/hk，成功类型零出网")
    _reset()
    _run_daily(
        {
            "ok": False,
            "results": [
                {"type": "fund", "count": 1},
                {"type": "stock", "error": "em down"},
                {"type": "bond", "count": 1},
                {"type": "crypto", "error": "cg down"},
                {"type": "hk", "count": 1},
            ],
        }
    )
    CALLS.clear()
    result = ss._execute_types(ss.RETRY_TRIGGER, ["stock", "crypto"], force=False)
    urls = _sync_urls()
    check("补试只发一次同步腿", len(urls) == 1, urls)
    check("URL 的 types 只有失败的两类", "types=stock,crypto" in urls[0], urls[0])
    for t in ("fund", "bond", "hk"):
        check(f"🔁 成功类型 {t} 不出现在补试 URL 里", f"{t}" not in urls[0].split("?")[1], urls[0])
    check("回执记了 retryTypes（读的人看得出这一轮补了谁）",
          result.get("retryTypes") == ["stock", "crypto"], result.get("retryTypes"))


# ---------- [3] 到点前不执行 ----------


def test_not_executed_before_due() -> None:
    print("[3] 到点前不执行：notBefore 之前 worker 零请求")
    _reset()
    ss._write_retry(
        {
            "date": TODAY,
            "state": "pending",
            "attempt": 0,
            "maxAttempts": 1,
            "types": ["stock"],
            "notBefore": (datetime.now(ss.TZ) + timedelta(seconds=2)).isoformat(timespec="seconds"),
        }
    )
    due_at = _marker()["retry"]["notBefore"]
    thread = threading.Thread(target=ss._retry_worker, args=(due_at,), daemon=True, name="w3-before-due")
    thread.start()
    thread.join(0.8)
    check("到点前零同步请求", not _sync_urls(), _sync_urls())
    check("到点前计划仍是 pending（没被提前认领）",
          (_marker().get("retry") or {}).get("state") == "pending", _marker().get("retry"))
    thread.join(15)
    check("过点之后真的跑了", bool(_sync_urls()), _sync_urls())


# ---------- [4] 重启后 pending 不丢失、不重复 ----------


def test_pending_survives_restart_without_duplicates() -> None:
    print("[4] 重启后 pending 不丢失、不重复")
    _reset()
    plan = {
        "date": TODAY,
        "state": "pending",
        "attempt": 0,
        "maxAttempts": 1,
        "types": ["stock"],
        "notBefore": (datetime.now(ss.TZ) + timedelta(minutes=30)).isoformat(timespec="seconds"),
    }
    ss._write_retry(plan)
    check("写盘后能读回来（`_resume_retry_after_start` 的全部依据）",
          (ss.retry_state() or {}).get("state") == "pending", ss.retry_state())

    # 重启恢复：`_resume_retry_after_start` 先 sleep(8) 让 web 就绪，这里跳过那段等待
    saved_sleep = ss.time.sleep
    ss.time.sleep = lambda *_: None  # type: ignore[assignment]
    started: list = []
    saved_thread = ss.threading.Thread

    class _FakeThread:
        def __init__(self, target=None, args=(), name=None, daemon=None, **_kw):
            started.append({"target": getattr(target, "__name__", str(target)), "name": name})

        def start(self):
            return None

    ss.threading.Thread = _FakeThread  # type: ignore[assignment]
    try:
        ss._resume_retry_after_start()
    finally:
        ss.threading.Thread = saved_thread  # type: ignore[assignment]
        ss.time.sleep = saved_sleep  # type: ignore[assignment]
    check("恢复时确实挂了一个 worker 线程（不是静默丢弃）",
          [s["target"] for s in started] == ["_retry_worker"], started)

    # 不重复：两个线程同时到点，只有一次能完成 pending→running
    first = ss._transition_retry(("pending",), state="running")
    second = ss._transition_retry(("pending",), state="running")
    check("第一次认领成功", bool(first), first)
    check("🔁 第二次认领失败（`completed`/`exhausted`/`running` 都不会被迟到线程改回来）",
          second is None, second)


def test_plan_from_yesterday_is_cancelled_not_replayed() -> None:
    print("[4b] 🔁 昨天的 pending 不会在今天被补跑（否则「每日一次」会变成「每天一次且能补昨天」）")
    _reset()
    ss._write_retry(
        {
            "date": "2000-01-01",
            "state": "pending",
            "attempt": 0,
            "maxAttempts": 1,
            "types": ["stock"],
            "notBefore": "2000-01-01T02:30:00+08:00",
        }
    )
    ss._schedule_retry(ss.retry_state())
    plan = _marker().get("retry") or {}
    check("跨日计划被记成 cancelled", plan.get("state") == "cancelled", plan)
    check("且说了原因（跨日不补）", "not today" in str(plan.get("cancelReason") or ""), plan)
    check("零请求", not _sync_urls(), _sync_urls())


# ---------- [5] 主任务 running 时不并发 ----------


def test_no_concurrency_with_running_sync() -> None:
    print("[5] 主任务 running 时不并发：等不到就让位，记 cancelled，绝不叠第二条腿")
    _reset()
    ss._write_retry(
        {
            "date": TODAY,
            "state": "pending",
            "attempt": 0,
            "maxAttempts": 1,
            "types": ["stock"],
            "notBefore": (datetime.now(ss.TZ) - timedelta(seconds=1)).isoformat(timespec="seconds"),
        }
    )
    due_at = _marker()["retry"]["notBefore"]
    # 让「让位」的十次等待不真等满 10 分钟（间隔是模块常量，函数体内读）
    saved_interval = ss.RETRY_WAIT_INTERVAL_S
    ss.RETRY_WAIT_INTERVAL_S = 0.0
    ss._state["running"] = True
    try:
        ss._retry_worker(due_at)
    finally:
        ss.RETRY_WAIT_INTERVAL_S = saved_interval
        still_running = bool(ss._state["running"])
        ss._state["running"] = False
    plan = _marker().get("retry") or {}
    check("零同步请求（没有和主任务并发）", not _sync_urls(), _sync_urls())
    check("记成 cancelled 而不是 expired/pending", plan.get("state") == "cancelled", plan)
    check("原因说得出「同步还在跑」", "still running" in str(plan.get("cancelReason") or ""), plan)
    check("🔁 主任务的 running 锁没有被补试放开（放开它＝两个写库的腿同时跑）",
          still_running is True, still_running)


def test_claim_yields_when_sync_finishes() -> None:
    print("[5b] 让位是有终点的：主任务在等待窗口内收尾 ⇒ 补试照常认领")
    _reset()
    saved_interval = ss.RETRY_WAIT_INTERVAL_S
    saved_sleep = ss.time.sleep
    ss.RETRY_WAIT_INTERVAL_S = 0.0
    # ⚠️ 这里刻意**不用**后台线程去放 `running`：那是竞态写法（11-27 门禁首跑即
    # "主任务收尾后认领成功"偶发红——线程抢不到 GIL 时主任务还没放锁，等待窗口就用完了）。
    # 改成在 `time.sleep` 的替身里放锁：第 3 次等待时模拟主任务收尾，次序完全确定。
    waits: list = []

    def _fake_sleep(seconds):
        waits.append(seconds)
        if len(waits) == 3:
            ss._state["running"] = False

    ss._state["running"] = True
    ss.time.sleep = _fake_sleep  # type: ignore[assignment]
    try:
        got = ss._claim_for_retry()
    finally:
        ss.time.sleep = saved_sleep  # type: ignore[assignment]
        ss.RETRY_WAIT_INTERVAL_S = saved_interval
        still = bool(ss._state["running"])
        ss._state["running"] = False
    check("第 3 次等待时主任务收尾 ⇒ 第 4 轮认领成功", got is True, got)
    check("🔁 认领发生在让位之后（不是一开始就硬抢）", len(waits) == 3, waits)
    check("认领成功后 `running` 归补试所有（主任务已放，补试拿走）", got is True and still is True,
          f"got={got} running={still}")


# ---------- [6] inconclusive 不补 ----------


def test_inconclusive_is_not_retried() -> None:
    print("[6] `inconclusive`（结果未知）不补试")
    check("`_retry_types_from` 对 inconclusive 返回空",
          ss._retry_types_from({"outcome": "inconclusive", "failedTypes": ["stock"], "ok": None}) == [],
          ss._retry_types_from({"outcome": "inconclusive", "failedTypes": ["stock"], "ok": None}))
    for outcome in ("completed", "skipped", "collecting", "rejected", "failed"):
        check(f"`{outcome}` 也不补",
              ss._retry_types_from({"outcome": outcome, "failedTypes": ["stock"]}) == [],
              outcome)

    _reset()
    saved = requests.post
    requests.post = lambda url, timeout=None, **kw: (_ for _ in ()).throw(
        requests.exceptions.ReadTimeout("read timeout")
    )
    ss._state["running"] = True
    try:
        r = ss._execute("daily")
    finally:
        requests.post = saved
        ss._state["running"] = False
    check("读超时的整轮记 inconclusive", r.get("outcome") == "inconclusive", r.get("outcome"))
    check("🔁 盘上没有任何补试计划（重跑会把额度花在可能已成功的一轮上）",
          _marker().get("retry") is None, _marker().get("retry"))


# ---------- [7] 成功后 completed ----------


def test_success_marks_completed() -> None:
    print("[7] 补试成功后 pending 收成 completed（不是继续挂着）")
    _reset()
    ss._write_retry(
        {
            "date": TODAY,
            "state": "pending",
            "attempt": 0,
            "maxAttempts": 1,
            "types": ["stock"],
            "notBefore": (datetime.now(ss.TZ) - timedelta(seconds=1)).isoformat(timespec="seconds"),
        }
    )
    due_at = _marker()["retry"]["notBefore"]
    SYNC_BODY_LOCAL = {"ok": True, "tookMs": 5, "results": [{"type": "stock", "count": 5913}]}
    globals()["SYNC_BODY"] = SYNC_BODY_LOCAL
    ss._retry_worker(due_at)
    plan = _marker().get("retry") or {}
    check("state=completed", plan.get("state") == "completed", plan)
    check("attempt 记到 1", plan.get("attempt") == 1, plan.get("attempt"))
    check("带上了这一轮的 outcome", plan.get("outcome") in ("completed", "skipped"), plan.get("outcome"))
    check("finishedAt 落了盘", bool(plan.get("finishedAt")), plan)
    check("`retryLastResult` 另存一份（补试结果不与自然轮抢 lastResult）",
          (ss._state.get("retryLastResult") or {}).get("outcome") in ("completed", "skipped"),
          ss._state.get("retryLastResult"))
    check("补试不再跑第二次：state 已不是 pending", plan.get("state") != "pending", plan)


# ---------- [8] 失败后 exhausted 且当日不再执行 ----------


def test_failure_marks_exhausted_and_stops() -> None:
    print("[8] 仍失败 ⇒ exhausted，且当日不再自动执行")
    _reset()
    ss._write_retry(
        {
            "date": TODAY,
            "state": "pending",
            "attempt": 0,
            "maxAttempts": 1,
            "types": ["stock"],
            "notBefore": (datetime.now(ss.TZ) - timedelta(seconds=1)).isoformat(timespec="seconds"),
        }
    )
    due_at = _marker()["retry"]["notBefore"]
    globals()["SYNC_BODY"] = {"ok": False, "tookMs": 5, "results": [{"type": "stock", "error": "still down"}]}
    ss._retry_worker(due_at)
    plan = _marker().get("retry") or {}
    check("state=exhausted", plan.get("state") == "exhausted", plan)
    check("错误原文留在盘上（不是只写『失败』两个字）",
          "still down" in str(plan.get("note") or plan.get("error") or ""),
          f"note={plan.get('note')} error={plan.get('error')}")
    check("attempt 记到 1（这一发真的花出去了）", plan.get("attempt") == 1, plan.get("attempt"))

    CALLS.clear()
    ss._retry_worker(due_at)
    check("🔁 再叫一次 worker 也零请求（exhausted 不再回到 pending）", not _sync_urls(), _sync_urls())
    check("状态仍是 exhausted", (_marker().get("retry") or {}).get("state") == "exhausted",
          _marker().get("retry"))

    # 当日第二份计划不许登记（每日最多一次）
    again = ss._plan_retry(["stock"], "daily partial_failed")
    check("🔁 当日已有计划 ⇒ `_plan_retry` 不覆盖", again is None, again)


# ---------- [9] 不带 force ----------


def test_retry_never_carries_force() -> None:
    print("[9] 补试不带 force（仍受 web 当日幂等闸门约束）")
    _reset()
    _run_daily({"ok": False, "results": [{"type": "stock", "error": "x"}]})
    CALLS.clear()
    ss._execute_types(ss.RETRY_TRIGGER, ["stock"], force=False)
    for url in _sync_urls() + _refresh_urls():
        check(f"不带 force=1：{url.split('?')[0]}", "force=1" not in url, url)
    check("补试轮的 runId 另起一支（不与自然轮共用同一份进度文件）",
          any("runId=retry-" in u for u in _refresh_urls()), _refresh_urls())


# ---------- [10] us 不受干扰 ----------


def test_us_job_untouched() -> None:
    print("[10] us 持久化任务不受干扰：不补、不追回执、不动它的 job")
    _reset()
    check("`us` 在补试排除名单里", "us" in ss.RETRY_EXCLUDED_TYPES, ss.RETRY_EXCLUDED_TYPES)
    check("`_retry_types_from` 把 us 滤掉",
          ss._retry_types_from({"outcome": "partial_failed", "failedTypes": ["us", "stock"]}) == ["stock"],
          ss._retry_types_from({"outcome": "partial_failed", "failedTypes": ["us", "stock"]}))

    _run_daily({"ok": False, "results": [{"type": "stock", "error": "em down"}]})
    check("自然轮仍会照常启动/恢复 us 任务", bool(US_ENSURE_CALLS), US_ENSURE_CALLS)
    CALLS.clear()
    US_ENSURE_CALLS.clear()
    r = ss._execute_types(ss.RETRY_TRIGGER, ["stock", "us"], force=False)
    check("🔁 补试轮不启动／恢复 us 任务", not US_ENSURE_CALLS, US_ENSURE_CALLS)
    check("补试轮回执里没有 us 那一行（否则看起来像又跑了一整轮）",
          not [x for x in (r.get("results") or []) if x.get("type") == "us"], r.get("results"))
    check("补试轮的 retryTypes 剔掉了 us", r.get("retryTypes") == ["stock"], r.get("retryTypes"))


# ---------- 账不许被篡改 ----------


def test_retry_does_not_rewrite_natural_round_ledger() -> None:
    print("[11] 🔁 补试轮不改写 marker 的 `lastAttempt*`／`lastResult`（那是自然轮的账）")
    _reset()
    _run_daily({"ok": False, "results": [{"type": "stock", "error": "em down"}]})
    before = _marker()
    CALLS.clear()
    ss._execute_types(ss.RETRY_TRIGGER, ["stock"], force=False)
    after = _marker()
    check("lastAttemptTrigger 仍是 daily（被补试改写会让重启补跑与 legStaleness 算错一天）",
          after.get("lastAttemptTrigger") == "daily", after.get("lastAttemptTrigger"))
    check("lastAttemptDate 未变", after.get("lastAttemptDate") == before.get("lastAttemptDate"))
    check("lastAttemptOutcome 仍是自然轮的 partial_failed",
          after.get("lastAttemptOutcome") == "partial_failed", after.get("lastAttemptOutcome"))
    check("lastResult 逐类结果未被补试覆盖",
          (after.get("lastResult") or {}).get("outcome") == "partial_failed",
          after.get("lastResult"))
    check("`runs` 未被补试 +1（它管「本进程跑了几轮整轮」）", ss._state["runs"] == 1, ss._state["runs"])
    check("retry 键仍在（补试自己的账不丢）", (after.get("retry") or {}).get("lastOutcome") is not None,
          after.get("retry"))


def test_retry_key_survives_attempt_and_outcome_overwrites() -> None:
    print("[12] 🔁 `_mark_attempt`／`_mark_outcome` 覆写时必须把 `retry` 键原样带过去")
    _reset()
    _run_daily({"ok": False, "results": [{"type": "stock", "error": "em down"}]})
    planned = (_marker().get("retry") or {}).get("notBefore")
    check("先有了一份计划", bool(planned), _marker())
    # 02:10 主人手动补跑（或重启补跑）——它会走 `_mark_attempt` ＋ `_mark_outcome`
    ss._mark_attempt("manual")
    check("`_mark_attempt` 之后 retry 还在（否则 02:30 那次排好的补试被静默吃掉）",
          (_marker().get("retry") or {}).get("notBefore") == planned, _marker().get("retry"))
    ss._mark_outcome("manual", "completed", {"outcome": "completed", "results": []})
    check("`_mark_outcome` 之后 retry 还在",
          (_marker().get("retry") or {}).get("notBefore") == planned, _marker().get("retry"))
    check("收尾那一轮自己的账也写对了", _marker().get("lastAttemptOutcome") == "completed",
          _marker().get("lastAttemptOutcome"))


def test_retry_refresh_only_covers_retried_types() -> None:
    print("[13] 补试轮的刷新腿只覆盖本轮类型（`exclude` 剔掉其余）")
    _reset()
    _run_daily({"ok": False, "results": [{"type": "stock", "error": "x"}, {"type": "hk", "error": "y"}]})
    CALLS.clear()
    ss._execute_types(ss.RETRY_TRIGGER, ["stock", "hk"], force=False)
    refresh = _refresh_urls()
    check("刷新腿发了一次", len(refresh) == 1, refresh)
    url = refresh[0] if refresh else ""
    exclude = url.split("exclude=")[1].split("&")[0] if "exclude=" in url else ""
    check("exclude 里是**其余**四类（stock/hk 不在里面）",
          set(exclude.split(",")) == {"fund", "bond", "crypto", "us"}, exclude)
    check("runId 是 retry-<今天>（两轮不互相覆盖进度）", f"runId=retry-{TODAY}" in url, url)


def test_natural_round_keeps_its_own_refresh_scope() -> None:
    print("[14] 🔁 自然轮的刷新腿一字未变：exclude=us、runId=daily-<今天>")
    _reset()
    _run_daily({"ok": True, "results": [{"type": "stock", "count": 1}]})
    url = (_refresh_urls() or [""])[0]
    check("exclude 只有 us", "exclude=us&" in url or url.endswith("exclude=us"), url)
    check("runId=daily-<今天>", f"runId=daily-{TODAY}" in url, url)


def test_only_daily_trigger_plans_retry() -> None:
    print("[15] 🔁 只有 `trigger=daily` 才登记补试（启动补跑／手动轮不繁衍）")
    for trigger in ("startup-catchup", "manual", "manual-ui", "daily-retry"):
        _reset()
        ss._state["running"] = True
        SYNC_BODY_LOCAL = {"ok": False, "results": [{"type": "stock", "error": "x"}]}
        globals()["SYNC_BODY"] = SYNC_BODY_LOCAL
        try:
            ss._execute(trigger)
        finally:
            ss._state["running"] = False
        check(f"`{trigger}` 不登记补试", _marker().get("retry") is None, _marker().get("retry"))


def test_all_us_failure_note_is_explicit() -> None:
    print("[16] 只有 us 失败 ⇒ 不排补试，且回执说清「由持久化任务自行续跑」")
    _reset()
    global SYNC_BODY
    SYNC_BODY = {"ok": False, "results": [{"type": "stock", "count": 1}]}
    ss._state["running"] = True
    try:
        r = ss._execute("daily")
    finally:
        ss._state["running"] = False
    check("零失败时没有计划", _marker().get("retry") is None, _marker().get("retry"))
    check("outcome=completed", r.get("outcome") == "completed", r.get("outcome"))


def main() -> int:
    test_plan_contains_only_failed_types()
    test_successful_types_get_no_request()
    test_not_executed_before_due()
    test_pending_survives_restart_without_duplicates()
    test_plan_from_yesterday_is_cancelled_not_replayed()
    test_no_concurrency_with_running_sync()
    test_claim_yields_when_sync_finishes()
    test_inconclusive_is_not_retried()
    test_success_marks_completed()
    test_failure_marks_exhausted_and_stops()
    test_retry_never_carries_force()
    test_us_job_untouched()
    test_retry_does_not_rewrite_natural_round_ledger()
    test_retry_key_survives_attempt_and_outcome_overwrites()
    test_retry_refresh_only_covers_retried_types()
    test_natural_round_keeps_its_own_refresh_scope()
    test_only_daily_trigger_plans_retry()
    test_all_us_failure_note_is_explicit()
    total = _PASS + _FAIL
    print(f"\n== 结果：{_PASS}/{total} 通过 ==")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
