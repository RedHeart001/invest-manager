"""外部调用看门狗：给"内部没有超时能力"的库调用加上超时保护。

背景：akshare 内部使用 requests 且未设置 timeout，上游节点挂死时调用会**永久阻塞**，
在 FastAPI 同步端点里会持续占住线程池 worker，最终拖垮整个 data-service
（项目早期已实际踩过一次：`_run_with_timeout` 就是那时为研报采集加的）。

Python 无法强杀线程，因此本模块用"守护线程 + join 超时"让**调用方按时返回并降级**；
被放弃的线程仍是 daemon，会在上游恢复/连接超时后自然结束（不会阻止进程退出）。

CR9-45②（2026-10-01）再加一道**在飞上限**：并发等待达到上限后，新调用不起线程、
不发外部请求、立即返回降级——把"上游挂起"能占住的线程池 worker 数钉死在上限内
（见 `MAX_INFLIGHT_WATCHDOGS` 的取值理由）。

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

# CR9-45②（2026-10-01，主人点头）：**在飞上限**。
# `_inflight` 数的是"当前正卡在 t.join() 上的调用数"——FastAPI 的同步端点全部共用
# anyio 默认 **40** 线程池，所以这个数**就是本模块正在占住的池 worker 数**。
# 09-28 夜实测：上游挂起时 abandoned 计数爬到 102，期间连零外部依赖的 `/health`
# 都拿不到 worker（`curl -m 8` 全 000）——观测通道与被观测对象抢同一份资源。
# 上限取 **12**：按 sync 形态（一轮 5 类、分钟级占桶）留出的并发，
# 40 − 12 = **28** 个 worker 永远留给"不经过本模块"的请求（含 `/health`）。
# 超限的新调用**不起线程、不发外部请求**，立即返回降级——既不再占 worker，
# 也不在上游已经挂起的时刻继续给它加请求量。
# 为什么不需要"半开探测"：`_inflight` 由主线程在 join 返回时递减，
# 而 join 最多等 `seconds` 秒 ⇒ 上游恢复后本闸门在 ≤seconds 内**自行打开**，
# 不存在永久锁死。
MAX_INFLIGHT_WATCHDOGS = 12
_inflight_lock = threading.Lock()
_inflight = 0
_gate_warned = False


class WatchdogOpenError(TimeoutError):
    """在飞已达上限：本次未发起外部调用，直接降级。

    继承 `TimeoutError` 是有意的——所有调用点（`_ak_request` / `_em_ak_request` /
    `chain_call`）本来就按"超时即降级"处理，无需逐处改判定；子类身份只用来让
    日志与测试能区分"真超时"和"闸门挡下"。
    """


def abandoned_count() -> int:
    """当前"已放弃等待但仍存活"的看门狗线程数（观测用）。"""
    return _abandoned


def inflight_count() -> int:
    """当前卡在超时等待中的看门狗调用数（= 被本模块占住的线程池 worker 数）。"""
    return _inflight


def run_with_timeout(
    fn: Callable[[], T],
    seconds: float,
    name: str = "external-call",
) -> Tuple[T | None, BaseException | None]:
    """在守护线程中执行 fn，最多等待 seconds 秒。

    返回 (结果, 异常)：超时时返回 (None, TimeoutError)；fn 抛错时返回 (None, 原异常)；
    在飞已达上限时返回 (None, WatchdogOpenError) 且**不发起 fn**（不发外部请求）。
    """
    global _abandoned, _inflight, _gate_warned
    box: dict[str, Any] = {}

    def _runner() -> None:
        global _abandoned
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 —— 原样交回调用方判定
            box["error"] = e
        finally:
            # D2：标志读取与递减在同一把锁内——与主线程的"置标志 + 计数"互斥。
            # 此前主线程锁外先写标志、runner 无锁读 → runner 在主线程置标志前
            # 恰好走到 finally 就不会递减（计数只增不减）。
            with _abandoned_lock:
                if box.get("_abandoned"):
                    _abandoned = max(0, _abandoned - 1)

    with _inflight_lock:
        if _inflight >= MAX_INFLIGHT_WATCHDOGS:
            if not _gate_warned:
                _gate_warned = True
                log.warning(
                    "watchdog gate open：在飞 %d ≥ 上限 %d，其后的外部调用立即降级（不再发请求）",
                    _inflight,
                    MAX_INFLIGHT_WATCHDOGS,
                )
            return None, WatchdogOpenError(
                f"{name} 未发起：看门狗在飞已达上限 {MAX_INFLIGHT_WATCHDOGS}（上游疑似持续挂起）"
            )
        _inflight += 1

    try:
        t = threading.Thread(target=_runner, name=name, daemon=True)
        t.start()
        t.join(seconds)
    finally:
        # 主线程离开 join 即归还名额：无论 fn 已完成、超时被放弃还是 start() 失败。
        # 被放弃的线程仍在后台存活，但它不再占线程池 worker，只由 _abandoned 记账。
        with _inflight_lock:
            _inflight -= 1
            if _inflight < MAX_INFLIGHT_WATCHDOGS:
                _gate_warned = False

    if t.is_alive():
        # D2（CR7-12，2026-09-25）：置标志与计数必须在同一把锁内，并与 runner 的
        # finally 递减互斥——此前 `box["_abandoned"] = True` 在锁外先写、runner
        # 恰在两步之间读走 finally → 只加不减（计数虚高）。现在持锁置标志：
        # runner 的 finally 同样持锁读改，两个顺序都正确——
        #   a) 主线程先拿锁：标志已置 + 计数 +1，runner 后续递减；
        #   b) runner 先拿锁：标志未置 → 不递减（它本来就不该递减），主线程
        #      随后 +1 但二次确认 is_alive()——若已结束则不虚增。
        with _abandoned_lock:
            if not t.is_alive():
                # 拿到锁的瞬间线程已自然结束：不计数（避免 +1 后无人递减）
                pass
            else:
                box["_abandoned"] = True
                _abandoned += 1
                count = _abandoned
        if t.is_alive():
            if count >= ABANDONED_WARN_THRESHOLD:
                log.warning(
                    "watchdog abandoned threads = %d (>= %d)：上游疑似持续挂起，请排查数据源",
                    count,
                    ABANDONED_WARN_THRESHOLD,
                )
            return None, TimeoutError(f"{name} 超时（>{seconds}s），已放弃等待并降级")
        # 极窄窗口（持锁判定存活 → 释放锁后线程结束）：按正常结束处理
        if "error" in box:
            return None, box["error"]
        return box.get("value"), None
    if "error" in box:
        return None, box["error"]
    return box.get("value"), None
