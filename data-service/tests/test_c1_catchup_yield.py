"""C1（CR7-7）+ CR9-4/CR9-22 离线单测：启动补跑的"让位热点"判据。

背景（2026-09-25 C0 实测实证）：热点补跑（sleep 5s）与同步补跑（sleep 8s）几乎同时
起跑，共用东财令牌桶——同步分页批量占满名额 → pipeline 拿不到 `cooling down` →
当日热点 degraded；且 stock 熔断连坐 hk（4ms 被拒）。C1 的处置是"同步让位热点"。

**CR9-4（2026-09-26）**：C1 原实现把"让位"写成了等**当日有没有 digest 产出**
（`while waited<600: … else: return`，唯一出口是 break）。两种常态下 count 恒为 0：
  ① 02:00–08:30 之间启动——热点侧未到点直接跳过，当日根本不会跑；
  ② 热点跑了但落库 0 行（新闻源全挂 / ingest 被 401 拒）。
两者都会死等到 600s 上限后 `return`，而调度器只在 02:00 触发 ⇒ **当天主数据同步
整日不发生**。修法：让位判据改为"热点正在跑 或 尚未定案"，热点一旦定案
（`scheduler._state["catchUpResolved"]==今天`，跑完/决定不跑/查询失败都算）立即同步。

**CR9-22**：原实现在循环里现编一条 web 查询，且 HTTP 非 2xx 走"继续等"、请求异常
走"直接放行"——同一件事两个方向。现整条删除，故本套件用 ⑦ 断言"不再发这条查询"。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_c1_catchup_yield.py
"""

import json
import os
import shutil
import sys
import tempfile
import time as _time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
# 自带 UTF-8 输出后，跑本脚本不再需要 PYTHONIOENCODING（errors=replace 兜极端情况）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


import app.sync_scheduler as ss  # noqa: E402
from app.utils.timeutil import beijing_today  # noqa: E402

# CR9-94（#68 乙-1）：本套件**必须**把 marker 指到临时文件。真的 `runtime/sync-state.json`
# 在正常日子里就带着今天的日期（当天跑过任何一轮同步就会写）⇒ 不隔离的话，①②⑤⑥⑦⑧⑨⑩⑪
# 全会在新加的第五条早退分支上早退（`ran.n==0`），套件就退化成"只在从没同步过的机器上才绿"。
# 这枚隔离本身就是 CR9-94 交付物的一部分：它让"闸自己变成常绿"这一形在套件层面不可能发生。
_TMPDIR = tempfile.mkdtemp(prefix="c1-catchup-marker-")
os.environ["SYNC_STATE_FILE"] = os.path.join(_TMPDIR, "sync-state.json")
_MARKER = os.environ["SYNC_STATE_FILE"]


def _write_marker(date: str, trigger: str = "startup-catchup", outcome: object = "running") -> None:
    with open(_MARKER, "w", encoding="utf-8") as f:
        json.dump(
            {
                "lastAttemptDate": date,
                "lastAttemptTrigger": trigger,
                "lastAttemptOutcome": outcome,
                "at": "unit-test",
            },
            f,
            ensure_ascii=False,
        )


