"""CR9-95（#68 同族的另一半）离线单测：热点腿「今天这台机器起过一轮」的落盘判据。

背景（10-13 实测代价＝同步侧白烧 47 发东财，见 FIX-LEDGER 第 68 项）：同步侧那一半已由
CR9-94 治好（`runtime/sync-state.json`）。热点腿的形状**不同**——`_catch_up_decide` 本来
就在问一个现成的结果真值（web 的 `/api/hotspots/ingest?date=今天` 的 count），所以它不像
同步侧那样"数据落了库还重买"；它漏的是另一格：**跑过但 0 产出／失败**的那一轮，digest
计数对它永远答 0 ⇒ 每次重启都重买一整轮 pipeline（akshare＋东财＋Tavily 三源）。

处置＝同一枚 date-keyed marker 扩到热点腿，与 `lastRun`/`lastResult` 同住
`runtime/hotspot-state.json`（不新造第二份状态位），写点在 `_execute` 顶部＝**钱已被承诺
的那一刻**（被 kill 的轮也留痕；线程启动失败那一支走不到这里 ⇒ 零成本的失败不吃掉当天）。
逃出口＝`POST /hotspots/run`（手动触发不读这枚）。

运行方式（无需任何服务在跑、零出网）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr9_95_hotspot_marker.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# 隔离＝本套件交付物的一部分（CR9-94 那一课）：真的 `runtime/hotspot-state.json` 在正常
# 日子里就带着今天的 `lastRun`；一旦本套件的假轮把 `lastAttemptDate=今天` 写进那份真文件，
# 之后当天任何一次重启都会在新加的早退分支上跳过补跑——**静默挡掉当天合法动作**。
_TMPDIR = tempfile.mkdtemp(prefix="cr995-hotspot-marker-")
os.environ["HOTSPOT_STATE_FILE"] = os.path.join(_TMPDIR, "hotspot-state.json")
_STATE = os.environ["HOTSPOT_STATE_FILE"]
_DEFAULT_STATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime", "hotspot-state.json"
)

import app.hotspot.scheduler as hs  # noqa: E402
from app.utils.timeutil import beijing_today  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# ---------- 替身与工具 ----------


class _Recorder:
    """`run_pipeline` 的替身：记调用次数，可按剧本返回／抛异常，可在**跑的中途**读盘。"""

    def __init__(self, items=None, raises=None, mid=None):
        self.calls = 0
        self._items = [{"code": "x"}] if items is None else items
        self._raises = raises
        self._mid = mid
        self.mid_disk = None

    def __call__(self, trigger: str = "manual") -> dict:
        self.calls += 1
        if self._mid is not None:
            self.mid_disk = _read_file()  # 写点在钱之前的那一枚牙齿
        if self._raises is not None:
            raise self._raises
        return {"items": self._items, "sources": ["cls"], "source": "cls",
                "missing": [], "degraded": False, "note": None, "stats": {}, "samples": {}}


class _WebQuery:
    """`requests.get` 的替身：记次数，按剧本给 count 或抛异常。"""

    def __init__(self, count=0, raises=None):
        self.calls = 0
        self._count = count
        self._raises = raises

    def __call__(self, url, params=None, timeout=None):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return _Resp(self._count)


class _Resp:
    ok = True

    def __init__(self, count: int):
        self._count = count

    def json(self):
        return {"count": self._count}


def _read_file() -> dict | None:
    try:
        with open(_STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _clear_file() -> None:
    try:
        os.remove(_STATE)
    except OSError:
        pass


_CLEAN = {
    "running": False, "lastRun": None, "lastResult": None, "runs": 0,
    "catchUpResolved": None, "lastAttemptDate": None, "lastAttemptTrigger": None,
    "lastAttemptOutcome": None, "lastAttemptAt": None, "stateWriteFailed": False,
    "catchUpSkipReason": None,
}


def _reset() -> None:
    hs._state.update(_CLEAN)  # 保持 dict 身份（同步侧按模块属性读同一个对象）
    _clear_file()


def _patched(rec=None, web=None, today_seq=None):
    """把 pipeline／web 查询／`beijing_today` 换成替身，返回 restore。"""
    orig_pipe, orig_get, orig_today = hs.run_pipeline, None, hs.beijing_today
    import requests

    orig_get = requests.get
    if rec is not None:
        hs.run_pipeline = rec
    if web is not None:
        requests.get = web
    if today_seq is not None:
        box = {"i": 0}

        def _today():
            v = today_seq[min(box["i"], len(today_seq) - 1)]
            box["i"] += 1
            return v

        hs.beijing_today = _today

    def restore():
        hs.run_pipeline = orig_pipe
        requests.get = orig_get
        hs.beijing_today = orig_today

    return restore


def _run_decide(at=None, web=None, rec=None):
    """跑一次 `_catch_up_decide`（可钉时刻）；`at` 用替身时钟，其余照真码走。"""
    restore = _patched(rec=rec, web=web)
    orig_dt = hs.datetime
    if at is not None:
        class _DT:
            @staticmethod
            def now(tz=None):
                return at

            @staticmethod
            def fromisoformat(s):
                return datetime.fromisoformat(s)

        hs.datetime = _DT  # type: ignore[assignment]
    try:
        hs._catch_up_decide()
    finally:
        hs.datetime = orig_dt  # type: ignore[assignment]
        restore()


def _run_execute(rec):
    restore = _patched(rec=rec)
    hs._state["running"] = True  # 调用方（_single_flight／request_run）已认领
    try:
        return hs._execute("unit-test")
    finally:
        restore()


# ---------- A 组：写点在钱之前，收尾写真结局 ----------


def test_marked_before_pipeline_and_outcome_after() -> None:
    """①② marker 在 `run_pipeline` **之前**就落了盘，收尾把 outcome 从 running 改成真结局。"""
    _reset()
    rec = _Recorder(mid=True)
    _run_execute(rec)
    disk = rec.mid_disk or {}
    check("CR9-95①：pipeline 还没返回时盘上已有今天的 marker（写点＝钱已被承诺的那一刻）",
          disk.get("lastAttemptDate") == beijing_today()
          and disk.get("lastAttemptOutcome") == "running"
          and disk.get("lastAttemptTrigger") == "unit-test", str(disk)[:220])
    after = _read_file() or {}
    check("CR9-95②：收尾把 outcome 覆写成 completed，且日期/trigger 仍是起跑那一份",
          after.get("lastAttemptOutcome") == "completed"
          and after.get("lastAttemptDate") == beijing_today()
          and after.get("lastAttemptTrigger") == "unit-test", str(after)[:220])
    check("CR9-95②：`lastRun`/`lastResult` 那两件既有落盘没被挤掉（同一份文件两用途）",
          bool(after.get("lastRun")) and isinstance(after.get("lastResult"), dict),
          str(sorted(after.keys())))


def test_failed_and_zero_items_are_distinguishable() -> None:
    """③④ failed 与 zero-items 是两档：后者正是 digest 计数永远答 0 的那一形。"""
    _reset()
    _run_execute(_Recorder(raises=RuntimeError("boom")))
    d1 = _read_file() or {}
    check("CR9-95③：失败轮 outcome=failed，且盘上日期仍是今天（重启不该重买这一轮）",
          d1.get("lastAttemptOutcome") == "failed" and d1.get("lastAttemptDate") == beijing_today(),
          str(d1)[:200])
    _reset()
    _run_execute(_Recorder(items=[]))
    d2 = _read_file() or {}
    check("CR9-95④：跑通但 0 产出 ⇒ outcome=zero-items（与 completed 不同档，不与 failed 混读）",
          d2.get("lastAttemptOutcome") == "zero-items", str(d2)[:200])


def test_date_is_the_start_day_across_midnight() -> None:
    """⑤ 跨午夜的轮：日期沿用**起跑时**那一份（收尾不重读 `beijing_today`）。"""
    _reset()
    rec = _Recorder(mid=True)
    restore = _patched(rec=rec, today_seq=["2026-10-13", "2026-10-14"])
    hs._state["running"] = True
    try:
        hs._execute("unit-test-midnight")
    finally:
        restore()
    d = _read_file() or {}
    check("CR9-95⑤：起跑在 10-13、收尾时 `beijing_today()` 已翻到 10-14 ⇒ 盘上仍记 10-13",
          d.get("lastAttemptDate") == "2026-10-13" and d.get("lastAttemptOutcome") == "completed",
          str(d)[:200])


# ---------- B 组：启动补跑的早退分支 ----------


def test_marker_blocks_recatchup_today() -> None:
    """⑥ 盘上=今天 ⇒ 既不跑 pipeline 也不查 web（这一枚就是省下那一轮上游的那一道闸）。"""
    _reset()
    hs._state.update({"lastAttemptDate": beijing_today(),
                      "lastAttemptTrigger": "pre-market",
                      "lastAttemptOutcome": "zero-items"})
    hs._write_state()
    rec, web = _Recorder(), _WebQuery(count=0)
    _run_decide(at=datetime(2026, 10, 13, 15, 0, tzinfo=hs.TZ), web=web, rec=rec)
    reason = str(hs._state.get("catchUpSkipReason"))
    check("CR9-95⑥：今天已起过一轮 ⇒ 零 pipeline、零 web 查询",
          rec.calls == 0 and web.calls == 0, f"pipeline={rec.calls} web={web.calls}")
    check("CR9-95⑥：原因写进状态位并带出磁盘态三件（log.info 在 uvicorn 下不打）",
          "already attempted today" in reason and "zero-items" in reason
          and "pre-market" in reason and "POST /hotspots/run" in reason, reason[:220])


def test_yesterday_marker_does_not_block() -> None:
    """⑦🔁 反向对照：昨天的 marker 不算数（隔夜开机照常补跑），且真触发时清掉跳过原因。"""
    _reset()
    hs._state.update({"lastAttemptDate": "2026-01-01", "lastAttemptTrigger": "pre-market",
                      "lastAttemptOutcome": "completed", "catchUpSkipReason": "上一轮留下的噪声"})
    hs._write_state()
    rec, web = _Recorder(), _WebQuery(count=0)
    _run_decide(at=datetime(2026, 10, 13, 15, 0, tzinfo=hs.TZ), web=web, rec=rec)
    check("CR9-95⑦🔁：昨日 marker ⇒ 照常问 web 并补跑一轮（证明那道闸不是恒真桩）",
          web.calls == 1 and rec.calls == 1, f"web={web.calls} pipeline={rec.calls}")
    check("CR9-95⑦🔁：真触发补跑的路径不写跳过原因（否则状态位变常驻噪声，#21 同口径）",
          hs._state.get("catchUpSkipReason") is None, str(hs._state.get("catchUpSkipReason")))


def test_digest_exists_and_web_failure_branches() -> None:
    """⑧⑨ 既有两条分支的行为没被新闸改动：有 digest 跳过；web 查询失败也跳过（不补跑）。"""
    _reset()
    rec, web = _Recorder(), _WebQuery(count=5)
    _run_decide(at=datetime(2026, 10, 13, 15, 0, tzinfo=hs.TZ), web=web, rec=rec)
    check("CR9-95⑧：当日 digest 已存在 ⇒ 跳过且原因带出 count（原行为保持）",
          rec.calls == 0 and web.calls == 1
          and "count=5" in str(hs._state.get("catchUpSkipReason")),
          str(hs._state.get("catchUpSkipReason"))[:160])

    _reset()
    rec2, web2 = _Recorder(), _WebQuery(raises=ConnectionError("web down"))
    _run_decide(at=datetime(2026, 10, 13, 15, 0, tzinfo=hs.TZ), web=web2, rec=rec2)
    check("CR9-95⑨：web 查询异常 ⇒ 不补跑（web 没起来时买一轮上游也无处落库），原因写进状态位",
          rec2.calls == 0 and "ConnectionError" in str(hs._state.get("catchUpSkipReason")),
          str(hs._state.get("catchUpSkipReason"))[:160])


def test_before_schedule_branch() -> None:
    """⑩ 未到 08:30 ⇒ 立即跳过：新闸在时刻闸**之后**，所以这一支连盘都不必读。"""
    _reset()
    rec, web = _Recorder(), _WebQuery(count=0)
    _run_decide(at=datetime(2026, 10, 13, 7, 0, tzinfo=hs.TZ), web=web, rec=rec)
    reason = str(hs._state.get("catchUpSkipReason"))
    check("CR9-95⑩：未到调度时刻 ⇒ 零 pipeline、零 web，原因带出当前时刻与调度点",
          rec.calls == 0 and web.calls == 0 and "before pre-market" in reason and "08:30" in reason,
          f"{reason[:160]} pipeline={rec.calls} web={web.calls}")


def test_resolved_still_set_when_marker_blocks() -> None:
    """⑪ 新分支早退之后 `catchUpResolved` 仍要置今天——否则同步侧回到 CR9-4 之前的死等。"""
    _reset()
    hs._state.update({"lastAttemptDate": beijing_today(), "lastAttemptTrigger": "pre-market",
                      "lastAttemptOutcome": "completed"})
    hs._write_state()
    rec, web = _Recorder(), _WebQuery(count=0)
    restore = _patched(rec=rec, web=web)
    orig_sleep, orig_dt = hs.time.sleep, hs.datetime
    hs.time.sleep = lambda s: None  # 免掉启动等待那 5s

    class _DT:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 10, 13, 15, 0, tzinfo=hs.TZ)

    hs.datetime = _DT  # type: ignore[assignment]
    try:
        hs._catch_up_if_needed()
    finally:
        hs.datetime = orig_dt  # type: ignore[assignment]
        hs.time.sleep = orig_sleep
        restore()
    check("CR9-95⑪：marker 分支早退仍置 `catchUpResolved=今天`（同步侧不死等，CR9-4 语义不回退）",
          hs._state.get("catchUpResolved") == beijing_today() and rec.calls == 0,
          f"resolved={hs._state.get('catchUpResolved')} pipeline={rec.calls}")


# ---------- C 组：观测位与既有契约 ----------


def test_status_exposes_attempt_and_keeps_old_contracts() -> None:
    """⑫⑬⑭ `/hotspots/status` 的新三件，以及被既有套件钉住的两条契约没被挤掉。"""
    _reset()
    hs._state.update({"lastAttemptDate": beijing_today(), "lastAttemptTrigger": "pre-market",
                      "lastAttemptOutcome": "zero-items"})
    hs._write_state()
    s = hs.status()
    check("CR9-95⑫：runs=0 而盘上有今天的 marker ⇒ lastAttempt 读得到、fromDisk=True",
          bool(s.get("lastAttempt")) and s["lastAttempt"]["lastAttemptOutcome"] == "zero-items"
          and s["lastAttemptFromDisk"] is True, str(s.get("lastAttempt"))[:200])

    _reset()
    _run_execute(_Recorder())
    s2 = hs.status()
    check("CR9-95⑬🔁：本进程真跑过一轮 ⇒ lastAttemptFromDisk=False（两格不许同形）",
          s2["runs"] == 1 and s2["lastAttemptFromDisk"] is False
          and bool(s2.get("lastAttempt")), f"runs={s2['runs']} fromDisk={s2['lastAttemptFromDisk']}")

    _reset()
    hs._state.update({"catchUpResolved": beijing_today(), "runs": 3})
    hs._write_state()
    disk_keys = sorted((_read_file() or {}).keys())
    s3 = hs.status()
    check("CR9-95⑭：`catchUpResolved` 仍**不进**状态位文件、`runs` 仍是本进程原义（既有两条 pin）",
          "catchUpResolved" not in disk_keys and s3["runs"] == 3, f"{disk_keys} runs={s3['runs']}")


def test_corrupt_state_file_is_still_tolerated() -> None:
    """⑮ 文件损坏一律当"没有"：新键不许把这条兜底弄破（观测位不能让 status 500）。"""
    _reset()
    with open(_STATE, "w", encoding="utf-8") as f:
        f.write("{ 半截的 JSON")
    s = hs.status()
    check("CR9-95⑮：损坏文件 ⇒ read_state 不抛、status 里 lastAttempt=None、fromDisk=False",
          hs.read_state() is None and s.get("lastAttempt") is None and s["fromDisk"] is False,
          str(s)[:160])
    _reset()
    rec = _Recorder(mid=True)
    _run_decide(at=datetime(2026, 10, 13, 15, 0, tzinfo=hs.TZ), web=_WebQuery(count=0), rec=rec)
    check("CR9-95⑮：盘上读不出（缺失/损坏）⇒ 判「没起过」照常补跑，不许 fail-closed 把当天饿掉",
          rec.calls == 1, f"pipeline={rec.calls}")


def test_unwritable_state_does_not_break_the_round() -> None:
    """⑯ CR9-45：写不进去只 warning＋状态位置 True，那一轮 pipeline 照常跑完。"""
    _reset()
    blocker = os.path.join(_TMPDIR, "blocker")
    with open(blocker, "w", encoding="utf-8") as f:
        f.write("占位：blocker 是个文件，它下面的目录建不出来")
    prev = os.environ["HOTSPOT_STATE_FILE"]
    os.environ["HOTSPOT_STATE_FILE"] = os.path.join(blocker, "sub", "hotspot-state.json")
    rec = _Recorder()
    try:
        res = _run_execute(rec)
        check("CR9-95⑯：状态位写不进去 ⇒ 那一轮照常跑完、返回真结果（观测不得拖垮主功能）",
              rec.calls == 1 and isinstance(res.get("items"), list), str(res)[:120])
        check("CR9-95⑯：写失败要在状态位上留机器可读位（否则保护失效的样子是「什么都不发生」）",
              hs._state.get("stateWriteFailed") is True and hs.status()["stateWriteFailed"] is True,
              str(hs._state.get("stateWriteFailed")))
    finally:
        os.environ["HOTSPOT_STATE_FILE"] = prev
        hs._state["stateWriteFailed"] = False


def test_isolation_from_the_real_state_file() -> None:
    """⑰ 隔离自证：本套件碰的是临时那份，仓库里那份真的没被动过。"""
    check("CR9-95⑰：HOTSPOT_STATE_FILE 指向临时目录且**不是**仓库里那份默认路径",
          hs._state_path() == _STATE and os.path.abspath(_STATE) != os.path.abspath(_DEFAULT_STATE),
          f"{hs._state_path()} vs {_DEFAULT_STATE}")


def main() -> int:
    test_marked_before_pipeline_and_outcome_after()
    test_failed_and_zero_items_are_distinguishable()
    test_date_is_the_start_day_across_midnight()
    test_marker_blocks_recatchup_today()
    test_yesterday_marker_does_not_block()
    test_digest_exists_and_web_failure_branches()
    test_before_schedule_branch()
    test_resolved_still_set_when_marker_blocks()
    test_status_exposes_attempt_and_keeps_old_contracts()
    test_corrupt_state_file_is_still_tolerated()
    test_unwritable_state_does_not_break_the_round()
    test_isolation_from_the_real_state_file()
    passed = sum(1 for _n, ok, _d in results if ok)
    fails = [x for x in results if not x[1]]
    for name, _ok, detail in fails:
        print(f"[FAIL] {name}  <- {detail[:200]}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    shutil.rmtree(_TMPDIR, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
