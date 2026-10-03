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

说明：同步本身由 web 侧 `lib/sync.ts` 执行（拉 data-service `/products` → 落库 → 重建 FTS），
data-service 只负责"按时触发"。**刀 3/甲-1（2026-10-02）起一轮有两个动作**：同步腿
`POST /api/sync`（只取列表）收尾后**链式**触发刷新腿 `POST /api/market/refresh?type=all`，
两条腿各拿各的预算——理由与实测基数见下面 `REFRESH_CALLBACK_TIMEOUT_S` 那段。

**当日幂等（#23，主人 2026-10-02 拍板"两道叠加"）**：闸门长在 web 侧（本服务无状态、
不直连库，拿不到"今天落库过没有"这个事实），判据是 `Product` 的两列——
列表看 `MAX(updatedAt)`、刷新看 `MAX(snapshotAt)`。本模块这边只做三件事：
把 `force` 透传下去、认 web 回的行内 `skipped` 标记（整轮都跳过 ⇒ `outcome="skipped"`
第六态 ＋ 一句可 curl 出的 `skippedReason`），以及**保持内存 `lastDate` 原样不动**
（它管"同进程内当天只试一次，含失败轮"，正是 CR9-28 那条被测试钉住的取舍）。
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

# 刀 3/甲-1（2026-10-02，主人"执行推荐方案"轮）：**刷新腿拆出同步事务、自带预算**。
# 依据＝10-01 实网窗口那次打穿预算的归因：一轮 wall ≥1800s，其中 **280 个
# `/quotes?type=fund` 净值批次（28,000 只场外基金）单独占 ≈1,700s**，而取 5 张列表只占
# 头一分钟 ⇒ "一条预算盖两件事"必然要么误记失败要么放任挂死。拆完之后：
#   · 同步腿（web `/api/sync`，只剩取列表）＝沿用上面两个既有数，**不跟着降**——
#     它们是 `test_c3_readtimeout` 钉住的 CR9-33 结论，而拆腿后同步腿的余量已从 1x 变成
#     ~15x，降它零收益、只有"列表抖动日误报 inconclusive"的风险；等有新样本再定。
#   · 刷新腿（web `/api/market/refresh?type=all`）＝本常量。1,700s 是**只算 fund** 的实测
#     基数，其余按 CR9-20 的批次数折算（stock 60 ＋ bond 11 ＋ hk 48 批 × 5s 间隔 ≈600s）
#     ⇒ 全量刷新 ≈2,300s，2,400s 是"盖过推算上界"，不是随手抬一档。
# 甲不消灭那 1,700s，只是把它从"被别人判成超时"挪进"一个知道自己要跑 40 分钟的 job"。
REFRESH_CALLBACK_TIMEOUT_S = 2400.0
REFRESH_URL_PATH = "/api/market/refresh?type=all"
# #33 甲（CR9-60）：刷新腿**自己失败时**去问 web 的进度状态位。这是一次本机 BFF 的只读
# GET（零出网、不占源族桶），预算只给 5s——它是观测，不许把主流程再拖一次（CR9-45 同族）。
PROGRESS_READ_TIMEOUT_S = 5.0

# 只有"web 真的回答完了列表"才值得接刷新腿（见 `_chain_refresh` 那段）。
# #23（主人 10-02 拍板"两道叠加"）之后 `skipped` 也进这一组，理由要说清：
# 同步腿被当日闸门挡下＝**列表这件事今天已经收尾了**（web 用 `MAX(updatedAt)` 作证），
# 而"列表到位、快照没到位"恰恰是最需要补的那一类 ⇒ 不能因为前一条腿跳过就连带废掉后一条。
CHAINED_OUTCOMES = ("completed", "partial_failed", "skipped")


