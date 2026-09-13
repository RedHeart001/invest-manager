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

    # ---------- 查询状态 ----------

    def in_cooldown(self) -> bool:
        with self._lock:
            return time.monotonic() < self._cooldown_until

    def cooldown_remaining(self) -> float:
        with self._lock:
            return max(0.0, self._cooldown_until - time.monotonic())

    def state(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "cooldown": round(self.cooldown_remaining(), 1),
                "consecutiveFailures": self._consecutive_failures,
            }

    # ---------- 取额度 ----------

    def acquire(self, timeout: float = 20.0) -> bool:
        """等待额度。冷却中或等待超时返回 False（调用方转备源）。"""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                if now < self._cooldown_until:
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
                    return True
            if time.monotonic() + wait > deadline:
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


def get_limiter(name: str, **kwargs) -> FamilyLimiter:
    with _REGISTRY_LOCK:
        if name not in _LIMITERS:
            _LIMITERS[name] = FamilyLimiter(name, **kwargs)
        return _LIMITERS[name]
