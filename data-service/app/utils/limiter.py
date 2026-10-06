"""源族级请求限速与熔断（R15 / PLAN M8）。

背景（2026-09-12 实测）：东财为 IP 级滚动窗口限流——空闲后单次请求可通过，
连续 2+ 请求立即触发惩罚，且惩罚覆盖其全部域名。因此限速必须按"源族"
（如整个 eastmoney）共享额度，而不是按域名。

设计：
- 令牌桶：最小间隔 min_interval + 突发容量 burst + 每分钟上限 rate_per_min
- acquire() 阻塞排队等待，超时返回 False（调用方应转向备源，不硬等）
- 熔断：连续失败 ≥failure_threshold → 冷却 cooldown_base 秒（指数递增至上限）
- 线程安全：FastAPI 同步端点在线程池执行，用 RLock 保护状态

**#41 甲（CR9-69）新增的一条前提**（主人 10-06 的字＝「走甲」）＝计数**落盘**。此前的计数住在
`FamilyLimiter` 的实例字段里、族实例住在模块作用域 ⇒ 每次重启归零，历次 `/health` 读数
`11→10→47→2` 非单调就是这个形状（10-06 18:2x 实测），而 #27 第二步的立项依据原文是
"拿一周真实计数定数值"——不落地就永远攒不出"一周"，那条决定只能一直悬着。
落法照 `backups/state.json`／`hotspot-state.json` 那一族：**按北京日分桶**、先 `.tmp` 再
`os.replace`、写不进只 `log.warning`（观测不得拖垮主功能，CR9-45）、留存 30 天。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque

from .timeutil import beijing_today

log = logging.getLogger(__name__)


class FamilyLimiter:
    def __init__(
        self,
        name: str,
        min_interval: float = 5.0,
        burst: int = 2,
        rate_per_min: int = 12,
        failure_threshold: int = 2,
        cooldown_base: float = 180.0,
        cooldown_max: float = 900.0,
    ) -> None:
        self.name = name
        self.min_interval = min_interval
        self.burst = burst
        self.rate_per_min = rate_per_min
        self.failure_threshold = failure_threshold
        self.cooldown_base = cooldown_base
        self.cooldown_max = cooldown_max

        self._lock = threading.RLock()
        self._last_ts = 0.0
        self._recent: deque[float] = deque()  # 最近请求时间戳（滑窗计数）
        self._consecutive_failures = 0
        self._cooldown_until = 0.0
        self._cooldown_level = 0
        # #27（10-03）：真实计数。此前"哪条路出了多少次网"在运行时**完全不可读**
        # （只有 `log.warning`），而给桶外请求补限流的第一步恰恰是要有数可看。
        self._granted = 0
        self._denied = 0
        self._seen: dict[str, int] = {}
        # #41 甲：落盘游标——`_flushed_*` 是"已经进过那一天桶里"的部分，差值才是待写的增量。
        # 用差值而不是覆盖，重启后本进程从 0 累计的那半才会**加**进那一天的桶，不会抹掉它。
        self._flushed_granted = 0
        self._flushed_denied = 0
        self._flushed_seen: dict[str, int] = {}

    # ---------- 查询状态 ----------

    def in_cooldown(self) -> bool:
        with self._lock:
            return time.monotonic() < self._cooldown_until

    def cooldown_remaining(self) -> float:
        with self._lock:
            return max(0.0, self._cooldown_until - time.monotonic())

    def state(self) -> dict:
        """可读状态（#27 起带真实计数）——**只读，不改变任何额度**。"""
        with self._lock:
            top = dict(
                sorted(self._seen.items(), key=lambda kv: (-kv[1], kv[0]))[:_SEEN_TOP]
            )
            return {
                "name": self.name,
                "cooldown": round(self.cooldown_remaining(), 1),
                "consecutiveFailures": self._consecutive_failures,
                "granted": self._granted,
                "denied": self._denied,
                "seen": top,
                "seenTotal": sum(self._seen.values()),
            }

    def observe(self, name: str) -> None:
        """纯计数一条（#27 第一步）。

        刻意**不经过 `acquire()`**：观测面不得改变行为——包括"到限就拒"这条行为。
        第二步若真要给这条路限流，改的是调用点，不是这里。
        """
        with self._lock:
            self._seen[name] = self._seen.get(name, 0) + 1
        _maybe_dump()  # 锁外落盘（锁内做文件 I/O 会把磁盘时间算进桶的等待）

    # ---------- #41 甲：落盘用的两个读数 ----------

    def _delta_locked(self) -> dict:
        return {
            "granted": self._granted - self._flushed_granted,
            "denied": self._denied - self._flushed_denied,
            "seen": {
                k: v - self._flushed_seen.get(k, 0)
                for k, v in self._seen.items()
                if v - self._flushed_seen.get(k, 0) > 0
            },
        }

    def outstanding(self) -> dict:
        """本进程**还没进盘**的那半（不推进游标）⇒ `/health` 的读数不会读少。"""
        with self._lock:
            return self._delta_locked()

    def take_delta(self) -> dict:
        """取增量**并**推进游标（只有 `flush()` 走这条路，重复调用不会重复计数）。"""
        with self._lock:
            d = self._delta_locked()
            self._flushed_granted = self._granted
            self._flushed_denied = self._denied
            self._flushed_seen = dict(self._seen)
            return d

    # ---------- 取额度 ----------

    def acquire(self, timeout: float = 20.0) -> bool:
        """等待额度。冷却中或等待超时返回 False（调用方转备源）。

        #41 甲：取额度这件事本身顺带落一次盘（节流在 `_maybe_dump` 里，锁外）。
        """
        try:
            return self._acquire(timeout)
        finally:
            _maybe_dump()

    def _acquire(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                if now < self._cooldown_until:
                    self._denied += 1
                    return False
                # 滑窗清理
                while self._recent and now - self._recent[0] > 60.0:
                    self._recent.popleft()
                wait = 0.0
                # 最小间隔（突发容量内可豁免 min_interval 的严格性）
                since_last = now - self._last_ts
                if len(self._recent) >= self.burst and since_last < self.min_interval:
                    wait = max(wait, self.min_interval - since_last)
                # 每分钟上限
                if len(self._recent) >= self.rate_per_min:
                    wait = max(wait, 60.0 - (now - self._recent[0]) + 0.05)
                if wait <= 0:
                    self._last_ts = now
                    self._recent.append(now)
                    self._granted += 1
                    return True
            if time.monotonic() + wait > deadline:
                with self._lock:
                    self._denied += 1
                return False
            time.sleep(min(wait, 1.0))

    # ---------- 结果回报 ----------

    def on_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._cooldown_level = 0
            self._cooldown_until = 0.0  # 成功即视为源已恢复，解除冷却

    def on_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                cooldown = min(
                    self.cooldown_base * (2**self._cooldown_level), self.cooldown_max
                )
                self._cooldown_until = time.monotonic() + cooldown
                self._cooldown_level += 1


# 全局注册表：按源族共享（调用方经 get_limiter 获取）
_LIMITERS: dict[str, FamilyLimiter] = {}
_REGISTRY_LOCK = threading.Lock()

# #27：`state()["seen"]` 只带最高的几项（观测位不是台账，一条 curl 要能读完）
_SEEN_TOP = 10

# ---------- #41 甲（CR9-69）：把计数落盘 ----------
#
# 为什么要这一份文件（不是"顺手加个持久化"）：桶与计数都是**模块作用域对象**，重启即归零 ⇒
# 历次 `/health` 读数 `11→10→47→2` 非单调（10-06 18:2x 实测）。而 #27 第二步（真给桶外那五处
# 补限流）的立项依据原文是"**拿一周真实计数定数值**"——不落盘，"一周"在结构上永远取不到。
#
# 落地的几处口径，写在这里因为它们是**决定**不是实现细节（要改等主人的字）：
# - **按北京日分桶**，不做"自某起点累计"：#27 要问的本来就是"这条路每天出多少次网"，
#   分桶直接给这个数；累计则需要第二个清零出口，否则限流值会被上一次故障期的高拒绝率长期拖住。
# - **留存 30 天**（`KEEP_DAYS`）＝与 `backup_scheduler` 那份同一口径，不新造一个数。
# - **观测不得拖垮主功能**（CR9-45 同族）：写不进只 `log.warning`；落盘只发生在族锁**外**
#   （`acquire`/`observe` 的收尾那一步），文件 I/O 的时间绝不会算进桶的等待里。
# - **增量而非覆盖**：`take_delta()` 推进游标，所以重启后本进程从 0 累计的那半是**加**进
#   那一天的桶，不会把上一个进程记的抹掉——这条才是本刀的存在理由。
STATE_NAME = "limiter-state.json"
KEEP_DAYS = 30
FLUSH_MIN_INTERVAL_S = 60.0  # 落盘节流：这是"事后读得出"的观测位，不是每秒都要新的表

_flush_lock = threading.Lock()
_last_flush = 0.0
_flush_failures = 0  # 只累加，给 /health 读"这份文件到底写没写成"


def state_path() -> str:
    """落点默认 `data-service/runtime/limiter-state.json`（该目录已在 `.gitignore`）。

    `LIMITER_STATE_FILE` 整条覆盖——离线单测靠它指向临时目录，不许把仓库目录当测试产物落点。
    """
    env = os.environ.get("LIMITER_STATE_FILE", "")
    if env:
        return env
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "runtime", STATE_NAME)