def _callback_timeout_s(trigger: str) -> float:
    """按触发形态取回调读超时（CR9-33）。未知/手动形态按定时态预算。"""
    return CATCHUP_CALLBACK_TIMEOUT_S if trigger == CATCHUP_TRIGGER else SCHEDULED_CALLBACK_TIMEOUT_S

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()
_state: dict = {
    "running": False,
    "lastRun": None,
    "lastDate": None,
    "lastResult": None,
    "runs": 0,
    # #21（10-01 提出、10-02 随刀 3 落地）：`log.info` 在 uvicorn 默认配置下**完全不打**
    # ⇒ "为什么这一轮没跑"必须做成状态位，不能靠翻会被回收的 dev 日志反推。
    "skippedReason": None,
    # 刀 3/甲-1：刷新腿自己的那份结果（None＝本轮根本没走到刷新腿）
    "lastRefresh": None,
}


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


def _refresh_progress() -> dict | None:
    """#33 甲（CR9-60）：刷新腿**被打断**时，进度只能去问 web。

    为什么必须有这一条（10-04 02:11 实测）：本腿那份逐类结果住在 HTTP 响应体里，
    连接被重置（`ConnectionResetError 10054`）就永远拿不到 ⇒ `lastRefresh` 只剩
    `outcome=failed`，我当晚是靠 `MAX(snapshotAt)` 与 `SUM(lastPrice IS NOT NULL)`
    反推出"刷完 stock、fund 跑到第 35 批就断了"。按 #21/CR9-28 的纪律
    **能做成状态位的别做成日志**，所以这里直接把它读回来。

    读回来的是 web 那侧写进 `refresh` 状态位的一份逐类进度（`{startedAt, types,
    current, done[], outcome}`，见 `web/lib/refresh-progress.ts`）。**它顺带把归因变成
    事后可读**：本腿拿到 `ConnectionResetError` 时，若那份进度是 `outcome=completed`
    ⇒ web 自己跑完了、是连接在半途被掐（#33 丙①）；若停在 `running` 且 `current`
    正是当时那一类 ⇒ web 进程根本没走到头（丙②＝dev 在请求进行中重启/重编译）。

    这是**本机 BFF 的一次只读 GET**：不出网、不占任何源族额度；读不到就返回 None
    （观测通道不得把主流程再拖一次，CR9-45 那条"观测与被观测对象抢同一份资源"的教训）。
    只在失败路径调用——成功路径的逐类结果本来就在 `results` 里，多问一次是浪费。
    """
    import requests

    try:
        r = requests.get(f"{_web_base()}/api/health", timeout=PROGRESS_READ_TIMEOUT_S)
        if r.status_code != 200:
            log.warning("refresh progress read: HTTP %s", r.status_code)
            return None
        prog = (r.json() or {}).get("refresh")
        return prog if isinstance(prog, dict) else None
    except Exception as e:  # noqa: BLE001 进度读不到不改变刷新腿自己的结论
        log.warning("refresh progress read failed: %s", e)
        return None


