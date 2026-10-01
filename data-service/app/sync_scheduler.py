"""产品主数据每日同步调度（G2 / 批次 D，本轮 code review）。

背景：M2 要求「每日全量同步产品列表到 Product」，但此前 APScheduler 只调度热点，
`/api/sync` 只能手动触发 → 主数据（A股/基金/转债/加密列表）不自动更新，
搜索与分类浏览会逐渐过期。

设计（复用热点调度的基础设施与约定）：
- BackgroundScheduler，TZ=Asia/Shanghai
- 每日一次，默认 02:00（盘后/凌晨，避开交易时段与外部源限流高峰；env 可覆盖）
- 回调 web BFF `POST /api/sync`（data-service 不直连库，产出落库统一模式）
- 单飞：同进程内不并发；失败只记录不抛出（不影响调度继续）
- 启动补跑：重启后若当日未同步且已过调度时刻则补跑一次（与热点一致）

说明：同步本身由 web 侧 `lib/sync.ts` 执行（拉 data-service `/products` → 落库 →
重建 FTS → 刷新行情快照），data-service 只负责"按时触发"。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .utils.timeutil import beijing_today

log = logging.getLogger("sync.scheduler")

TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_SYNC_HOUR = 2
DEFAULT_SYNC_MINUTE = 0

# C1/CR9-4：启动补跑让位热点的轮询参数（上限 10min，与热点侧 300s 预算 + 单飞相称）
CATCHUP_POLL_INTERVAL_S = 10.0
CATCHUP_YIELD_MAX_WAIT_S = 600.0

# CR9-33（2026-09-27）：回调 web 的读超时**按触发形态分别取数**。
# 一轮同步的耗时实测差一个数量级，单一预算必然要么误记失败要么放任挂死：
#   · 定时态（到点就跑、东财空闲）runs=1 逐类 tookMs 合计约 **430s**
#     （fund 358 / stock 41 / crypto 43 / bond 1.3 / hk 4ms）
#   · 补跑态（重启后 catch-up：与热点争抢同一源族桶、常撞在冷却窗口上）
#     09-26 实测 **≥29 分钟仍未收敛**，当时 1800s 第一次真被打穿
# ⇒ 补跑态给 2700s（≥29min 实测 + 约 55% 余量），其余形态沿用 C3/CR7-9 的 1800s
#    （定时态 4.2 倍余量）。web 侧 `maxDuration=1500` 仍小于两者，维持"web 先结束、
#    ds 不把已成功的同步误记为失败"的口径（读超时的中性标注见 C3-③）。
# ⚠️ 冷却日仍可能超过本预算——真护栏是源族桶自身（docs/CONSTRAINTS.md C-5），
#    这里只保证"预算与实际形态同量级"，不假装能盖住最坏情况。
SCHEDULED_CALLBACK_TIMEOUT_S = 1800.0
CATCHUP_CALLBACK_TIMEOUT_S = 2700.0
CATCHUP_TRIGGER = "startup-catchup"


def _callback_timeout_s(trigger: str) -> float:
    """按触发形态取回调读超时（CR9-33）。未知/手动形态按定时态预算。"""
    return CATCHUP_CALLBACK_TIMEOUT_S if trigger == CATCHUP_TRIGGER else SCHEDULED_CALLBACK_TIMEOUT_S

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()
_state: dict = {"running": False, "lastRun": None, "lastDate": None, "lastResult": None, "runs": 0}


def _sync_hour_minute() -> tuple[int, int]:
    """调度时刻（env SYNC_HOUR / SYNC_MINUTE 可覆盖，非法值回落默认）。"""
    try:
        hour = int(os.environ.get("SYNC_HOUR", str(DEFAULT_SYNC_HOUR)))
    except ValueError:
        hour = DEFAULT_SYNC_HOUR
    try:
        minute = int(os.environ.get("SYNC_MINUTE", str(DEFAULT_SYNC_MINUTE)))
    except ValueError:
        minute = DEFAULT_SYNC_MINUTE
    return max(0, min(hour, 23)), max(0, min(minute, 59))


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:3000")


def _execute(trigger: str) -> dict:
    """回调 web /api/sync 并收尾（调用方须已认领 running）。

    状态位不变量（刀 1/#20②）：`ok` **只有在 web 真的回答了时才带真/假值**（CR9-28：
    抄 web 的判定，不自己下结论）；web 没回答（读超时／连接失败／被拒绝）一律
    `ok=None` ＋ `outcome` 说明是哪一种（`inconclusive` / `failed` / `rejected`）。
    「不是失败」不等于「成功」，这个区别必须能被机器读出来。
    """
    import requests

    started = time.time()
    result: dict
    # C3（CR7-9，2026-09-25）：定时态实测全 5 类型 9.6~13 分钟 → 1800s 保留约 2.3 倍余量。
    # CR9-33（2026-09-27）：预算按**触发形态**取数（补跑态实测 ≥29min，会打穿 1800s），
    # 依据见上面 `SCHEDULED_CALLBACK_TIMEOUT_S` 一组常量；形态由 `trigger` 带进来。
    timeout_s = _callback_timeout_s(trigger)
    try:
        r = requests.post(f"{_web_base()}/api/sync", timeout=timeout_s)
        if r.status_code >= 300:
            result = {
                "ok": None,
                "outcome": "rejected",
                "error": f"HTTP {r.status_code}",
                "body": r.text[:200],
            }
            log.warning("daily sync rejected: status=%s body=%s", r.status_code, r.text[:200])
        else:
            body = r.json() or {}
            results = body.get("results") or []
            failed = [str(x.get("type")) for x in results if isinstance(x, dict) and x.get("error")]
            # CR9-28：web 侧返回的是真 ok（`results.every(r => !r.error)`），
            # 此前这里硬写 `ok: True` → 5 类里 4 类失败也被记成"同步成功"
            # （09-26 实测：lastResult.ok=true，而 stock/bond/crypto/hk 全带 error）。
            # 状态失真会让"看 /sync/status 判断今天是否要补跑"这条唯一路径失效。
            # 刀 1（#20②）：与 `ok` 并列一个 `outcome`——`ok` 只有真/假两值，表达不了
            # "web 根本没回答"这种第三态（见下面的 ReadTimeout 分支）。
            result = {
                "ok": bool(body.get("ok")),
                "tookMs": body.get("tookMs"),
                "results": results,
                "outcome": "partial_failed" if failed else "completed",
            }
            if failed:
                result["failedTypes"] = failed
                # 失败类型不自动重试是有意取舍：整轮同步实测 9.6~13min，
                # 反复重试会持续占东财源族（CR7-7/C1 的让位逻辑同样怕这个）。
                # 因此只把缺口显式暴露出来，交给人/下次调度决定。
                result["note"] = (
                    f"部分类型失败：{', '.join(failed)}——lastDate 已置位，"
                    f"本轮不自动重试；需要时可 POST /sync/run 或等下次调度"
                )
                log.warning("daily sync partially failed: ok=false failedTypes=%s", failed)
            else:
                log.info("daily sync done: %s", result)
    except requests.exceptions.ReadTimeout as e:
        # C3-③（CR7-9，2026-09-25）：**读超时 ≠ 同步失败**——web 侧仍在后台执行
        # （ds 只是不再等结果），且 lastDate 已在下方置位不再重跑。此前把这种情况
        # 记成 error 会与"实际已成功的同步"矛盾（状态失真）。
        #
        # 刀 1（#20②，2026-10-01 主人点头改判）：中性标注**不再等于 `ok=True`**。
        # 10-01 实测把这条语义逼到了台面上：健康态一轮 wall ≥1800s，**正好打穿定时态
        # 预算**（`tookMsTotal=1800030`），而那一轮真入库的只有 fund（其余 3 条腿 502、
        # bond 未写入）——状态位却写着 `ok:true`。也就是说"读超时可能仍会成功"这个
        # 原意成立，但把它编码成 `ok=True` 会让 `/sync/status` 在定时态**恒为真**，
        # CR9-28 要它保住的"今天要不要补跑"判据再次失效（同根、未覆盖的分支）。
        # ⇒ 第三态：`ok=None`（未知，不是真也不是假）＋ `outcome="inconclusive"`，
        #   error 字段照旧保留原始异常供排查。
        result = {
            "ok": None,
            "outcome": "inconclusive",
            "note": (
                f"回调读超时（本次预算 {int(timeout_s)}s，形态 {trigger}）"
                "——同步可能仍在 web 侧完成，也可能没有：本轮结果**未知**，"
                "请查 Product.updatedAt / snapshotAt 或 web 侧日志；本条不是失败标记"
            ),
            "error": f"{type(e).__name__}: {e}",
        }
        log.warning("daily sync callback read timeout (outcome inconclusive, sync may still complete on web side): %s", e)
    except Exception as e:  # noqa: BLE001 调度不因单次失败而中断
        result = {"ok": None, "error": f"{type(e).__name__}: {e}", "outcome": "failed"}
        log.warning("daily sync failed: %s", e)

    with _lock:
        _state["lastRun"] = datetime.now(TZ).isoformat(timespec="seconds")
        _state["lastDate"] = beijing_today()
        _state["lastResult"] = result
        _state["runs"] += 1
        _state["running"] = False
    result["tookMsTotal"] = int((time.time() - started) * 1000)
    # CR9-33：把本次实际生效的预算回写进状态，`GET /sync/status` 才说得出
    # "这轮用的是哪个形态的预算"（否则超时说明只能靠读代码对）。
    result["callbackTimeoutS"] = int(timeout_s)
    return result


def run_now(trigger: str = "manual") -> dict:
    """手动/补跑触发（C4/CR7-10 异步化，2026-09-25 拍板）。

    此前在请求线程内同步跑完整个同步（15min+ 级），HTTP 请求全程挂着；
    照 `hotspot/scheduler.request_run` 模板改：认领 running 后由后台线程
    执行，立即返回 `{accepted}`。线程启动失败须回滚 running（CR4 同类修复：
    否则永久卡 True，后续手动触发全部 skipped）。
    进度观测：`GET /sync/status`（running 字段 + 最近一次 results）。
    """
    with _lock:
        if _state["running"]:
            return {"accepted": False, "note": "daily sync already running"}
        _state["running"] = True
    try:
        threading.Thread(target=_execute, args=(trigger,), name="sync-manual", daemon=True).start()
    except Exception:  # noqa: BLE001 CR4：线程启动失败要回滚 running，否则永久卡 True
        with _lock:
            _state["running"] = False
        raise
    return {"accepted": True, "note": "已提交后台执行，进度见 /sync/status"}


def _catchup_disabled() -> bool:
    """`SYNC_CATCHUP=off` 只关**启动补跑**，**不关**每日 cron（`:247` 仍按 SYNC_HOUR 触发）。

    为什么需要它（待拍板 #16，主人 2026-10-01 点头）：补跑判据（`:190`）与 cron 时刻
    （`:247-251`）读的是**同一组** `SYNC_HOUR/SYNC_MINUTE` ⇒ 过去想"起一个不会顺手补跑
    同步的健康 ds"，唯一手段是把调度时刻撒谎到未来，而那一谎同时挪走了当晚的 cron，
    还必须记得在撒谎到的时刻之前停服务（09-29、09-30 两夜都靠手动 kill 躲过）。
    有了这个开关，起干净 ds 不再需要撒谎，也没有"忘了停就真跑一轮"的雷。
    """
    return os.environ.get("SYNC_CATCHUP", "on").strip().lower() == "off"


def _catch_up_if_needed() -> None:
    """重启后若已过当日调度时刻且当日未同步 → 补跑一次。

    C1（CR7-7，2026-09-25）：与热点补跑（hotspot/scheduler._catch_up_if_needed，
    sleep 5s 先起跑）共用东财令牌桶——同步的分页批量会长时间占满 min_interval=5s，
    pipeline 的 `_EM.acquire(timeout=15)` 拿不到名额即抛 cooling down，
    HOTSPOT_PIPELINE_TIMEOUT_S=300 预算被等待吃光 → 当日热点 degraded。
    C0 实测（2026-09-25）当场实证：stock 熔断 → hk 4ms 被拒（同源族连坐）。

    处置：**同步让位热点**——热点 pipeline 在跑或尚未产出当日 digest 时等待；
    热点结束后（或当日已有产出）再跑同步。轮询上限 10 分钟：热点侧自身有
    300s 预算 + 单飞，超上限按超时放弃本轮补跑（下个调度周期 02:00 再试）。
    """
    if _catchup_disabled():
        log.info("sync catch-up skipped: SYNC_CATCHUP=off（每日 cron 不受影响）")
        return
    time.sleep(8)  # 等 web 就绪（web 侧迁移/启动）
    hour, minute = _sync_hour_minute()
    now = datetime.now(TZ)
    if (now.hour, now.minute) < (hour, minute):
        log.info("sync catch-up skipped: before schedule")
        return
    if _state.get("lastDate") == beijing_today():
        log.info("sync catch-up skipped: already synced today")
        return

    # C1（CR7-7）让位热点。**CR9-4/CR9-22 修正（2026-09-26）**：
    # 原实现等的是"当日有没有 digest 产出"，那个判据在两种常态下永远不满足——
    #   ① 02:00–08:30 之间启动：热点侧 `scheduler._catch_up_decide` 未到点直接跳过，
    #      当日不会有任何产出；
    #   ② 热点跑了但落库 0 行（新闻源全挂 / ingest 被 401 拒）。
    # 两者都表现为 count==0，于是 `while … else: return` 死等满 600s 后**整轮放弃**，
    # 而调度器只在 02:00 触发 ⇒ 当天主数据同步根本不发生。
    # 现改为只让位给"真的会与之争抢东财令牌"的热点：**正在跑** 或 **尚未定案**；
    # 热点一旦定案（跑完/决定不跑/查询失败）就立即同步，不再反推它有没有产出。
    # 顺带删掉这条 web 查询——原来 HTTP 非 2xx 走"继续等"、请求异常走"直接放行"，
    # 同一件事两种方向（CR9-22）。
    from .hotspot import scheduler as hotspot_scheduler

    today = beijing_today()
    waited = 0.0
    while waited < CATCHUP_YIELD_MAX_WAIT_S:
        st = hotspot_scheduler._state
        if not st["running"]:
            if st.get("catchUpResolved") == today:
                log.info("sync catch-up: hotspot resolved for today, no need to yield")
                break
            log.info("sync catch-up: hotspot not started/resolved (%.0fs)...", waited)
        else:
            log.info("sync catch-up: hotspot pipeline running (%.0fs)...", waited)
        time.sleep(CATCHUP_POLL_INTERVAL_S)
        waited += CATCHUP_POLL_INTERVAL_S
    else:
        # 到上限：热点仍在跑 → 放弃本轮（不能压在一个卡死的 pipeline 上）；
        # 热点没在跑却迟迟没定案（其补跑线程异常/被跳过）→ 照常同步，别把当天饿掉。
        if hotspot_scheduler._state["running"]:
            log.warning(
                "sync catch-up: hotspot still running after %.0fs, giving up this round",
                CATCHUP_YIELD_MAX_WAIT_S,
            )
            return
        log.warning(
            "sync catch-up: hotspot never resolved within %.0fs, syncing anyway",
            CATCHUP_YIELD_MAX_WAIT_S,
        )

    # 无法确知"当日是否已同步"（同步状态在 web 侧，未持久化）→ 保守补跑一次：
    # 单飞 + 空载荷保护（C1）已能兜住重复同步的安全性。
    log.info("sync catch-up: running daily sync now")
    run_now(trigger=CATCHUP_TRIGGER)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    hour, minute = _sync_hour_minute()
    _scheduler = BackgroundScheduler(timezone=str(TZ))
    _scheduler.add_job(
        lambda: run_now("daily"),
        CronTrigger(hour=hour, minute=minute),
        id="daily-product-sync",
        replace_existing=True,
        misfire_grace_time=1800,
        coalesce=True,
    )
    _scheduler.start()
    threading.Thread(target=_catch_up_if_needed, daemon=True, name="sync-catchup").start()
    log.info("product sync scheduler started: daily %02d:%02d (Asia/Shanghai)", hour, minute)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> dict:
    jobs = []
    if _scheduler is not None:
        for j in _scheduler.get_jobs():
            jobs.append({"id": j.id, "nextRun": str(j.next_run_time)})
    return {
        "running": _state["running"],
        "runs": _state["runs"],
        "lastRun": _state["lastRun"],
        "lastDate": _state["lastDate"],
        "lastResult": _state["lastResult"],
        "jobs": jobs,
        "timezone": str(TZ),
    }
