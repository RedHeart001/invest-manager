"""外部调用看门狗：给"内部没有超时能力"的库调用加上超时保护。

背景：akshare 内部使用 requests 且未设置 timeout，上游节点挂死时调用会**永久阻塞**，
在 FastAPI 同步端点里会持续占住线程池 worker，最终拖垮整个 data-service
（项目早期已实际踩过一次：`_run_with_timeout` 就是那时为研报采集加的）。

Python 无法强杀线程，因此本模块用"守护线程 + join 超时"让**调用方按时返回并降级**；
被放弃的线程仍是 daemon，会在上游恢复/连接超时后自然结束（不会阻止进程退出）。

用法：
    from .timeout import run_with_timeout
    value, err = run_with_timeout(lambda: ak.some_call(...), 30.0, "ak.some_call")
    if err:  # 超时或异常 → 由调用方转成降级
        ...
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Tuple, TypeVar

log = logging.getLogger("timeout")

T = TypeVar("T")

# CR-22（本轮 code review）：看门狗超时后线程无法强杀，只能等上游自然结束。
# 此处统计"已放弃但仍存活"的看门狗线程数，超过阈值时告警，便于发现上游持续挂起。
_abandoned_lock = threading.Lock()
_abandoned = 0
ABANDONED_WARN_THRESHOLD = 20


def abandoned_count() -> int:
    """当前"已放弃等待但仍存活"的看门狗线程数（观测用）。"""
    return _abandoned


def run_with_timeout(
    fn: Callable[[], T],
    seconds: float,
    name: str = "external-call",
) -> Tuple[T | None, BaseException | None]:
    """在守护线程中执行 fn，最多等待 seconds 秒。

    返回 (结果, 异常)：超时时返回 (None, TimeoutError)；fn 抛错时返回 (None, 原异常)。
    """
    global _abandoned
    box: dict[str, Any] = {}

    def _runner() -> None:
        global _abandoned
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 —— 原样交回调用方判定
            box["error"] = e
        finally:
            # 只在"曾被放弃（超时）"的线程结束时递减；正常结束的线程不计入
            if box.get("_abandoned"):
                with _abandoned_lock:
                    _abandoned = max(0, _abandoned - 1)

    t = threading.Thread(target=_runner, name=name, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        box["_abandoned"] = True
        with _abandoned_lock:
            _abandoned += 1
            count = _abandoned
        if count >= ABANDONED_WARN_THRESHOLD:
            log.warning(
                "watchdog abandoned threads = %d (>= %d)：上游疑似持续挂起，请排查数据源",
                count,
                ABANDONED_WARN_THRESHOLD,
            )
        return None, TimeoutError(f"{name} 超时（>{seconds}s），已放弃等待并降级")
    if "error" in box:
        return None, box["error"]
    return box.get("value"), None