def _read_marker_file() -> dict | None:
    try:
        with open(_MARKER, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _clear_marker() -> None:
    try:
        os.remove(_MARKER)
    except OSError:
        pass

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


class _FakeHotspot:
    """hotspot.scheduler 的最小替身：只暴露同步侧要读的那几个键。"""

    def __init__(self, running: bool = False, resolved: str | None = None) -> None:
        self._state = {
            "running": running,
            "lastRun": None,
            "lastResult": None,
            "runs": 0,
            "catchUpResolved": resolved,  # CR9-4 新增的定案标志
        }


def _install_hotspot(fake: _FakeHotspot):
    """把真实 hotspot.scheduler 的 _state 换成替身（同步侧按模块属性读取）。"""
    import app.hotspot.scheduler as hs

    orig_state = hs._state
    hs._state = fake._state  # type: ignore[misc]

    def _restore() -> None:
        hs._state = orig_state  # type: ignore[misc]

    return _restore


def _fast_sleep(counts: dict):
    """把循环里的 sleep(10) 变成计数，不真睡；其余 sleep（如启动等待 8s）压到 10ms。"""
    orig = _time.sleep

    def _sleep(s: float) -> None:
        if float(s) == ss.CATCHUP_POLL_INTERVAL_S:
            counts["polls"] += 1
            if counts.get("on_poll"):
                counts["on_poll"](counts["polls"])
            return
        orig(min(float(s), 0.01))

    return orig, _sleep


def _run_case(fake: _FakeHotspot, on_poll=None, forbid_web_query: bool = False,
              at_hour: int = 9, at_minute: int = 0) -> dict:
    """跑一次 _catch_up_if_needed，返回 {ran, polls}。

    forbid_web_query=True 时把 requests 钉成"一旦被调用就抛"，用来证明 CR9-22
    的那条查询确实被删掉了（而不是留着但走了另一条分支）。

    **时刻必须钉住（CR9-35，09-27 00:4x 实测）**：`_catch_up_if_needed` 开头有一道
    "未到当日调度时刻（默认 02:00）就直接 return"的门。本套件此前用它不存在的假设跑
    ——在 00:00–01:59 之间跑，11 个用例里 8 个被这道门静默吞掉（实测 3/11，全是
    `{n:0, polls:0}`）。默认钉到当天 09:00（已过调度点），需要走"未到点"分支的用例
    显式传 `at_hour/at_minute`。
    """
    ran = {"n": 0}
    counts = {"polls": 0, "on_poll": on_poll}
    restore_hs = _install_hotspot(fake)
    orig_run_now = ss.run_now
    orig_time = _time.sleep
    orig_dt = ss.datetime
    builtins_import = __import__("builtins").__import__

    class _PinnedDatetime:
        """只替 `datetime.now(TZ)`（模块内仅此一处用途），日期仍取真实北京今日。"""

        @staticmethod
        def now(tz=None):
            return orig_dt.now(tz or ss.TZ).replace(
                hour=at_hour, minute=at_minute, second=0, microsecond=0
            )

    ss.datetime = _PinnedDatetime  # type: ignore[misc]
    ss.run_now = lambda trigger="manual": (ran.__setitem__("n", ran["n"] + 1),  # type: ignore[assignment]
                                           ran.__setitem__("trigger", trigger),
                                           {"accepted": True})[2]
    if forbid_web_query:
        import builtins

        def _boom(name, *a, **k):
            if name == "requests":
                raise AssertionError("CR9-22：让位循环不应再查询 web /api/hotspots/ingest")
            return builtins_import(name, *a, **k)

        builtins.__import__ = _boom  # type: ignore[assignment]

    orig_sleep, fast = _fast_sleep(counts)
    _time.sleep = fast  # type: ignore[assignment]
    try:
        ss._catch_up_if_needed()
    finally:
        _time.sleep = orig_sleep  # type: ignore[assignment]
        ss.run_now = orig_run_now  # type: ignore[assignment]
        ss.datetime = orig_dt  # type: ignore[misc]
        if forbid_web_query:
            import builtins

            builtins.__import__ = builtins_import  # type: ignore[assignment]
        restore_hs()
    ran["polls"] = counts["polls"]
    return ran


def test_yields_while_hotspot_running() -> None:
    """① 热点在跑 → 等待；跑完并定案后才触发同步（C1 原语义不变）。"""
    fake = _FakeHotspot(running=True, resolved=None)

    def _finish(polls: int) -> None:
        if polls >= 2:  # 第 2 轮：热点结束并定案
            fake._state["running"] = False
            fake._state["catchUpResolved"] = beijing_today()

    r = _run_case(fake, on_poll=_finish)
    check("C1①：热点结束后同步才触发",
          r["n"] == 1 and r.get("trigger") == "startup-catchup", str(r))
    check("C1①：等待期间确实轮询了热点状态", r["polls"] == 2, str(r["polls"]))


def test_proceeds_when_hotspot_resolved_with_output() -> None:
    """② 热点已定案且当日有产出 → 零等待直接同步。"""
    fake = _FakeHotspot(running=False, resolved=beijing_today())
    r = _run_case(fake)
    check("C1②：热点定案且已跑过 → 立即同步（零等待）", r["n"] == 1 and r["polls"] == 0, str(r))


def test_gives_up_when_hotspot_never_finishes() -> None:
    """③ 热点始终在跑 → 600s 上限后放弃本轮（不能压在一个卡死的 pipeline 上）。"""
    fake = _FakeHotspot(running=True, resolved=None)
    r = _run_case(fake)
    check("C1③：热点永不结束 → 到上限放弃本轮（不跑同步）", r["n"] == 0, str(r))
    check("C1③：确实走满了轮询上限", r["polls"] >= int(
        ss.CATCHUP_YIELD_MAX_WAIT_S / ss.CATCHUP_POLL_INTERVAL_S), str(r["polls"]))


def test_skips_when_already_synced_today() -> None:
    """④ 当日已同步（lastDate=今天）→ 跳过（原有语义保持）。"""
    orig_last_date = ss._state.get("lastDate")
    ss._state["lastDate"] = beijing_today()
    try:
        r = _run_case(_FakeHotspot(running=False, resolved=beijing_today()))
        check("C1④：当日已同步 → 跳过（不重复）", r["n"] == 0, str(r))
    finally:
        ss._state["lastDate"] = orig_last_date


def test_cr9_4_before_hotspot_schedule() -> None:
    """⑤ CR9-4 触发路径一：02:00–08:30 启动，热点决定今天不跑（定案、0 产出）。

    旧实现：count 恒 0 → 死等 600s → `return` → **当天同步不发生**。
    新实现：热点已定案 → 立即同步。
    """
    fake = _FakeHotspot(running=False, resolved=beijing_today())  # 决定不跑也算定案
    r = _run_case(fake, forbid_web_query=True)
    check("CR9-4⑤：热点未到点跳过（0 产出）→ 同步照常立即执行", r["n"] == 1 and r["polls"] == 0, str(r))


def test_cr9_4_hotspot_finished_with_zero_rows() -> None:
    """⑥ CR9-4 触发路径二：热点跑了但落库 0 行（新闻源全挂 / ingest 401）。"""
    fake = _FakeHotspot(running=False, resolved=beijing_today())
    fake._state["lastResult"] = {"ok": True, "inserted": 0}  # 跑过，零产出
    r = _run_case(fake, forbid_web_query=True)
    check("CR9-4⑥：热点跑完但 0 行 → 不再死等，同步照常执行", r["n"] == 1, str(r))
    check("CR9-4⑥：定案态生效 = **零轮询死等**（旧实现这里会空转 61 轮到上限）",
          r["polls"] == 0, str(r["polls"]))


def test_cr9_4_never_resolved_still_syncs_at_cap() -> None:
    """⑦ 热点既没在跑也一直没定案（其补跑线程异常/被跳过）→ 到上限**仍要同步**。

    与 ③ 的区别是本判定的落点：仍在跑才放弃，没在跑就不能把当天饿掉。
    """
    fake = _FakeHotspot(running=False, resolved=None)
    r = _run_case(fake)
    check("CR9-4⑦：热点从未定案且未运行 → 到上限仍同步（不是放弃）", r["n"] == 1, str(r))


def test_cr9_22_stale_resolved_from_previous_day() -> None:
    """⑧ 反向对照：定案态必须是**今天**，昨天的 `catchUpResolved` 不算数。

    （若把它当数，跨天重启时同步会在热点真要跑的时候抢先起跑 → 回到 CR7-7 的连坐。）
    """
    fake = _FakeHotspot(running=False, resolved="2026-01-01")
    r = _run_case(fake)
    check("CR9-4⑧：昨日定案不生效（轮询等待，直到上限后同步）",
          r["n"] == 1 and r["polls"] >= int(
              ss.CATCHUP_YIELD_MAX_WAIT_S / ss.CATCHUP_POLL_INTERVAL_S), str(r))


def test_cr9_35_before_schedule_gate_skips_without_polling() -> None:
    """⑨ CR9-35：未到当日调度时刻（默认 02:00）→ 立即跳过，不轮询也不同步。

    这条分支此前**没有任何用例覆盖**：整套 _catch_up_if_needed 测试都在真实墙上时钟
    上跑，00:00–01:59 之间执行时全部用例被这道门吞掉（09-27 00:4x 实测 3/11、
    失败详情一律 `{n:0, polls:0}`）。补上分支覆盖 + 把时刻钉住，两件事一起做。
    """
    fake = _FakeHotspot(running=False, resolved=beijing_today())
    r = _run_case(fake, at_hour=1, at_minute=30)
    check("CR9-35⑨：未到调度时刻 → 立即跳过（不同步、零轮询）",
          r["n"] == 0 and r["polls"] == 0, str(r))
    # 反向对照：同一时刻若已过调度点（SYNC_HOUR=0），必须照常走到同步
    os.environ["SYNC_HOUR"] = "0"
    os.environ["SYNC_MINUTE"] = "0"
    try:
        r2 = _run_case(fake, at_hour=1, at_minute=30)
        check("CR9-35⑨🔁：调度时刻改 00:00 后同一时刻立即同步（证明判定读的是调度点）",
              r2["n"] == 1 and r2["polls"] == 0, str(r2))
    finally:
        os.environ.pop("SYNC_HOUR", None)
        os.environ.pop("SYNC_MINUTE", None)


def test_sync_catchup_off_switch() -> None:
    """⑩ #16（2026-10-01 主人点头）：`SYNC_CATCHUP=off` 只关启动补跑，不关每日 cron。

    这条开关存在的理由就是本套件反复踩的那个耦合：补跑判据与 cron 时刻读同一组
    `SYNC_HOUR/SYNC_MINUTE` ⇒ 过去起一个"不顺手补跑"的 ds 只能撒谎挪时刻，而挪掉的
    正是当晚那档 cron，还得记得在挪到的时刻前停服务。所以断言必须**两条一起**：
    off 确实拦住补跑，且 off **没有**改变 cron 时刻。
    """
    fake = _FakeHotspot(running=False, resolved=beijing_today())
    os.environ["SYNC_CATCHUP"] = "off"
    os.environ["SYNC_HOUR"] = "3"
    os.environ["SYNC_MINUTE"] = "30"
    try:
        r = _run_case(fake, at_hour=9, at_minute=0)
        check("#16⑩：SYNC_CATCHUP=off → 已过调度点也不补跑（零轮询、不 sleep）",
              r["n"] == 0 and r["polls"] == 0, str(r))
        check("#16⑩：off 不得改变 cron 时刻（_sync_hour_minute 仍读配置）",
              ss._sync_hour_minute() == (3, 30), str(ss._sync_hour_minute()))
        # 🔁 反向：同一时刻同一状态，开关回到默认 on 必须照常补跑
        os.environ.pop("SYNC_CATCHUP", None)
        r2 = _run_case(fake, at_hour=9, at_minute=0)
        check("#16⑩：不设开关（默认 on）同一场景照常同步（证明 off 不是恒假桩）",
              r2["n"] == 1 and r2["polls"] == 0, str(r2))
    finally:
        os.environ.pop("SYNC_CATCHUP", None)
        os.environ.pop("SYNC_HOUR", None)
        os.environ.pop("SYNC_MINUTE", None)


def test_skip_reason_written_by_each_early_return() -> None:
    """⑪ #21（10-01 提出、10-02 随刀 3 落地）：四条早退分支都要在状态位上留字面痕迹。

    **第五条**（CR9-94 的磁盘态 marker）不在这里，由 ⑫ 覆盖——它要连"写点／回滚／fail-open"
    一起断言，混进本用例会看不清哪一枚红了。

    为什么不是日志：`sync_scheduler` 的 `log.info` 在 uvicorn 默认配置下**完全不打**
    （10-01 实测整轮同步在 ds 日志里只剩四行启动信息＋访问日志），四条分支此前只能靠
    `/sync/status` ＋ `Product.updatedAt` 反推。`GET /sync/status` 的 `skippedReason`
    现在就是那四条答案的落点。
    """
    saved = dict(ss._state)
    try:
        # (a) SYNC_CATCHUP=off
        os.environ["SYNC_CATCHUP"] = "off"
        try:
            ss._state["skippedReason"] = None
            _run_case(_FakeHotspot(running=False, resolved=beijing_today()),
                      at_hour=9, at_minute=0)
            check("#21⑪：off 分支把原因写进状态位（不再只有一条打不出来的 log.info）",
                  "SYNC_CATCHUP=off" in str(ss._state.get("skippedReason")),
                  str(ss._state.get("skippedReason")))
        finally:
            os.environ.pop("SYNC_CATCHUP", None)

        # (b) 未到调度时刻
        ss._state["skippedReason"] = None
        _run_case(_FakeHotspot(running=False, resolved=beijing_today()),
                  at_hour=1, at_minute=30)
        check("#21⑪：before schedule 分支写原因，并带出当前时刻与调度点（R16 可判定）",
              "before schedule" in str(ss._state.get("skippedReason"))
              and "01:30" in str(ss._state.get("skippedReason")),
              str(ss._state.get("skippedReason")))

        # (c) 当日已同步（lastDate 内存态）
        ss._state["skippedReason"] = None
        ss._state["lastDate"] = beijing_today()
        try:
            _run_case(_FakeHotspot(running=False, resolved=beijing_today()),
                      at_hour=9, at_minute=0)
            check("#21⑪：already synced today 分支写原因，并点明它是**内存态**"
                  "（重启即失效＝待拍板 #23 要治的那个形态）",
                  "already synced today" in str(ss._state.get("skippedReason"))
                  and "内存态" in str(ss._state.get("skippedReason")),
                  str(ss._state.get("skippedReason")))
        finally:
            ss._state["lastDate"] = None

        # (d) 让位热点到上限放弃
        ss._state["skippedReason"] = None
        _run_case(_FakeHotspot(running=True, resolved=None))
        check("#21⑪：热点从未结束 ⇒ 原因写\"让位热点\"（与前三条不同档，不能混读）",
              "hotspot still running" in str(ss._state.get("skippedReason")),
              str(ss._state.get("skippedReason")))

        # 🔁 反向：真触发补跑的那条路径**不写**跳过原因（否则状态位会变成常驻噪声）
        ss._state["skippedReason"] = None
        r = _run_case(_FakeHotspot(running=False, resolved=beijing_today()),
                      at_hour=9, at_minute=0)
        check("🔁 #21⑪：照常补跑的路径不写 skippedReason（证明它不是恒填的桩）",
              r["n"] == 1 and ss._state.get("skippedReason") is None,
              f"{r} / {ss._state.get('skippedReason')}")
    finally:
        ss._state.clear()
        ss._state.update(saved)


def test_cr9_94_disk_attempt_marker() -> None:
    """⑫ CR9-94（#68 乙-1）：跨进程的"今天起过一轮"落盘判据。

    为什么必须有这一枚（10-13 实测代价）：补跑判据只读内存 `_state["lastDate"]`，而 web 的
    #23 磁盘闸比的是"当日**已落库**"（`freshness.listSyncedToday`＝`MAX(updatedAt)` 的北京日）
    ⇒ 只要当天没有一轮真落库（那天 `MAX(updatedAt)` 停在 10-09 02:01），**每重启一次就白买
    一整轮列表**（4 分钟内进程内 `eastmoney granted 47／denied 0`）。

    四枚一起看才成立：(a) 今天⇒拦住；(b) 🔁 昨天⇒照跑（少了它，这条分支就是"永远不跑"的
    常绿牙齿）；(c) 缺文件／损坏⇒照跑（fail-open：通宵没开机那天的补跑比省一次钱重要）；
    (d) 写点在 `run_now` 里真落盘、收尾能覆写 outcome、线程启动失败要回滚。
    """
    saved = dict(ss._state)
    fake = _FakeHotspot(running=False, resolved=beijing_today())
    try:
        # (a) 磁盘＝今天 且内存 lastDate 为空 ⇒ 这正是"重启之后"的真实形态
        ss._state["lastDate"] = None
        ss._state["skippedReason"] = None
        _write_marker(beijing_today(), outcome="rejected")
        r = _run_case(fake, at_hour=9, at_minute=0)
        check("CR9-94⑫：磁盘 marker＝今天 且内存 lastDate 为空 → 不补跑（重启不再白买一轮）",
              r["n"] == 0 and r["polls"] == 0, str(r))
        check("CR9-94⑫：状态位点明是**磁盘态**并带出上一轮 trigger/outcome（一条 curl 分得清）",
              "磁盘态" in str(ss._state.get("skippedReason"))
              and "rejected" in str(ss._state.get("skippedReason")),
              str(ss._state.get("skippedReason")))
        check("CR9-94⑫：文件读得到 ⇒ markerReadError 必须是 None（缺文件不算错，坏文件才算）",
              ss._state.get("markerReadError") is None, str(ss._state.get("markerReadError")))

        # (b) 🔁 反向：昨天的 marker 不算数
        ss._state["skippedReason"] = None
        _write_marker("2026-01-01")
        r2 = _run_case(fake, at_hour=9, at_minute=0)
        check("CR9-94⑫🔁：昨天的 marker 不生效 → 照常补跑（证明这条分支不是恒假桩）",
              r2["n"] == 1 and r2["polls"] == 0, str(r2))

        # (c) fail-open：缺文件 / JSON 损坏 都要放行
        ss._state["skippedReason"] = None
        _clear_marker()
        r3 = _run_case(fake, at_hour=9, at_minute=0)
        check("CR9-94⑫：marker 缺失 → 照常补跑（通宵没开机那天必须放行）",
              r3["n"] == 1 and ss._state.get("markerReadError") is None, str(r3))
        with open(_MARKER, "w", encoding="utf-8") as f:
            f.write("{ 这不是 JSON")
        ss._state["skippedReason"] = None
        r4 = _run_case(fake, at_hour=9, at_minute=0)
        check("CR9-94⑫：marker 损坏 → 照常补跑（fail-open），但错误字面看得见、不许静默",
              r4["n"] == 1 and str(ss._state.get("markerReadError")).startswith("unreadable"),
              str(ss._state.get("markerReadError")))

        # (d) 写点：起跑前落盘 → 收尾覆写 outcome → 线程启动失败要回滚
        _clear_marker()
        ss._state["running"] = False
        orig_execute, orig_threading = ss._execute, ss.threading
        ss._execute = lambda trigger="manual", force=False: None  # type: ignore[assignment]

        class _FakeThreading:
            """只替 `ss.threading` 这一个模块属性，不动真的 threading 模块。"""

            class Thread:
                def __init__(self, *a, **k):
                    raise RuntimeError("unit-test: 线程启动失败")

        try:
            acc = ss.run_now(trigger="unit-test")
            m = _read_marker_file() or {}
            check("CR9-94⑫：run_now 认领成功后**起跑前**就落盘（＝钱已被承诺的那一刻）",
                  acc.get("accepted") is True and m.get("lastAttemptDate") == beijing_today()
                  and m.get("lastAttemptTrigger") == "unit-test"
                  and m.get("lastAttemptOutcome") == "running", str(m))
            check("CR9-94⑫：写成功 ⇒ markerWriteFailed 必须是 False（仪器位不许恒真）",
                  ss._state.get("markerWriteFailed") is False, str(ss._state.get("markerWriteFailed")))
            ss._mark_outcome("unit-test", "completed")
            m2 = _read_marker_file() or {}
            check("CR9-94⑫：收尾覆写真结局，日期沿用起跑那一份（跨午夜的轮不改写归属日）",
                  m2.get("lastAttemptOutcome") == "completed"
                  and m2.get("lastAttemptDate") == beijing_today(), str(m2))
            ss._state["running"] = False  # 上一枚的假 _execute 不会放开 running
            ss.threading = _FakeThreading  # type: ignore[assignment]
            try:
                ss.run_now(trigger="unit-test-boom")
                boom_raised = False
            except RuntimeError:
                boom_raised = True
            check("CR9-94⑫：线程启动失败要抛（CR4 同族，不许把失败吞成 accepted）",
                  boom_raised, "run_now 没抛")
            m3 = _read_marker_file() or {}
            check("CR9-94⑫：线程没起来＝一次网都没出 ⇒ marker 还原成写之前那一份"
                  "（否则零代价锁死一天）",
                  m3.get("lastAttemptOutcome") == "completed"
                  and m3.get("lastAttemptTrigger") == "unit-test", str(m3))
            check("CR9-94⑫：回滚后 running 也已放开（不会永久卡 True）",
                  ss._state.get("running") is False, str(ss._state.get("running")))
        finally:
            ss.threading = orig_threading
            ss._execute = orig_execute  # type: ignore[assignment]
    finally:
        ss._state.clear()
        ss._state.update(saved)
        _clear_marker()


def main() -> int:
    test_yields_while_hotspot_running()
    test_proceeds_when_hotspot_resolved_with_output()
    test_gives_up_when_hotspot_never_finishes()
    test_skips_when_already_synced_today()
    test_cr9_4_before_hotspot_schedule()
    test_cr9_4_hotspot_finished_with_zero_rows()
    test_cr9_4_never_resolved_still_syncs_at_cap()
    test_cr9_22_stale_resolved_from_previous_day()
    test_cr9_35_before_schedule_gate_skips_without_polling()
    test_sync_catchup_off_switch()
    test_skip_reason_written_by_each_early_return()
    test_cr9_94_disk_attempt_marker()
    passed = sum(1 for _n, ok, _d in results if ok)
    fails = [x for x in results if not x[1]]
    for name, _ok, detail in fails:
        print(f"[FAIL] {name}  <- {detail[:160]}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    shutil.rmtree(_TMPDIR, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
