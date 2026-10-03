"""源族级请求限速与熔断（R15 / PLAN M8）。

背景（2026-09-12 实测）：东财为 IP 级滚动窗口限流——空闲后单次请求可通过，
连续 2+ 请求立即触发惩罚，且惩罚覆盖其全部域名。因此限速必须按"源族"
（如整个 eastmoney）共享额度，而不是按域名。

设计：
- 令牌桶：最小间隔 min_interval + 突发容量 burst + 每分钟上限 rate_per_min
- acquire() 阻塞排队等待，超时返回 False（调用方应转向备源，不硬等）
- 熔断：连续失败 ≥failure_threshold → 冷却 cooldown_base 秒（指数递增至上限）
- 线程安全：FastAPI 同步端点在线程池执行，用 RLock 保护状态
"""

from __future__ import annotations

import threading
import time
from collections import deque


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

    # ---------- 取额度 ----------

    def acquire(self, timeout: float = 20.0) -> bool:
        """等待额度。冷却中或等待超时返回 False（调用方转备源）。"""
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