def _refresh_leg(trigger: str, force: bool = False) -> dict:
    """刷新腿（刀 3/甲-1）：`POST /api/market/refresh?type=all`，自带 2400s 预算。

    语义与同步腿同族、不另立一套：`ok` **只在 web 真的回答了时才带真/假**（CR9-28），
    读超时＝`ok=None` ＋ `outcome="inconclusive"`（C3-③：web 侧仍在写，不是失败）。
    差别只在判据来源——web 的这个端点**不返回 `ok`**，所以 `ok` 由逐类 `failedBatches`
    导出（任一类有失败批次即假），而不是替 web 下结论。

    #23：web 侧对**逐类**各自判当日幂等（`snapshotAt` 那一列），整轮都被挡下时
    `results` 里每行都带 `skipped` ⇒ 本腿给 `outcome="skipped"`，既不是 completed
    （没跑却记完成＝撒谎，CR9-28 的同类病）也不是 rejected（那是 4xx）。
    """
    import requests

    started = time.time()
    timeout_s = REFRESH_CALLBACK_TIMEOUT_S
    url = f"{_web_base()}{REFRESH_URL_PATH}" + ("&force=1" if force else "")
    try:
        r = requests.post(url, timeout=timeout_s)
        if r.status_code >= 300:
            out: dict = {
                "ok": None,
                "outcome": "rejected",
                "error": f"HTTP {r.status_code}",
                "body": r.text[:200],
            }
            log.warning("refresh leg rejected: status=%s body=%s", r.status_code, r.text[:200])
            # #33 甲：4xx/5xx 也不该留白——web 回 500 时"到底刷完了几类"只有它自己知道。
            out["progress"] = _refresh_progress()
        else:
            body = r.json() or {}
            results = body.get("results") or []
            weak = [
                str(x.get("type"))
                for x in results
                if isinstance(x, dict) and int(x.get("failedBatches") or 0) > 0
            ]
            held = [
                str(x.get("type"))
                for x in results
                if isinstance(x, dict) and x.get("skipped")
            ]
            all_held = bool(results) and len(held) == len(results)
            out = {
                "ok": not weak,
                "tookMs": body.get("tookMs"),
                "results": results,
                "outcome": "skipped" if all_held else ("partial_failed" if weak else "completed"),
            }
            if all_held:
                out["skippedReason"] = (
                    f"already-refreshed-today: {', '.join(held)}——web 的当日幂等闸门"
                    "（判据 `Product.snapshotAt`＝今日）；确要重刷走 /sync/run?force=true"
                )
                out["note"] = out["skippedReason"]
            if held and not all_held:
                out["skippedTypes"] = held
            if weak:
                out["weakTypes"] = weak
                # 与同步腿同一取舍：只把缺口显式暴露，不自动重试（重试＝再占 40 分钟东财桶）
                out["note"] = (
                    f"部分类型有失败批次：{', '.join(weak)}——这些类的 lastPrice 仍是旧值或 null；"
                    "本轮不自动重试，需要时可 POST /market-refresh 或等下次调度"
                )
                log.warning("refresh leg partially failed: weakTypes=%s", weak)
    except requests.exceptions.ReadTimeout as e:
        out = {
            "ok": None,
            "outcome": "inconclusive",
            "note": (
                f"刷新腿读超时（本次预算 {int(timeout_s)}s，形态 {trigger}）"
                "——快照可能仍在 web 侧写入，本轮结果**未知**；本条不是失败标记"
            ),
            "error": f"{type(e).__name__}: {e}",
        }
        log.warning("refresh leg read timeout (outcome inconclusive): %s", e)
        # 读超时＝web 可能还在写 ⇒ 这时问到的进度是"跑到第几类"的最好证据（丙①/丙② 分档）
        out["progress"] = _refresh_progress()
    except Exception as e:  # noqa: BLE001 单次失败不影响调度
        out = {"ok": None, "error": f"{type(e).__name__}: {e}", "outcome": "failed"}
        log.warning("refresh leg failed: %s", e)
        # #33 甲的主战场：连接被重置（10054）时响应体永远拿不到，本腿只剩 `outcome=failed`。
        # 进度读不到就留 None——**有没有读过**与**读到没读到**是两件事，别用省略冒充。
        out["progress"] = _refresh_progress()

    out["callbackTimeoutS"] = int(timeout_s)
    out["tookMsTotal"] = int((time.time() - started) * 1000)
    return out


def _chain_refresh(trigger: str, sync_result: dict, force: bool = False) -> dict:
    """同步腿收尾后决定是否接刷新腿，并返回刷新腿的结果（刀 3/甲-1）。

    判据不是"成功才刷"这么简单，而是**"web 有没有把列表这件事收尾"**：
      · `completed` / `partial_failed` ⇒ 整表删旧插新已经结束，此刻刷价格写的是最终集合；
      · `skipped`（#23 当日幂等闸门）⇒ 列表**今天已经收尾过**，照样得试刷新腿——
        "列表到位、快照没到位"恰恰是最需要补的那一类；真没事可做时刷新腿自己返回
        `outcome="skipped"`，代价只是两次毫秒级读库，一次网也不出；
      · `inconclusive`（读超时）⇒ web 可能还在写库，两个写事务叠在一起会把刷新结果
        写进**即将被删除的行**（`sync.ts` 的 list 阶段是 DELETE＋INSERT）；
      · `rejected` / `failed` ⇒ web 根本没接活，刷新的还是昨天那批行，等于白花额度。
    """
    outcome = sync_result.get("outcome")
    if outcome in CHAINED_OUTCOMES:
        return _refresh_leg(trigger, force)
    return {
        "ok": None,
        "outcome": "skipped",
        "callbackTimeoutS": int(REFRESH_CALLBACK_TIMEOUT_S),
        "skippedReason": (
            f"同步腿 outcome={outcome} ⇒ 刷新腿不触发："
            + (
                "web 可能仍在写库，此刻刷新会写进即将被删除的行"
                if outcome == "inconclusive"
                else "web 未接活，刷新的仍是上一轮的旧集合"
            )
        ),
    }


