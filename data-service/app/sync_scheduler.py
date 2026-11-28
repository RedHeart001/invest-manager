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

**CR9-94（#68 乙-1，主人 2026-10-13「确认按这个方案落码」）起的第四件事**：把
"今天这台机器**起过**一轮同步"也落盘（`runtime/sync-state.json`）。为什么 web 那道
#23 磁盘闸不够——它比的是"当日**已落库**"（`freshness.listSyncedToday`＝
`MAX(updatedAt)` 的北京日），答不出"当日**已试过**"；于是只要当天没有一轮真落库
（10-13 实测：`MAX(updatedAt)` 停在 10-09 02:01），**每重启一次就白买一整轮列表**
（那一次 4 分钟内进程内 `eastmoney granted 47／denied 0`）。三枚判据因此各管一格、
互不替换：内存 `lastDate`＝本进程当天只试一次／web 的 #23＝逐类"已落库就别再出网"／
盘上 `lastAttemptDate`＝跨进程的"今天试过没有"。**只在启动补跑那一条路上读**——
cron 与手动 `POST /sync/run` 两条路都不读它，主人的两个既有出口一行没改。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .utils.http import direct_proxies
from .utils.timeutil import beijing_today, leg_staleness

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
# ⇒ 补跑态给 2700s（≥29min 实测 + 约 55% 余量）。
# 11-12 美股乙：定时态 1800 → **2500**——us 列表全量（上限 950 页、早停按实盘）名义 ≈950s，
# 加其余五类（10-17 基线 ≈540s＋stock 修复后 324s）整轮名义 ≈1506s、最坏 ≈2086s，1800 的余量已不足。
# 2500 刻意避开 2400（REFRESH）与 2700（CATCHUP）：test_c3_readtimeout 的牙齿要求
# 三种形态预算互不相同（日志归因要分得清是哪条腿）。web 侧 maxDuration 同批抬到 2400，
# 仍小于本值，维持"web 先结束、ds 不把已成功的同步误记为失败"的口径（中性标注见 C3-③）。
# ⚠️ 冷却日仍可能超过本预算——真护栏是源族桶自身（docs/CONSTRAINTS.md C-5），
#    这里只保证"预算与实际形态同量级"，不假装能盖住最坏情况。
SCHEDULED_CALLBACK_TIMEOUT_S = 2500.0
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
CHAINED_OUTCOMES = ("completed", "partial_failed", "skipped", "collecting")

# ---------- W3（2026-11-27）：失败类型的有界自动补试 ----------
# 从"失败不自动重试"改成"失败类型最多补试一次"是**经确认的策略变更**，但边界收得很紧：
#   · 只补自然轮（`trigger="daily"`）失败的那几类，不重买整轮；
#   · 每日最多 1 次、延迟 30 分钟（够 web 侧异步收尾，也还在凌晨的低峰里）；
#   · **不带 `force`** ⇒ 仍受 web 当日幂等闸门约束，成功过的那类不会再出网；
#   · `inconclusive` 不补（结果未知时重跑只会把额度花在可能已经成功的一轮上）；
#   · `us` 不补（它由 `us_list_job` 的持久化任务按页续跑，与五类是两条账）；
#   · 启动补跑、手动轮不繁衍补试（否则一次重启就能把"每天一次"放大成任意次）。
RETRY_TRIGGER = "daily-retry"
RETRY_DELAY_S = 30 * 60
RETRY_MAX_ATTEMPTS = 1
#: 到点时主任务还在跑 ⇒ 先让位再试，但不许无限等（等不到就记 `cancelled`，当日不再自动执行）。
RETRY_WAIT_INTERVAL_S = 60.0
RETRY_WAIT_MAX = 10
#: 不参与补试的类型：us 的采集与发布在 `us_list_job` 里自己续跑。
RETRY_EXCLUDED_TYPES = ("us",)
RETRY_STATES = ("pending", "running", "completed", "exhausted", "cancelled")

#: web 刷新端点认识的类型全集（`app/api/market/refresh/route.ts` 的 `SNAPSHOT_TYPES`）。
#: 补试轮用它把 `exclude` 算出去（只刷失败类型，见 `_refresh_leg` 的 `types`）。
SNAPSHOT_ALL_TYPES = ("stock", "fund", "bond", "crypto", "hk", "us")

#: 自然轮的触发字面量（`cron` 那条入口）。**只认它**才登记补试：启动补跑与手动轮
#: 都是"人/重启额外要的一轮"，从它们繁衍补试会让"每天最多一次"退化成任意次。
DAILY_TRIGGER = "daily"


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
    # CR9-94（#68 乙-1）：落盘 marker 自己的两枚"仪器有没有坏"位。fail-open 是有意取舍
    # （读不出就当"今天没试过"，通宵没开机那天的补跑比省一次钱重要），但**不许静默**——
    # `:242` 那条纪律：有没有读过与读到没读到是两件事，别用省略冒充。
    "markerReadError": None,
    "markerWriteFailed": False,
    # W3：补试计划的内存镜像（盘上那份是真相，见 `_retry_state()`）。
    # `None`＝今天没有待执行的补试；有值时形如 `{"date","state","attempt",...}`。
    "retry": None,
    "retryLastResult": None,
}


# CR9-94（#68 乙-1）：跨进程的"今天起过一轮"落盘件。形状照 `hotspot-state.json`
# （`hotspot/scheduler.py:46-88`）／`limiter-state.json`（`utils/limiter.py:216`）那一族：
# 覆写、先 `.tmp` 再 `os.replace`（读者看不到半截）、不回显绝对路径、写不进只 `log.warning`
# （CR9-45：观测位不得拖垮主功能）。**按北京日取值**，不是布尔——`hotspot/scheduler.py:260`
# 那句"`catchUpResolved` 更不许从盘上捞"防的就是"昨天的定案值放到今天"，带日期的形状不受它影响。
SYNC_STATE_NAME = "sync-state.json"


def _sync_state_path() -> str:
    """落点默认 `data-service/runtime/sync-state.json`（该目录已在 `.gitignore`）。

    `SYNC_STATE_FILE` 可整条覆盖——离线单测靠它指向临时目录，**绝不碰仓库里那份真的**
    （否则套件会把 marker 写进真文件，之后任何一次重启都被静默挡掉＝闸自己变成常绿）。
    """
    env = os.environ.get("SYNC_STATE_FILE", "")
    if env:
        return env
    # CR9-102（#72）：本文件在 `app/` 下（非 `app/utils/`、非 `app/hotspot/`），
    # dirname×3 会落到**仓库根**、且那份 runtime/ 不在 .gitignore ⇒ 用 ×2 落
    # `data-service/runtime/`，与 limiter/hotspot 两份状态文件同语义。
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "runtime", SYNC_STATE_NAME)