def read_state() -> dict | None:
    """读回盘上那份；缺失／半截／形状不对一律当"没有"，**不抛**（健康检查不许因此 500）。"""
    try:
        with open(state_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
        return None
    return data


def _num(v: object) -> int:
    """盘上那份可能被人手改过（或是旧形状）：非整数一律当 0，绝不让 `/health` 因此 500。"""
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _bump(bucket: dict, delta: dict) -> None:
    """把一份增量并进那一天的某族桶里。"""
    bucket["granted"] = _num(bucket.get("granted")) + _num(delta.get("granted"))
    bucket["denied"] = _num(bucket.get("denied")) + _num(delta.get("denied"))
    raw_seen = bucket.get("seen")
    seen = raw_seen if isinstance(raw_seen, dict) else {}
    for name, n in (delta.get("seen") or {}).items():
        seen[name] = _num(seen.get(name)) + _num(n)
    bucket["seen"] = seen
    bucket["seenTotal"] = sum(_num(v) for v in seen.values())


def flush(force: bool = True) -> bool:
    """把每个族未落盘的增量并进今天那份，然后原子写盘。写不进只 warning、返回 False。

    `force=False` 时按 `FLUSH_MIN_INTERVAL_S` 节流——事件路径上走的都是这一支。
    **没有增量就一律不碰文件**：否则 mtime 会谎称"这个进程写过盘"。
    """
    global _last_flush, _flush_failures
    if not force and time.monotonic() - _last_flush < FLUSH_MIN_INTERVAL_S:
        return False
    with _REGISTRY_LOCK:
        limits = list(_LIMITERS.values())
    deltas = {}
    for lim in limits:
        d = lim.take_delta()
        if d["granted"] or d["denied"] or d["seen"]:
            deltas[lim.name] = d
    if not deltas:
        return False
    tmp = ""
    with _flush_lock:
        _last_flush = time.monotonic()
        path = state_path()
        data = read_state() or {"days": {}}
        day = beijing_today()
        bucket = data["days"].setdefault(day, {})
        for name, d in deltas.items():
            _bump(bucket.setdefault(name, {"granted": 0, "denied": 0, "seenTotal": 0, "seen": {}}), d)
        # 轮换：只按日期字符串留最近 KEEP_DAYS 天（ISO 日期字典序＝时间序，不用解析）
        for old in sorted(data["days"].keys())[:-KEEP_DAYS]:
            data["days"].pop(old, None)
        data["day"] = day
        data["keptDays"] = len(data["days"])
        tmp = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, path)
            return True
        except (OSError, TypeError, ValueError) as e:
            _flush_failures += 1
            log.warning("limiter state could not be written: %s", e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False


def _maybe_dump() -> None:
    """事件路径上的节流落盘（`acquire`/`observe` 的锁外那一步）。任何意外都不许改变取额度的结果。"""
    try:
        flush(force=False)
    except Exception as e:  # noqa: BLE001 观测面：CR9-45 那条口径在这里同样成立
        log.warning("limiter dump failed: %s", e)


def durable_today() -> dict:
    """`/health` 的 `limitersDurable`：**跨重启**的今日累计（#27 第二步要的那个数）。

    与 `limiters` 的分工要说清：那一位读的是"这个进程此刻的桶"（冷却、连续失败只有当下有意
    义），这一位读的是"这一天累计了多少次"（只有落盘才读得到）。

    读数形状＝**盘上那份 ＋ 本进程还没落盘的增量**（在内存里并一份，不为了读而写盘）——
    只回落到盘上会把最近这 ≤60 秒的数读少，而 #27 要的恰恰是"到底多少次"。
    `fromDisk` ＝ 本进程对这些数一点都没贡献（全新进程、盘上有货），与 #29／#34 那两枚同族口径。
    """
    data = read_state() or {"days": {}}
    day = beijing_today()
    stored = (data.get("days") or {}).get(day) or {}
    families: dict[str, dict] = {}
    for name, v in stored.items():
        if isinstance(v, dict):
            raw_seen = v.get("seen")
            families[name] = {
                "granted": _num(v.get("granted")),
                "denied": _num(v.get("denied")),
                "seenTotal": _num(v.get("seenTotal")),
                "seen": dict(raw_seen) if isinstance(raw_seen, dict) else {},
            }
    with _REGISTRY_LOCK:
        limits = list(_LIMITERS.values())
    pending = 0
    for lim in limits:
        d = lim.outstanding()
        if d["granted"] or d["denied"] or d["seen"]:
            pending += 1
            _bump(families.setdefault(lim.name, {"granted": 0, "denied": 0, "seenTotal": 0, "seen": {}}), d)
    return {
        "day": day,
        "families": families,
        "fromDisk": pending == 0 and bool(families),
        "keptDays": len((data.get("days") or {})),
        "flushFailures": _flush_failures,
    }


# ---------- #42 丙（CR9-70）：读侧的「最近 N 日汇总」 ----------
#
# 为什么这条长在**读数面**而不是写侧（这是丙与乙的分工，不是实现偏好）：按日分桶已经把要用的
# 原料全存着了，#27 第二步缺的只是"把 7 格相加"这一步的出口。改成"自起点累计"就得再养第二个
# 机制（清零出口）——`denied` 里含着故障期的连续拒绝，永久累计会让限流值被上一次事故长期拖住。
# ⇒ 存储形状、写路径、节流、留存上限一律不动；要更长的历史只改 `KEEP_DAYS` 这一个常数。
WINDOW_DAYS = 7  # 就是立项依据里"一周"那个字面，不新造一个数


def _as_delta(v: dict) -> dict:
    """把盘上那一份归一成 `_bump()` 能吃的增量形状。

    刻意**不**把 `seenTotal` 传下去：`_bump()` 是按合并后的 `seen` 重新求和的，这正是我们要的
    口径（盘上那个已存字段可能来自旧形状或被人手改过，不信它）。`seen` 不是字典就当空——
    与 `durable_today()` 同一条"坏文件不许让 `/health` 500"的纪律。
    """
    raw_seen = v.get("seen")
    return {
        "granted": _num(v.get("granted")),
        "denied": _num(v.get("denied")),
        "seen": dict(raw_seen) if isinstance(raw_seen, dict) else {},
    }


def durable_window(days: int = WINDOW_DAYS) -> dict:
    """`/health` 的 `limitersWindow`：把盘上最近 N 个**有记录的**北京日相加（#42 丙）。

    与 `durable_today()` 的分工＝"这一天多少次"与"这一周总共多少次"，两者读同一份文件、
    同一条增量口径，谁也不替代谁（第二步要定的是速率，得两頭都有数才能看出趋势）。

    两条必须让读者看得见的口径：
    - **`coveredDays` 只列盘上真有的那些日**，`windowDays` 是请求的上限而非实际覆盖天数。
      攒够一周之前这个读数会小于 7 天 ⇒ 天数本身必须可见，否则"7 日汇总"会在只有 2 天时
      伪装成一周（把两天的数当一周读，10-06 我账上那条"已累积 3 天"就是同一个错）。
      同理注意：**中间缺的那几天不会把区间缩回来**（ds 没跑的那两天本来就没有出网）。
    - **今天那一格含本进程未落盘的增量**（与 `durable_today()` 一字同口径）。不双计：
      `outstanding()` 读的是游标之后那半截，已经进盘的部分不会重复出现。
    - `fromDisk`＝本进程对这些数一点都没贡献（全新进程、盘上有货），与 #29／#34／#41 同族。
    """
    data = read_state() or {"days": {}}
    stored_days = data.get("days") or {}
    # `sorted(..., reverse=True)` 取的是**最近的 N 个有数之日**；先夹到非负，
    # 否则 `[:-1]` 这种负切片会把最新那一天（也就是今天）切掉。
    keys = sorted(stored_days, reverse=True)[: max(0, days)]
    families: dict[str, dict] = {}
    for key in keys:
        for name, v in (stored_days.get(key) or {}).items():
            if isinstance(v, dict):
                _bump(
                    families.setdefault(
                        name, {"granted": 0, "denied": 0, "seenTotal": 0, "seen": {}}
                    ),
                    _as_delta(v),
                )
    with _REGISTRY_LOCK:
        limits = list(_LIMITERS.values())
    pending = 0
    for lim in limits:
        d = lim.outstanding()
        if d["granted"] or d["denied"] or d["seen"]:
            pending += 1
            _bump(
                families.setdefault(
                    lim.name, {"granted": 0, "denied": 0, "seenTotal": 0, "seen": {}}
                ),
                d,
            )
    return {
        "windowDays": max(0, days),
        "coveredDays": sorted(keys),  # 升序：让"区间"和"缺口"在一条 curl 里都读得出
        "families": families,
        "fromDisk": pending == 0 and bool(families),
        "keptDays": len(stored_days),
        "flushFailures": _flush_failures,
    }

# CR9-18（2026-09-27）：桶参数**只有一个来源**。
# 旧实现 `get_limiter(name, **kwargs)` 是"首调用获胜"——同名族的 kwargs 只在创建那一刻
# 生效，而谁是首调用由 import 顺序决定：`hotspot/pipeline.py` 的无参调用先创建 eastmoney
# 族，`akshare_provider` 写在调用点上的六个参数就被静默丢弃（当前两处取值恰好相同，
# 所以无症状；一旦按 C-5 调桶，改动会不生效且不报错）。
# 现在 get_limiter 不再接受参数，调参只有 PROFILES 一处。
PROFILES: dict[str, dict] = {
    "eastmoney": {
        # R15/M8：东财 IP 级滚动窗口限流，全部域名共享额度（实测见 C-5）
        "min_interval": 5.0,
        "burst": 2,
        "rate_per_min": 12,
        "failure_threshold": 2,
        "cooldown_base": 180.0,
        "cooldown_max": 900.0,
    },
    # #27 第一步（10-03）：**观测族，不是额度族**。`akshare_provider._ak_request` 那几处
    # 不占上面的东财桶，而其中若干实际打的仍是 eastmoney 域名（红线"OPT-3 不得动东财桶"
    # 的破口）。今天要回答的不是"怎么限"而是"到底多少次"——那五处此前没有任何可读计数面。
    # 调用点走 `observe()` 而不是 `acquire()` ⇒ 本族的参数**一律不生效**，写在这里只是给
    # 第二步预留唯一调参来源（CR9-18 的纪律：调参只有 PROFILES 一处，否则改了不生效也不报错）。
    "akshare-obs": {
        "min_interval": 0.0,
        "burst": 10**9,
        "rate_per_min": 10**9,
        "failure_threshold": 10**9,
        "cooldown_base": 0.0,
        "cooldown_max": 0.0,
    },
}


def get_limiter(name: str) -> FamilyLimiter:
    """取源族共享限速器（按名创建一次，之后所有调用方拿到同一实例）。

    参数一律来自 `PROFILES[name]`；未声明的源族用 `FamilyLimiter` 的类默认值。
    """
    with _REGISTRY_LOCK:
        if name not in _LIMITERS:
            _LIMITERS[name] = FamilyLimiter(name, **PROFILES.get(name, {}))
        return _LIMITERS[name]


def snapshot_all() -> list[dict]:
    """/health 的读数面：按族名字典序列出各家 `state()`。

    只列**已注册**的族（懒创建 ⇒ 没被用到的族不会出现），这样"某族一次都没被调过"
    与"该族被调了 500 次"在一条 curl 里是两种可读的形态，而不是都读成缺项。
    """
    with _REGISTRY_LOCK:
        names = sorted(_LIMITERS)
        return [_LIMITERS[n].state() for n in names]