def _execute(trigger: str, force: bool = False) -> dict:
    """回调 web /api/sync 并收尾（调用方须已认领 running）。

    状态位不变量（刀 1/#20②）：`ok` **只有在 web 真的回答了时才带真/假值**（CR9-28：
    抄 web 的判定，不自己下结论）；web 没回答（读超时／连接失败／被拒绝）一律
    `ok=None` ＋ `outcome` 说明是哪一种（`inconclusive` / `failed` / `rejected`）。
    「不是失败」不等于「成功」，这个区别必须能被机器读出来。

    #23 加第六态 `skipped`：web 的当日幂等闸门把**整轮**都挡下时，"没跑"既不能记
    completed（没做事却记完成＝撒谎，正是 CR9-28 那个病），也不是 rejected（那才是 4xx）。
    """
    import requests

    started = time.time()
    result: dict
    # C3（CR7-9，2026-09-25）：定时态实测全 5 类型 9.6~13 分钟 → 1800s 保留约 2.3 倍余量。
    # CR9-33（2026-09-27）：预算按**触发形态**取数（补跑态实测 ≥29min，会打穿 1800s），
    # 依据见上面 `SCHEDULED_CALLBACK_TIMEOUT_S` 一组常量；形态由 `trigger` 带进来。
    timeout_s = _callback_timeout_s(trigger)
    # #23(vi)：`force` 由 `POST /sync/run?force=true` 一路透传到这里——没有这个出口，
    # 主人"今天就是要重刷一遍"会撞上自己的闸门（闸门的用途是防手滑，不是防他）。
    url = f"{_web_base()}/api/sync" + ("?force=1" if force else "")
    try:
        r = requests.post(url, timeout=timeout_s)
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
            held = [str(x.get("type")) for x in results if isinstance(x, dict) and x.get("skipped")]
            all_held = bool(results) and len(held) == len(results)
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
                "outcome": "skipped" if all_held else ("partial_failed" if failed else "completed"),
            }
            if all_held:
                result["skippedReason"] = (
                    f"already-synced-today: {', '.join(held)}——web 的当日幂等闸门"
                    "（判据 `Product.updatedAt`＝今日，#23）；"
                    "确要重跑走 POST /sync/run?force=true"
                )
            if held and not all_held:
                # 逐类粒度：只有失败过的那一类当天还能重跑，成功过的不陪着再烧一遍额度
                result["skippedTypes"] = held
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
        # #21＋#23：这一行同时管两件事——真跑起来了 ⇒ 上一条"为什么没跑"作废（None）；
        # 整轮被 web 的当日幂等闸门挡下 ⇒ 把那条原因挂到同一个状态位上，
        # `GET /sync/status` 一条 curl 就分得清"没到点／已经跑过／被闸门跳过"。
        _state["skippedReason"] = result.get("skippedReason")
    result["tookMsTotal"] = int((time.time() - started) * 1000)
    # CR9-33：把本次实际生效的预算回写进状态，`GET /sync/status` 才说得出
    # "这轮用的是哪个形态的预算"（否则超时说明只能靠读代码对）。
    result["callbackTimeoutS"] = int(timeout_s)

    # 刀 3/甲-1：**同步腿收尾后链式触发刷新腿**。放在状态写入之后、`running` 放开之前
    # ⇒ 单飞（`run_now` 只看 `running`）自动覆盖整轮两条腿，刷新还在跑时再点同步会被挡。
    # 为什么不排成第二个 cron：拆腿后列表阶段会把新行的 lastPrice 抹成 null（整表删旧插新），
    # 两个固定时刻之间的间隔就是"分类浏览无价"的窗口——链式触发把它压到只剩一次 HTTP 往返。
    refresh = _chain_refresh(trigger, result, force)
    with _lock:
        _state["lastRefresh"] = refresh
        _state["running"] = False
    return result