def _read_marker() -> tuple[dict | None, str | None]:
    """返回 `(数据, 错误字面)`。错误分三形：`missing`（正常态）／`unreadable:<类型>`／
    `not-an-object`——后两形要能被 `/sync/status` 读出来，缺文件不算错。"""
    try:
        with open(_sync_state_path(), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as e:
        return None, f"unreadable: {type(e).__name__}"
    if not isinstance(data, dict):
        return None, "not-an-object"
    return data, None


def read_sync_state() -> dict | None:
    """读回磁盘那份 marker；缺失／损坏／非对象一律当"没有"，**不抛**（观测位不许让 status 500）。"""
    return _read_marker()[0]


def _write_marker(payload: dict) -> bool:
    path = _sync_state_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError) as e:
        log.warning("sync state could not be written: %s", e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _mark_attempt(trigger: str) -> tuple[dict | None, bool]:
    """起跑前落"今天这台机器起过一轮"。返回 `(写之前盘上那一份, 是否写成功)`。

    时机＝**钱已被承诺的那一刻**：列表腿随后按源族桶 `min_interval=5s` 逐发买东财
    （一整轮 ≈244s／≈48 发，与 web 日志 `POST /api/sync 200 in 244167ms` 同量级）。
    写在收尾而不是起跑，就会留下今天 18:57 那一形的漏洞——被 kill 的轮钱已花、盘上无痕迹。
    """
    prev, _ = _read_marker()
    payload = {
        "lastAttemptDate": beijing_today(),
        "lastAttemptTrigger": trigger,
        "lastAttemptOutcome": "running",
        "at": datetime.now(TZ).isoformat(timespec="seconds"),
    }
    # W3：`retry` 是**正交**的一位（今天要不要补试），不许被"又起了一轮"顺手抹掉——
    # 否则 02:10 一次手动/启动补跑就会静默吃掉 02:30 那次排好的补试。
    if isinstance((prev or {}).get("retry"), dict):
        payload["retry"] = prev["retry"]
    ok = _write_marker(payload)
    with _lock:
        _state["markerWriteFailed"] = not ok
    return prev, ok


def _unmark_attempt(prev: dict | None, wrote: bool) -> None:
    """线程启动失败的回滚（CR4 同族，见 `run_now` 里那条 `running` 回滚）。

    不回滚就会把当天吃掉，而代价是一分钱都没花——那是最坏的一种失败形态。
    """
    if not wrote:
        return
    if prev is None:
        try:
            os.remove(_sync_state_path())
        except OSError as e:
            log.warning("sync state rollback could not remove file: %s", e)
        return
    _write_marker(prev)


def _mark_outcome(trigger: str, outcome: object, result: dict | None = None) -> None:
    """收尾覆写真结局（成功与失败两条出口都要写，照 hotspot `_execute` 的 `finally` 口径）。

    为什么要 outcome 而不只是一个日期：它把"今天试过"分成两种——「试过且结局是
    `rejected`／`inconclusive`／`partial_failed`」与「试过且 `completed`，可
    `Product.updatedAt` 还是旧的」。后者才是更该 alarm 的那一形，而这一枚是它唯一
    零出网可读的仪器（#69 那枚账缺的就是这个）。日期沿用**起跑时**那一份：跨午夜的轮
    不该把昨天的起跑记成今天。

    10-18（追加九十二 刀 C）再多带一份 `lastResult`：热点腿那份状态文件自 CR9-62 起就把
    `lastResult` 一起落盘，同步腿只落 marker ⇒ 逐类 `note`（例：`sina.us-list` 那句
    「只取前排 N 页」）**只住在内存**、重启即失（现存三枚 `/sync/status` 回执逐枚
    `lastResult=null` 实证）。字段名跟着写点的语义走＝"那一轮的结果快照"，与
    `_state["lastResult"]`／`status()` 同名同形；旧格式那份文件没有这个键 ⇒ 读侧回落 None。
    """
    prev, _ = _read_marker()
    payload = {
        "lastAttemptDate": (prev or {}).get("lastAttemptDate") or beijing_today(),
        "lastAttemptTrigger": (prev or {}).get("lastAttemptTrigger") or trigger,
        "lastAttemptOutcome": outcome,
        "at": datetime.now(TZ).isoformat(timespec="seconds"),
        "lastResult": result,
    }
    # W3：`retry` 与 `lastAttempt*` 是两个不相干的问题（"今天补不补" / "今天自然轮结局"），
    # 收尾覆写必须把它原样带过去。丢了它＝重启后不知道还有一次补试没跑（也读不出
    # `exhausted`／`cancelled` 的现场），而这一刻正是"刚失败、最需要那张计划还活着"的时候。
    if isinstance((prev or {}).get("retry"), dict):
        payload["retry"] = prev["retry"]
    ok = _write_marker(payload)
    with _lock:
        _state["markerWriteFailed"] = not ok


_finalize_lock = threading.Lock()


def _finalize_collecting_from_us(us_status: dict | None = None) -> bool:
    """把「五类已完成、美股仍在采集」的当日 marker 幂等收尾为 `completed`。

    CR10-51（2026-11-28 自然轮）：02:09 五类收尾时美股还在持久化采集，marker 正确写
    `collecting`；02:26 美股发布并刷新完成后，`us_list_job` 只写自己的状态，没有人回写
    同步 marker ⇒ `/sync/status` 永久停在 `collecting`，watcher 也等不到终态。

    这里只做**状态收尾**：不采集、不发布、不刷新、不排补试、不伪造整轮耗时。判据必须
    同时成立才推进；任一不成立就原样返回 False（幂等空操作）。写盘前再读一次并与第一次
    读到的 marker 全等比较，避免把期间新起的一轮（手动／跨日）覆盖掉。
    """
    if us_status is None:
        from . import us_list_job

        us_status = us_list_job.status()
    if not isinstance(us_status, dict):
        return False
    if us_status.get("state") != "completed" or us_status.get("refreshOutcome") != "completed":
        return False
    today = beijing_today()
    if us_status.get("completedDate") != today:
        return False
    snapshot_id = us_status.get("snapshotId")
    if not snapshot_id:
        return False

    with _finalize_lock:
        marker = read_sync_state()
        if not isinstance(marker, dict):
            return False
        if marker.get("lastAttemptTrigger") != DAILY_TRIGGER:
            return False
        if marker.get("lastAttemptOutcome") != "collecting":
            return False
        if marker.get("lastAttemptDate") != today:
            return False
        result = marker.get("lastResult")
        if not isinstance(result, dict):
            return False
        collecting_types = result.get("collectingTypes")
        if not isinstance(collecting_types, list) or "us" not in collecting_types:
            return False
        results = result.get("results")
        if not isinstance(results, list) or not results:
            return False
        # 原五类必须没有错误；有任何 failedTypes／逐类 error 都不许借美股完成洗白。
        if result.get("failedTypes"):
            return False
        if any(isinstance(row, dict) and row.get("error") for row in results):
            return False
        us_row = next(
            (row for row in results if isinstance(row, dict) and row.get("type") == "us"),
            None,
        )
        if us_row is None:
            return False

        finalized_at = datetime.now(TZ).isoformat(timespec="seconds")
        new_results = []
        for row in results:
            if isinstance(row, dict) and row.get("type") == "us":
                new_results.append(
                    {
                        "type": "us",
                        "count": us_status.get("publishedCount"),
                        "snapshotId": snapshot_id,
                        "jobState": "completed",
                        "published": True,
                        "refreshOutcome": "completed",
                        "note": "persistent us list job completed and refreshed",
                    }
                )
            else:
                new_results.append(row)
        new_result = {
            **result,
            "ok": True,
            "outcome": "completed",
            "results": new_results,
            "note": "美股完整名单已发布并完成刷新：collecting 收尾为 completed（未重复发布/刷新）",
            "finalizedFrom": "collecting",
            "finalizedAt": finalized_at,
            "usSnapshotId": snapshot_id,
            "usCompletedAt": us_status.get("lastCompletedAt"),
        }
        new_result.pop("collectingTypes", None)
        payload = {**marker, "lastAttemptOutcome": "completed", "lastResult": new_result}

        if read_sync_state() != marker:
            log.warning("sync collecting finalize skipped: marker changed while checking")
            return False
        if not _write_marker(payload):
            return False
        with _lock:
            in_proc = _state.get("lastResult")
            if isinstance(in_proc, dict) and in_proc.get("outcome") == "collecting":
                _state["lastResult"] = new_result
        log.info(
            "sync collecting finalized from us job: snapshot=%s completedAt=%s",
            snapshot_id,
            us_status.get("lastCompletedAt"),
        )
        return True


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


# ---------- W3：补试状态机（`sync-state.json` 的 `retry` 键） ----------


def retry_state() -> dict | None:
    """读盘上那份补试计划；缺失／损坏／形状不对一律当"没有"（观测位不许让 status 500）。

    只认 `state` 在 `RETRY_STATES` 里的对象——手改出来的 `{"state":"whatever"}` 当没有，
    而不是当成某个未知状态继续跑（那会让"当日最多一次"失去判据）。
    """
    data = _read_marker()[0] or {}
    plan = data.get("retry")
    if not isinstance(plan, dict):
        return None
    if plan.get("state") not in RETRY_STATES:
        return None
    return plan


def _write_retry(plan: dict | None) -> bool:
    """原子写 `retry` 键：保留 marker 其余键（`lastAttempt*`／`lastResult`）一字不动。

    `plan=None` ⇒ 删键（今天没有待执行计划）。写盘失败**返回 False 并挂状态位**，
    不许假装已安排——这正是 `_write_marker` 那条 fail-open 纪律的同一族。
    """
    data = _read_marker()[0] or {}
    if plan is None:
        data.pop("retry", None)
    else:
        data["retry"] = plan
    ok = _write_marker(data)
    with _lock:
        _state["markerWriteFailed"] = not ok
        _state["retry"] = plan
    if not ok:
        log.warning("retry plan could not be written to sync state (state=%s)", (plan or {}).get("state"))
    return ok


def _retry_due_at(delay_s: float = RETRY_DELAY_S) -> str:
    """现在 + 延迟（ISO，带 +08:00）。用北京时区是为了盘上那份人能直接读。"""
    return (datetime.now(TZ) + timedelta(seconds=delay_s)).isoformat(timespec="seconds")


def _plan_retry(failed_types: list[str], reason: str) -> dict | None:
    """自然轮失败后登记一次补试计划（每日最多一次，同一天不重复登记）。

    判据顺序都是"宁可少补，不可多补"：
      ① 没有失败类型 ⇒ 不登记（返回 None）；
      ② 失败类型里全是 us（或 `RETRY_EXCLUDED_TYPES` 的子集）⇒ 不登记，us 自己续跑；
      ③ 今天已经有 plan ⇒ 不覆盖（`exhausted`／`cancelled` 也照旧，当日不再自动执行）；
      ④ 写盘失败 ⇒ 不登记（内存里也不留，否则重启后又"想补"）。
    """
    types = [t for t in failed_types if t and t not in RETRY_EXCLUDED_TYPES]
    if not types:
        return None
    existing = retry_state()
    if existing and existing.get("date") == beijing_today():
        log.info("retry already planned today: state=%s", existing.get("state"))
        return None
    plan = {
        "date": beijing_today(),
        "state": "pending",
        "attempt": 0,
        "maxAttempts": RETRY_MAX_ATTEMPTS,
        "types": types,
        "notBefore": _retry_due_at(),
        "reason": reason,
        "plannedAt": datetime.now(TZ).isoformat(timespec="seconds"),
    }
    if not _write_retry(plan):
        return None
    log.info("retry planned: types=%s notBefore=%s", types, plan["notBefore"])
    return plan


def _transition_retry(expect: tuple[str, ...], **changes) -> dict | None:
    """条件迁移：只有盘上 `state` 在 `expect` 里才改，否则返回 None（不覆盖别人的决定）。

    这是"补试不许自我繁衍"的实际闸门：`pending → running` 只有一次能成功；已经
    `completed`／`exhausted`／`cancelled` 的当天计划不会被任何迟到线程改回来。
    """
    plan = retry_state()
    if not plan or plan.get("state") not in expect:
        return None
    plan = {**plan, **changes, "updatedAt": datetime.now(TZ).isoformat(timespec="seconds")}
    if not _write_retry(plan):
        return None
    return plan


def _cancel_retry(reason: str) -> dict | None:
    """把今日计划标成 `cancelled`（不删键＝留下的现场还能读出来）。"""
    return _transition_retry(("pending", "running"), state="cancelled", cancelReason=reason)


def _retry_types_from(result: dict) -> list[str]:
    """从一轮结果里取"该补的失败类型"。

    只有 `outcome="partial_failed"` 才有失败类型可补：
      · `completed`／`skipped` ⇒ 没有失败；
      · `collecting` ⇒ 列表都到位了，us 在持久化任务里续跑；
      · `inconclusive` ⇒ **结果未知**，重跑可能把额度花在已经成功的一轮上，不补；
      · `rejected`／`failed` ⇒ web 根本没接活，重跑同一条路只会再撞一次。
    """
    if result.get("outcome") != "partial_failed":
        return []
    failed = [str(t) for t in (result.get("failedTypes") or []) if t]
    return [t for t in failed if t not in RETRY_EXCLUDED_TYPES]


def _claim_for_retry(max_wait: int = RETRY_WAIT_MAX) -> bool:
    """等到主轮收尾并**原子地**认领 `running`（补试与主轮共用同一把单飞锁）。

    判据只有一个 `_state["running"]`：同步腿与链式刷新腿都由它覆盖（见 `run_now` 的
    注释），所以补试绝不会叠在一条正在写快照的腿上。等不到就返回 False，调用方记
    `cancelled`——不许把补试排成第二支并发（那是"不增加并发"这条边界的实际落点）。
    """
    for i in range(max_wait):
        with _lock:
            if not _state["running"]:
                _state["running"] = True
                return True
        log.info("retry waiting for running sync (%ss)", int((i + 1) * RETRY_WAIT_INTERVAL_S))
        time.sleep(RETRY_WAIT_INTERVAL_S)
    with _lock:
        if _state["running"]:
            return False
        _state["running"] = True
        return True


def _retry_worker(due_at: str) -> None:
    """补试的执行体（后台线程）：等 `notBefore` → 认领 → 只跑失败类型 → 收尾。

    「带上失败类型」靠 `_execute_types(types=...)`，不走 `run_now`——后者固定五类、会把
    `running`／marker 按"整轮"重写，而补试**不是**今天"又起了一轮"（marker 的
    `lastAttemptTrigger` 必须还是 `daily`，否则自然轮的结局被篡改、`legStaleness` 也会算错）。
    """
    try:
        due = datetime.fromisoformat(due_at)
    except ValueError:
        _cancel_retry(f"invalid notBefore: {due_at!r}")
        return
    while True:
        wait_s = (due - datetime.now(TZ)).total_seconds()
        if wait_s <= 0:
            break
        time.sleep(min(wait_s, 60.0))

    plan = retry_state()
    if not plan or plan.get("state") != "pending" or plan.get("date") != beijing_today():
        # 到点时计划已被换掉／已过期（跨日）⇒ 什么都不做（条件迁移自己会失败）。
        _cancel_retry("due but plan is no longer pending for today")
        return

    claimed = _transition_retry(
        ("pending",), state="running", startedAt=datetime.now(TZ).isoformat(timespec="seconds")
    )
    if not claimed:
        return  # 别人先认领了（或已被取消）
    types = [str(t) for t in (claimed.get("types") or [])]
    if not types:
        _transition_retry(("running",), state="cancelled", cancelReason="no types to retry")
        return

    if not _claim_for_retry():
        _transition_retry(("running",), state="cancelled", cancelReason="sync still running when retry became due")
        return

    log.info("retry start: types=%s", types)
    try:
        result = _execute_types(RETRY_TRIGGER, types, force=False)
    except Exception as e:  # noqa: BLE001 补试线程自己的失败要落成状态，不能静默死掉
        result = {"ok": None, "outcome": "failed", "error": f"{type(e).__name__}: {e}"}
        log.warning("retry crashed: %s", e)
    finally:
        with _lock:
            _state["running"] = False

    with _lock:
        _state["retryLastResult"] = result
    attempt = int(claimed.get("attempt") or 0) + 1
    if result.get("outcome") in ("completed", "skipped"):
        _transition_retry(
            ("running",),
            state="completed",
            attempt=attempt,
            finishedAt=datetime.now(TZ).isoformat(timespec="seconds"),
            outcome=result.get("outcome"),
        )
    else:
        # 仍失败／结果未知／被拒 ⇒ 当日不再自动补试（`exhausted`，不回到 pending）。
        _transition_retry(
            ("running",),
            state="exhausted",
            attempt=attempt,
            finishedAt=datetime.now(TZ).isoformat(timespec="seconds"),
            outcome=result.get("outcome"),
            error=result.get("error"),
            note=result.get("note"),
        )
    log.info("retry done: outcome=%s", result.get("outcome"))


def _schedule_retry(plan: dict | None) -> None:
    """把盘上的 `pending` 计划挂到一个后台线程（重启后恢复未执行计划＝同一个入口）。

    幂等性靠 `_transition_retry` 的条件迁移：两个线程同时到点，只有先把
    `pending → running` 写成功的那一个会真跑（另一个在 `claimed` 处直接返回）。
    """
    if not plan or plan.get("state") != "pending":
        return
    if plan.get("date") != beijing_today():
        _cancel_retry(f"plan date {plan.get('date')} is not today")
        return
    due_at = str(plan.get("notBefore") or "")
    threading.Thread(
        target=_retry_worker, args=(due_at,), name="sync-retry", daemon=True
    ).start()


def _web_base() -> str:
    # 默认值用 127.0.0.1 而非 localhost：Windows 的 localhost 先解析成 ::1，
    # 而 web 只监听 IPv4，Python 的 urllib/requests 会先撞一次空端口再回落（每次约 2s）。
    # 容器内由 compose 显式给 http://web:3000，不受此默认值影响。
    return os.environ.get("WEB_BASE_URL", "http://127.0.0.1:3000")


def _write_headers() -> dict[str, str]:
    """G7 最小版（CR10-7）：web 的 `requireWriteToken` 一旦配值，本文件这两条腿是它**唯一的
    调用方**——不带头就是当晚同步腿＋链式刷新腿双双 401，而 `run_now` 在认领那一刻已把
    当日 marker 落下（CR9-94），于是这一天不会再自动补跑。

    未配＝返回 `{}`，与 `web/.env` 空值那一档同形（`guard.ts` 的 `?? ""` 放行），本机默认态
    行为一字不变。照 `research/tasks.py:130` 的形状在**调用时**读 env，不 module-level 固化，
    这样 `load_env()` 的先后不影响取值。⚠️ 值只进请求头，任何分支不得打印。
    """
    token = os.environ.get("WRITE_TOKEN", "")
    return {"x-write-token": token} if token else {}


def _refresh_progress(run_id: str | None = None) -> dict | None:
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
        suffix = f"?refreshRunId={run_id}" if run_id else ""
        r = requests.get(f"{_web_base()}/api/health{suffix}", timeout=PROGRESS_READ_TIMEOUT_S, proxies=direct_proxies())
        if r.status_code != 200:
            log.warning("refresh progress read: HTTP %s", r.status_code)
            return None
        prog = (r.json() or {}).get("refresh")
        return prog if isinstance(prog, dict) else None
    except Exception as e:  # noqa: BLE001 进度读不到不改变刷新腿自己的结论
        log.warning("refresh progress read failed: %s", e)
        return None


def _refresh_leg(trigger: str, force: bool = False, types: list[str] | None = None) -> dict:
    """刷新腿（刀 3/甲-1）：`POST /api/market/refresh?type=all`，自带 2400s 预算。

    语义与同步腿同族、不另立一套：`ok` **只在 web 真的回答了时才带真/假**（CR9-28），
    读超时＝`ok=None` ＋ `outcome="inconclusive"`（C3-③：web 侧仍在写，不是失败）。
    差别只在判据来源——web 的这个端点**不返回 `ok`**，所以 `ok` 由逐类 `failedBatches`
    导出（任一类有失败批次即假），而不是替 web 下结论。

    #23：web 侧对**逐类**各自判当日幂等（`snapshotAt` 那一列），整轮都被挡下时
    `results` 里每行都带 `skipped` ⇒ 本腿给 `outcome="skipped"`，既不是 completed
    （没跑却记完成＝撒谎，CR9-28 的同类病）也不是 rejected（那是 4xx）。

    W3：`types` 非空时**只刷这几类**（补试专用）——用 `exclude` 把其余类型剔掉，
    而不是加一个新的 `types=` 参数：web 那侧只有 `type=all|单个` 两档，用 `exclude`
    不需要动契约。补试若把全市场重刷一遍，既超出"只补失败类型"，也会把成功类的
    `snapshotAt` 抬到今日，混掉"今天哪几条腿真的重新取过数"这条读数。
    """
    import requests

    started = time.time()
    timeout_s = REFRESH_CALLBACK_TIMEOUT_S
    # CR10-49：普通轮不刷新尚未发布的旧 us；us 发布后由持久化任务单独刷新。
    # W3：补试轮的 runId 另起一支——两轮写的是同一份 `refresh-progress.json`，
    # 同名会互相覆盖，事后就看不出"那一轮到底跑了谁"。
    run_id = f"daily-{beijing_today()}" if types is None else f"retry-{beijing_today()}"
    if types is None:
        exclude = ["us"]
    else:
        exclude = [t for t in SNAPSHOT_ALL_TYPES if t not in types]
    url = (
        f"{_web_base()}{REFRESH_URL_PATH}&exclude={','.join(exclude)}&runId={run_id}"
        + ("&force=1" if force else "")
    )
    try:
        r = requests.post(url, timeout=timeout_s, headers=_write_headers(), proxies=direct_proxies())
        if r.status_code >= 300:
            out: dict = {
                "ok": None,
                "outcome": "rejected",
                "error": f"HTTP {r.status_code}",
                "body": r.text[:200],
            }
            log.warning("refresh leg rejected: status=%s body=%s", r.status_code, r.text[:200])
            # #33 甲：4xx/5xx 也不该留白——web 回 500 时"到底刷完了几类"只有它自己知道。
            out["progress"] = _refresh_progress(run_id)
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
        out["progress"] = _refresh_progress(run_id)
    except Exception as e:  # noqa: BLE001 单次失败不影响调度
        out = {"ok": None, "error": f"{type(e).__name__}: {e}", "outcome": "failed"}
        log.warning("refresh leg failed: %s", e)
        # #33 甲的主战场：连接被重置（10054）时响应体永远拿不到，本腿只剩 `outcome=failed`。
        # 进度读不到就留 None——**有没有读过**与**读到没读到**是两件事，别用省略冒充。
        out["progress"] = _refresh_progress(run_id)

    out["callbackTimeoutS"] = int(timeout_s)
    out["tookMsTotal"] = int((time.time() - started) * 1000)
    # CR10-51：给刷新腿留下“哪一轮、何时收尾”，供 watcher 区分本轮与上一轮遗留的
    # `_state["lastRefresh"]`（进程跨日不重启时，旧值会一直挂在内存里）。
    out["runId"] = run_id
    out["finishedAt"] = datetime.now(TZ).isoformat(timespec="seconds")
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
    """每日整轮（五类 + us）。W3 起是 `_execute_types(None)` 的薄包装。

    保留这个名字与签名的原因：`run_now`／测试／日志都按它引用，而"整轮"与"只补几类"
    的差别只在传不传 `types`——拆成两个同名不同义的函数反而会让"顺势多跑两类"变成
    一行改动就能做到的事。
    """
    return _execute_types(trigger, None, force)


def _execute_types(trigger: str, types: list[str] | None = None, force: bool = False) -> dict:
    """回调 web /api/sync 并收尾（调用方须已认领 running）。

    状态位不变量（刀 1/#20②）：`ok` **只有在 web 真的回答了时才带真/假值**（CR9-28：
    抄 web 的判定，不自己下结论）；web 没回答（读超时／连接失败／被拒绝）一律
    `ok=None` ＋ `outcome` 说明是哪一种（`inconclusive` / `failed` / `rejected`）。
    「不是失败」不等于「成功」，这个区别必须能被机器读出来。

    #23 加第六态 `skipped`：web 的当日幂等闸门把**整轮**都挡下时，"没跑"既不能记
    completed（没做事却记完成＝撒谎，正是 CR9-28 那个病），也不是 rejected（那才是 4xx）。

    W3：`types` 非空＝**补试轮**（`trigger="daily-retry"`）。三处刻意不同：
      ① URL 只带这几类（`?types=stock,crypto`），成功过的类型零出网；
      ② `us` 一律不碰——它由 `us_list_job` 的持久化任务按页续跑，与五类两条账；
      ③ 不写 marker、不动 `lastDate`／`running`：补试不是"今天又起了一轮"，
         marker 的 `lastAttemptTrigger` 必须还是 `daily`，否则自然轮的结局被篡改掉。
    """
    import requests

    started = time.time()
    result: dict
    retry_mode = types is not None
    # C3（CR7-9，2026-09-25）：定时态实测全 5 类型 9.6~13 分钟 → 1800s 保留约 2.3 倍余量。
    # CR9-33（2026-09-27）：预算按**触发形态**取数（补跑态实测 ≥29min，会打穿 1800s），
    # 依据见上面 `SCHEDULED_CALLBACK_TIMEOUT_S` 一组常量；形态由 `trigger` 带进来。
    timeout_s = _callback_timeout_s(trigger)
    # #23(vi)：`force` 由 `POST /sync/run?force=true` 一路透传到这里——没有这个出口，
    # 主人"今天就是要重刷一遍"会撞上自己的闸门（闸门的用途是防手滑，不是防他）。
    # CR10-49：普通轮只同步五类；us 由持久化任务单独采集，不再让一次 HTTP 背 923 页。
    if retry_mode:
        wanted = [t for t in types if t not in RETRY_EXCLUDED_TYPES]
        url = f"{_web_base()}/api/sync?types={','.join(wanted)}"
    else:
        url = f"{_web_base()}/api/sync?types=fund,stock,bond,crypto,hk"
    if force:
        url += "&force=1"
    try:
        r = requests.post(url, timeout=timeout_s, headers=_write_headers(), proxies=direct_proxies())
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
            if retry_mode:
                # 补试轮只合并本次涉及的类；us 不在本轮范围内（它自己续跑），
                # 也不追加 us 回执——否则"补试结果"会看起来像又跑了一整轮。
                us_state, us_result, us_collecting = "skipped", None, False
            else:
                # CR10-49：五类收尾后启动/恢复美股持久化任务。它不在本 HTTP 请求里翻页，
                # 所以“还在采集”只记 collecting，不写 completed，也不写 failed。
                from . import us_list_job

                job = us_list_job.ensure_running(trigger, force=force)
                job_status = job.get("status") or us_list_job.status()
                us_state = str(job_status.get("state") or "idle")
                us_snapshot = job_status.get("snapshotId")
                if us_state == "completed":
                    us_result: dict = {
                        "type": "us",
                        "count": job_status.get("publishedCount"),
                        "snapshotId": us_snapshot,
                        "jobState": us_state,
                        "published": True,
                        "note": "persistent us list job completed and refreshed",
                    }
                elif us_state == "blocked":
                    us_result = {
                        "type": "us",
                        "error": f"us list job blocked: {job_status.get('blockedReason')}",
                        "jobState": us_state,
                        "snapshotId": us_snapshot,
                    }
                else:
                    us_result = {
                        "type": "us",
                        "collecting": True,
                        "jobState": us_state,
                        "snapshotId": us_snapshot,
                        "progress": job_status.get("progress"),
                        "resolvedPages": job_status.get("resolvedPages"),
                        "requiredPages": job_status.get("requiredPages"),
                        "pendingPages": job_status.get("pendingPages"),
                        "lastProgressAt": job_status.get("lastProgressAt"),
                        "nextAttemptAt": job_status.get("nextAttemptAt"),
                        "note": (
                            "美股完整名单正在持久化采集中；正式 Product 未改动，旧数据继续可用。"
                            "完整候选通过全部完整性验证后才会发布，并单独刷新 us 行情。"
                        ),
                    }
                results.append(us_result)
            failed = [str(x.get("type")) for x in results if isinstance(x, dict) and x.get("error")]
            held = [str(x.get("type")) for x in results if isinstance(x, dict) and x.get("skipped")]
            us_collecting = bool(us_result.get("collecting")) if us_result else False
            # 分母跟着本轮**请求了谁**走：整轮是五类，补试轮是「本轮那几类」。
            # 写死 5 会让补试轮永远判不出"整轮被挡"（补试只请求 2 类时 held=2），
            # 于是"web 说这几类今天已经做完了"被记成 completed——又是一种没做事记完成。
            # `expected > 0` 那一道是防"空名单"：`all_held` 对空集合恒真＝把没请求记成跳过。
            expected = len(wanted) if retry_mode else 5
            all_held = expected > 0 and len(held) == expected and (retry_mode or us_state == "completed")
            # CR9-28：web 侧返回的是真 ok（`results.every(r => !r.error)`），
            # 此前这里硬写 `ok: True` → 5 类里 4 类失败也被记成"同步成功"
            # （09-26 实测：lastResult.ok=true，而 stock/bond/crypto/hk 全带 error）。
            # 状态失真会让"看 /sync/status 判断今天是否要补跑"这条唯一路径失效。
            # 刀 1（#20②）：与 `ok` 并列一个 `outcome`——`ok` 只有真/假两值，表达不了
            # "web 根本没回答"这种第三态（见下面的 ReadTimeout 分支）。
            # CR10-49：collecting 不是成功也不是失败 ⇒ ok=None + outcome="collecting"。
            if failed:
                ok_value: bool | None = False
            elif us_collecting:
                ok_value = None
            else:
                ok_value = bool(body.get("ok"))
            result = {
                "ok": ok_value,
                "tookMs": body.get("tookMs"),
                "results": results,
                "outcome": (
                    "partial_failed"
                    if failed
                    else ("collecting" if us_collecting else ("skipped" if all_held else "completed"))
                ),
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
            if us_collecting:
                result["collectingTypes"] = ["us"]
            if failed:
                result["failedTypes"] = failed
                # 失败类型不无限重试是有意取舍：整轮同步实测 9.6~13min，
                # 反复重试会持续占东财源族（CR7-7/C1 的让位逻辑同样怕这个）。
                # W3 起自然轮会安排**一次**有界补试（下面 `_plan_retry` 那段覆写这句 note），
                # 其余触发形态（手动／启动补跑）仍只暴露缺口，不自动加码。
                result["note"] = (
                    f"部分类型失败：{', '.join(failed)}——lastDate 已置位，"
                    f"本轮不自动重试；需要时可 POST /sync/run 或等下次调度"
                )
                log.warning("daily sync partially failed: ok=false failedTypes=%s", failed)
            elif us_collecting:
                result["note"] = (
                    "美股完整名单仍在持久化采集中（collecting）——不是失败；"
                    "旧数据继续可用，完整候选发布后会单独刷新 us。"
                )
                log.info("daily sync collecting: us job state=%s", us_state)
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

    if retry_mode:
        # W3：补试轮**不动**整轮状态位——`lastRun`／`lastDate`／`runs`／marker 都是
        # "今天自然轮"的账，补试写进去就会把自然轮的结局盖掉（`runs` 尤其：它的义是
        # "本进程跑了几轮整轮"）。补试的结果另有 `retry` 计划与 `retryLastResult` 两处。
        result["retryTypes"] = [t for t in (types or []) if t not in RETRY_EXCLUDED_TYPES]
        result["tookMsTotal"] = int((time.time() - started) * 1000)
        result["callbackTimeoutS"] = int(timeout_s)
        # W3 收尾修正（11-27 现查）：上面 `failed` 分支那句 note 是**整轮**语境的
        # （"lastDate 已置位，本轮不自动重试"）。在补试轮里它自相矛盾——这一轮本身就是
        # 那次重试——而且它不含任何一类的原因原文，盘上只剩一句"失败"。这里按补试语境改写：
        # 点名这一轮补了谁、为什么还失败、以及「今天到此为止」（别让人以为 30 分钟后还会再来）。
        per_type = [
            f"{x.get('type')}: {x.get('error')}"
            for x in (result.get("results") or [])
            if isinstance(x, dict) and x.get("error")
        ]
        if result.get("failedTypes"):
            result["note"] = (
                f"补试仍失败：{', '.join(result.get('failedTypes') or [])}"
                f"（{'; '.join(per_type)[:300]}）"
                "——今日不再自动重试；旧数据保留，确要重跑走 POST /sync/run?force=true"
            )
        elif result.get("outcome") == "inconclusive":
            result["note"] = (
                "补试结果未知（回调读超时）——web 侧可能仍在写；"
                "今日不再自动重试，请查 Product.updatedAt／snapshotAt"
            )
        _mark_retry_outcome(result)
        # 刷新腿**只覆盖本轮涉及的类**：`exclude` 把其余类型剔掉。补试若顺手刷全市场，
        # 既超出"只补失败类型"的边界，也会把成功类的 `snapshotAt` 抬到今日、
        # 混掉"今天哪几条腿真的重新取过数"这条读数。
        refresh = _refresh_leg(RETRY_TRIGGER, force, types=result["retryTypes"])
        with _lock:
            _state["retryLastRefresh"] = refresh
        result["refresh"] = refresh
        return result

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
    # CR9-94：同步腿的真结局覆写进 marker。放在这里而不是整轮收尾——刷新腿还要 ≈40min，
    # 而"钱已经花完"这件事在同步腿收尾这一刻就成立了（被 kill 的轮也要留下结局）。
    # 10-18 刀 C：往下挪两行＝等 `tookMsTotal`／`callbackTimeoutS` 都写完再落盘，
    # 否则落进盘上的那份 `lastResult` 会比内存那份少两个键（同一个名字两种形状）。
    _mark_outcome(trigger, result.get("outcome"), result)

    # CR10-51：美股可能在“读 status → 写 collecting marker”之间完成（竞态）。写盘后
    # 立即再检查一次；不成立就保持 collecting，由美股完成回调或启动恢复继续收尾。
    if trigger == DAILY_TRIGGER and result.get("outcome") == "collecting":
        _finalize_collecting_from_us()

    # W3：自然轮失败 ⇒ 登记一次有界补试（每日最多一次、延迟 30 分钟、不带 force）。
    # 放在 `_mark_outcome` 之后＝"自然轮的结局"先落定，再登记"要不要补"；
    # 顺序反过来的话，一次写盘失败会让 marker 缺失而补试计划还在，重启后无法归因。
    # 触发形态闸门：只有 `daily`（02:00 cron）才繁衍补试。启动补跑是"今天还没试过"那一支，
    # 手动轮是主人当场要的，两者的失败要么已有一次补跑机会、要么人就在现场 ⇒ 不自动加码。
    retry_types = _retry_types_from(result) if trigger == DAILY_TRIGGER else []
    if retry_types:
        plan = _plan_retry(retry_types, f"{trigger} partial_failed")
        if plan:
            result["retryPlanned"] = {
                "state": plan["state"],
                "types": plan["types"],
                "notBefore": plan["notBefore"],
                "maxAttempts": plan["maxAttempts"],
            }
            # note 里那句"本轮不自动重试"从 W3 起不成立了——改成如实说明已安排什么。
            result["note"] = (
                f"部分类型失败：{', '.join(result.get('failedTypes') or [])}"
                f"——已保留旧数据，并安排一次自动补试（{', '.join(plan['types'])}，"
                f"{plan['notBefore'][11:16]} 起、每日最多一次、不带 force）；"
                "也可 POST /sync/run?force=true 立即重跑"
            )
            _schedule_retry(plan)
    elif result.get("outcome") == "partial_failed":
        result["note"] = (
            f"部分类型失败：{', '.join(result.get('failedTypes') or [])}"
            "——失败类型只有 us（由持久化任务自行续跑），不排补试；"
            "旧数据保留，确要重跑走 POST /sync/run?force=true"
        )

    # 刀 3/甲-1：**同步腿收尾后链式触发刷新腿**。放在状态写入之后、`running` 放开之前
    # ⇒ 单飞（`run_now` 只看 `running`）自动覆盖整轮两条腿，刷新还在跑时再点同步会被挡。
    # 为什么不排成第二个 cron：拆腿后列表阶段会把新行的 lastPrice 抹成 null（整表删旧插新），
    # 两个固定时刻之间的间隔就是"分类浏览无价"的窗口——链式触发把它压到只剩一次 HTTP 往返。
    refresh = _chain_refresh(trigger, result, force)
    with _lock:
        _state["lastRefresh"] = refresh
        _state["running"] = False
    return result


def _mark_retry_outcome(result: dict) -> None:
    """补试轮的结果落盘（`retry.lastResult`），不碰 marker 的 `lastAttempt*`。

    为什么要单独一处：`_mark_outcome` 会把 `lastAttemptTrigger` 写成 `daily-retry`，
    而那一位的语义是"今天自然轮是谁起的"——被补试改写之后，重启补跑判据与
    `legStaleness` 都会把账算错一天。
    """
    plan = retry_state()
    if not plan:
        return
    merged = {
        **plan,
        "lastOutcome": result.get("outcome"),
        "lastResultAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "lastError": result.get("error"),
    }
    _write_retry(merged)


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
    # CR9-94（#68 乙-1）：marker 的**写点只有这一处**——正因为三条触发路径都经过这里，
    # 它的语义才是"今天这台机器起过一轮"而不是"今天补跑过"（后者会漏掉"02:00 cron 失败
    # ⇒ 午后重启又买一整轮"这一形）。`accepted=False` 那条路不写：没有新的钱被承诺。
    # 读点只有 `_catch_up_if_needed` 一处 ⇒ cron 与手动两条路的既有行为一字未动。
    prev_marker, wrote_marker = _mark_attempt(trigger)
    try:
        threading.Thread(
            target=_execute, args=(trigger, force), name="sync-manual", daemon=True
        ).start()
    except Exception:  # noqa: BLE001 CR4：线程启动失败要回滚 running，否则永久卡 True
        with _lock:
            _state["running"] = False
        # CR4 同族：线程没起来＝这一轮一次网都没出 ⇒ marker 也必须还原，
        # 否则一次线程启动失败就把当天吃掉（代价为零却锁死一天，是最坏的失败形态）。
        _unmark_attempt(prev_marker, wrote_marker)
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

    下面五条早退分支**都要留下机器可读的去向**（#21，10-02 随刀 3 落地；第五条是
    CR9-94 加的）——五条都写成 `skippedReason`，`GET /sync/status` 一条 curl 就能分清是哪一条。
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

    # CR9-94（#68 乙-1）：第五条早退分支——跨进程的"今天起过一轮"。
    # 放在内存 `lastDate` 之后（同一件事的进程内版先答，答不出才问盘）、**让位热点那个
    # 600s 循环之前**（否则热点在跑时要先白等满 `CATCHUP_YIELD_MAX_WAIT_S` 才发现不该跑）。
    # fail-open：读不出（缺文件／损坏）就当"今天没试过"⇒ 通宵没开机那天的补跑照旧放行，
    # 但错误字面要挂到状态位上（`markerReadError`），不许静默。
    disk, disk_err = _read_marker()
    with _lock:
        _state["markerReadError"] = None if disk_err == "missing" else disk_err
    attempt_date = (disk or {}).get("lastAttemptDate")
    if attempt_date == beijing_today():
        _set_skip(
            f"catchup: already attempted today（磁盘态 lastAttemptDate={attempt_date}"
            f"，trigger={(disk or {}).get('lastAttemptTrigger')}"
            f"，outcome={(disk or {}).get('lastAttemptOutcome')}）"
            "——今天这台机器已经起过一轮，不再重买列表；确要重跑走 POST /sync/run?force=true"
        )
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


def _resume_us_job_if_due() -> None:
    """CR10-49：重启后若已过调度时刻且美股任务未完成，恢复/启动持久化采集。

    五类的“今天已试过” marker 不能替美股任务作证：两者是独立任务。这里只负责
    把未收尾的 generation 接上，或在调度时刻之后补起当天的新 generation。
    """
    from . import us_list_job

    hour, minute = _sync_hour_minute()
    now = datetime.now(TZ)
    if (now.hour, now.minute) < (hour, minute):
        return
    st = us_list_job.status()
    if st.get("state") == "completed" and st.get("completedDate") == beijing_today():
        return
    us_list_job.ensure_running(CATCHUP_TRIGGER)


def _resume_us_job_after_start() -> None:
    """让 web 先就绪，再恢复/补起美股任务；异常只记录，不拖垮 DS 启动。"""
    time.sleep(8)
    try:
        from . import us_list_job

        us_list_job.resume_on_startup()
        _resume_us_job_if_due()
    except Exception as e:  # noqa: BLE001 任务恢复失败不能拖垮 DS
        log.warning("us list job resume failed: %s", e)
    # CR10-51：若进程在“美股已完成、marker 还没收尾”之间重启，这里按持久化结果补齐。
    # 不重跑任务、不发网络请求；跨日或已收尾时是空操作。
    try:
        _finalize_collecting_from_us()
    except Exception as e:  # noqa: BLE001 收尾失败只留痕，不拖垮启动
        log.warning("sync collecting finalize after start failed: %s", e)


def _resume_retry_after_start() -> None:
    """W3：重启后恢复未执行的补试计划。

    `pending` 且日期是今天 ⇒ 重新挂线程（到点就跑、过点就跑）；日期不是今天 ⇒
    记 `cancelled` 并**不**改写成今天——"昨天没补成"这件事不能靠今天多补一次来圆，
    那会让"每日最多一次"变成"每天最多一次且可以补昨天的"。

    起点同样让 web 先就绪（与 `_resume_us_job_after_start` 的 8s 同一口径），
    因为到点即跑的那一支会立刻打 `POST /api/sync`。
    """
    time.sleep(8)
    plan = retry_state()
    if not plan:
        return
    if plan.get("date") != beijing_today():
        _cancel_retry(f"plan date {plan.get('date')} is not today（重启后不跨日补跑）")
        return
    if plan.get("state") != "pending":
        return
    try:
        _schedule_retry(plan)
        log.info("retry plan resumed after restart: notBefore=%s", plan.get("notBefore"))
    except Exception as e:  # noqa: BLE001 恢复失败不能拖垮 DS 启动
        log.warning("retry plan resume failed: %s", e)


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
    threading.Thread(target=_resume_us_job_after_start, daemon=True, name="us-list-resume").start()
    # W3：补试计划的恢复必须**排在启动补跑之后**——两者都落同一个 `running` 锁，
    # 而启动补跑是"今天还没跑过"的那一支，优先级更高（补试只在自然轮已失败后才存在）。
    threading.Thread(target=_resume_retry_after_start, daemon=True, name="sync-retry-resume").start()
    log.info("product sync scheduler started: daily %02d:%02d (Asia/Shanghai)", hour, minute)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    try:
        from . import us_list_job

        us_list_job.shutdown()
    except Exception as e:  # noqa: BLE001 关闭失败不改变其他调度器的收尾
        log.warning("us list job shutdown failed: %s", e)


def status() -> dict:
    jobs = []
    if _scheduler is not None:
        for j in _scheduler.get_jobs():
            jobs.append({"id": j.id, "nextRun": str(j.next_run_time)})
    disk_marker = read_sync_state()
    # 10-18 刀 C：本进程没跑过 ⇒ 用盘上那一份结果快照顶上（照 hotspot `status()` 的
    # `fromDisk` 先例）。没有这层回落时，逐类 `note` 在重启后永久读不到＝验收对象住在内存里。
    disk_result = (disk_marker or {}).get("lastResult")
    in_proc_result = _state["lastResult"]
    sync_hour, sync_minute = _sync_hour_minute()
    from . import us_list_job

    return {
        "running": _state["running"],
        "runs": _state["runs"],
        "lastRun": _state["lastRun"],
        "lastDate": _state["lastDate"],
        "lastResult": in_proc_result if in_proc_result is not None else disk_result,
        "lastResultFromDisk": in_proc_result is None and disk_result is not None,
        # #21：一条 curl 就能读出"上一轮为什么没跑"（off／未到点／当日已同步／当日已试过／
        # 让位热点超时），这些原因此前只存在于 `log.info` 里，而 uvicorn 默认配置根本不打 info。
        "skippedReason": _state.get("skippedReason"),
        # 刀 3/甲-1：刷新腿那份结果（含它自己的 outcome／预算／skippedReason）
        "lastRefresh": _state.get("lastRefresh"),
        # CR10-49：美股完整名单的持久化任务状态。`collecting/waiting` 不是失败，
        # `completed` 只表示完整候选已发布且 us 行情刷新收尾。
        "usListJob": us_list_job.status(),
        # CR9-94（#68 乙-1）：跨进程那份"今天起过一轮"（含 `lastAttemptOutcome`，它把
        # "今天试过"分成 rejected／inconclusive 与 completed 两种——后者配上 `Product.updatedAt`
        # 没动，就是 #69 那枚唯一零出网可读的仪器）。`lastAttemptFromDisk` 照 hotspot
        # `status()` 的 `fromDisk` 先例：本进程一轮没跑而盘上有 ⇒ 那是**上一个进程**起的。
        # ⚠️ `runs` 的义一字不动（`hotspot/scheduler.py:259` 同族纪律：它管"本进程跑了几轮"）。
        "lastAttempt": disk_marker,
        "lastAttemptFromDisk": bool(disk_marker) and _state["runs"] == 0,
        # fail-open 的两枚仪器位：读不出／写不进都要看得见，不许用省略冒充
        "markerReadError": _state.get("markerReadError"),
        "markerWriteFailed": bool(_state.get("markerWriteFailed")),
        # CR10-1：这条腿「今天该不该已经有它」由读的一方算——`skippedReason` 住内存，
        # 而擦掉它的那次重启正是丢腿的原因（10-19／10-20／10-21 三夜同一形）。
        "legStaleness": leg_staleness(
            (disk_marker or {}).get("lastAttemptDate"),
            hour=sync_hour,
            minute=sync_minute,
            instrument_ok=not (_state.get("markerWriteFailed") or _state.get("markerReadError")),
        ),
        "jobs": jobs,
        "timezone": str(TZ),
        # W3：补试计划（`pending/running/completed/exhausted/cancelled`）。盘上那份是真相，
        # 内存镜像只是本进程刚写过的那份；两者不一致时以盘为准——一条 curl 就能读出
        # "今天会不会再自动补一次、补哪几类、几点起"。`None`＝今天没有待执行计划。
        "retry": (disk_marker or {}).get("retry"),
        "retryLastResult": _state.get("retryLastResult"),
        "retryLastRefresh": _state.get("retryLastRefresh"),
    }