def run_now(trigger: str = "manual", force: bool = False) -> dict:
    """手动/补跑触发（C4/CR7-10 异步化，2026-09-25 拍板）。

    此前在请求线程内同步跑完整个同步（15min+ 级），HTTP 请求全程挂着；
    照 `hotspot/scheduler.request_run` 模板改：认领 running 后由后台线程
    执行，立即返回 `{accepted}`。线程启动失败须回滚 running（CR4 同类修复：
    否则永久卡 True，后续手动触发全部 skipped）。
    进度观测：`GET /sync/status`（running 字段 + 最近一次 results）。
    ⚠️ 刀 3/甲-1 之后 `running` **覆盖整轮两条腿**（同步腿＋链式刷新腿）⇒ 刷新还在跑时
    这里同样返回未认领，这正是我们要的：手动补跑不会叠在一条正在写快照的腿上。
    `force`（#23(vi)）＝越过 web 侧的当日幂等闸门，两条腿都带过去。
    """
    with _lock:
        if _state["running"]:
            return {
                "accepted": False,
                "note": "daily sync already running（同步腿或链式刷新腿未收尾，见 /sync/status 的 lastRefresh）",
            }
        _state["running"] = True
        # #21：走到"认领成功"这一步，上一条"为什么没跑"就此作废（清空只放在这一个入口，
        # 三条触发路径——cron／手动／启动补跑——都经过这里）
        _state["skippedReason"] = None
    try:
        threading.Thread(
            target=_execute, args=(trigger, force), name="sync-manual", daemon=True
        ).start()
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


def _set_skip(reason: str) -> None:
    """#21：把"这一轮为什么没跑"写进状态位。

    为什么必须是状态位而不是日志：`sync_scheduler` 的 `log.info` 在 uvicorn 默认配置下
    **完全不打**（10-01 实测：整轮同步在 ds 日志里只剩四行启动信息＋访问日志），
    而 dev 日志会被回收、也不会被任何门禁断言读 ⇒ 只能靠 `Product.updatedAt` 反推。
    """
    with _lock:
        _state["skippedReason"] = reason
    log.info("sync skipped: %s", reason)


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

    下面四条早退分支**都要留下机器可读的去向**（#21，10-02 随刀 3 落地）——
    四条都写成 `skippedReason`，`GET /sync/status` 一条 curl 就能分清是哪一条。
    """
    if _catchup_disabled():
        _set_skip("catchup: SYNC_CATCHUP=off（每日 cron 不受影响）")
        return
    time.sleep(8)  # 等 web 就绪（web 侧迁移/启动）
    hour, minute = _sync_hour_minute()
    now = datetime.now(TZ)
    if (now.hour, now.minute) < (hour, minute):
        _set_skip(f"catchup: before schedule（现在 {now:%H:%M} < 调度点 {hour:02d}:{minute:02d}）")
        return
    if _state.get("lastDate") == beijing_today():
        _set_skip("catchup: already synced today（lastDate 命中，内存态）")
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
            # #21：这条同样要能被 `/sync/status` 读出来——它是"今天为什么没同步"的
            # 第四个答案，而 warning 只在日志里、门禁不读日志。
            _set_skip(
                f"catchup: hotspot still running after {int(CATCHUP_YIELD_MAX_WAIT_S)}s"
                "（让位热点，本轮放弃）"
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
        # #21：一条 curl 就能读出"上一轮为什么没跑"（off／未到点／当日已同步／让位热点超时），
        # 这些原因此前只存在于 `log.info` 里，而 uvicorn 默认配置根本不打 info。
        "skippedReason": _state.get("skippedReason"),
        # 刀 3/甲-1：刷新腿那份结果（含它自己的 outcome／预算／skippedReason）
        "lastRefresh": _state.get("lastRefresh"),
        "jobs": jobs,
        "timezone": str(TZ),
    }
