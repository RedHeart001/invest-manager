"""CR9-45② 离线单测：看门狗的**在飞上限**——上游挂起时不再无限占线程池。

背景（2026-09-28 夜字面证据，见 [CODE-REVIEW.md](../CODE-REVIEW.md)「CR9 追加十/十一」）：
`utils/timeout.py` 的看门狗超时后**只能计数不能强杀**，而 ds 每个端点都是同步 `def` ⇒
共用 anyio 默认 **40** worker 线程池。上游持续挂起时，几十个调用各自卡在 `join(30s)` 上，
连零外部依赖的 `/health` 都排不到 worker（实测 `curl -m 8 :8000/health` → `000`、
abandoned 计数 138 条告警、峰值 102）——**观测通道与被观测对象抢同一份资源**。

②＝在飞达到 `MAX_INFLIGHT_WATCHDOGS` 时，新调用**不起线程、不发外部请求、立即降级**。
钉住的不变量：**被本模块占住的 worker 数 ≤ 上限 < 池容量**（40 − 12 = 28 永远留给
不经过本模块的请求）。①（`/health` 改 `async def`）在
`tests/test_cr9_45_health_async.py`。

反向验证成对断言（C34）：既断"到上限即快速失败"，也断"在飞回落后同一函数照常执行"
——证明上限不是恒假桩；另断"返回的是 `TimeoutError` 子类"，证明调用点无需改动就能
沿用链上降级语义（R16：降级要可判定，不是新增一种错误形态）。

运行方式（无需任何服务在跑，不碰外部数据源）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr9_45_inflight_cap.py
"""

import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含中文/emoji，Windows GBK 控制台会 UnicodeEncodeError。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from app.utils import timeout as to  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _wait_inflight(target: int, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if to.inflight_count() >= target:
            return True
        time.sleep(0.01)
    return False


def test_cap_below_pool() -> None:
    """上限的存在意义：占住的 worker 必须**少于** anyio 默认池容量。

    这条不测数值本身（12 是拍板值，不是实现细节），测的是"上限 < 池容量"这个
    让 `/health` 活下来的不变量——池容量按实测读，不写死 40。
    """
    from anyio.to_thread import current_default_thread_limiter

    async def _capacity() -> int:
        # 必须在事件循环里读——限流器是 anyio 后端对象，主线程直接调用会抛 NoEventLoopError。
        return current_default_thread_limiter().total_tokens

    total = asyncio.run(_capacity())
    check(
        f"CR9-45②：在飞上限 {to.MAX_INFLIGHT_WATCHDOGS} < 线程池容量 {total}"
        "（差值就是永远留给非取数请求的 worker）",
        to.MAX_INFLIGHT_WATCHDOGS < total,
        f"cap={to.MAX_INFLIGHT_WATCHDOGS} pool={total}",
    )
    check(
        "CR9-45②：上限 > 0（配成 0 等于把外部取数全关掉）",
        to.MAX_INFLIGHT_WATCHDOGS > 0,
        str(to.MAX_INFLIGHT_WATCHDOGS),
    )


def test_gate_blocks_at_cap() -> None:
    """到上限：第 13 个调用立即降级、不 join、**不起线程**。"""
    cap = to.MAX_INFLIGHT_WATCHDOGS
    release = threading.Event()

    def _blocked():
        release.wait(20)
        return "released"

    holders = [
        threading.Thread(
            target=lambda: to.run_with_timeout(_blocked, 15.0, f"cap-holder-{i}"),
            daemon=True,
        )
        for i in range(cap)
    ]
    for h in holders:
        h.start()
    check(
        f"CR9-45②：前置条件——{cap} 个调用确实进入在飞等待",
        _wait_inflight(cap) and to.inflight_count() == cap,
        str(to.inflight_count()),
    )

    threads_before = threading.active_count()
    calls = 0

    def _should_not_run():
        nonlocal calls
        calls += 1
        return "leaked"

    t0 = time.perf_counter()
    value, err = to.run_with_timeout(_should_not_run, 15.0, "cap-13th")
    dt = time.perf_counter() - t0

    check(
        "CR9-45②：到上限后新调用立即返回降级（未 join，耗时 < 0.05s）",
        value is None and dt < 0.05,
        f"dt={dt:.4f}s value={value}",
    )
    check(
        "CR9-45②：降级返回 WatchdogOpenError 且是 TimeoutError 子类"
        "（调用点零改动即沿用链上降级语义）",
        isinstance(err, to.WatchdogOpenError) and isinstance(err, TimeoutError),
        repr(err),
    )
    check(
        "CR9-45②：被挡下的调用**没有起线程、没有发起 fn**（不给已挂起的上游加请求）",
        threading.active_count() == threads_before and calls == 0,
        f"threads {threads_before} -> {threading.active_count()}, calls={calls}",
    )

    release.set()
    for h in holders:
        h.join(20)
    check(
        "🔁 CR9-45② 反向：在飞回落后计数归零、同一函数照常执行（上限不是恒假桩）",
        to.inflight_count() == 0 and to.run_with_timeout(lambda: "ok", 2.0, "after-cap") == ("ok", None),
        f"inflight={to.inflight_count()}",
    )


def test_abandoned_call_releases_slot() -> None:
    """被放弃的线程只算 `abandoned`，不占在飞名额 ⇒ 闸门在 ≤seconds 内自行打开。

    这条是"不需要半开探测"的依据：如果槽位跟着被放弃的线程不放，一次永久阻塞
    就会把外部取数永久锁死。
    """
    before = to.abandoned_count()
    value, err = to.run_with_timeout(lambda: time.sleep(1.0) or "late", 0.05, "abandon-slot")
    check(
        "CR9-45②：超时被放弃 → (None, TimeoutError)（CR-22/D2 语义未变）",
        value is None and isinstance(err, TimeoutError) and not isinstance(err, to.WatchdogOpenError),
        repr(err),
    )
    check(
        "CR9-45②：离开 join 即在飞归零（被放弃的线程不再占 worker）",
        to.inflight_count() == 0,
        str(to.inflight_count()),
    )
    v2, e2 = to.run_with_timeout(lambda: "ok", 2.0, "gate-self-opens")
    check(
        "🔁 CR9-45② 反向：紧接着的调用照常发起（闸门自行打开，无需重启）",
        v2 == "ok" and e2 is None,
        repr(e2),
    )
    time.sleep(1.2)  # 等被放弃的那个线程自然结束
    check(
        "CR9-45②：被放弃线程结束后 abandoned 回落（D2 递减路径没被这次改动打断）",
        to.abandoned_count() == before,
        f"before={before} after={to.abandoned_count()}",
    )


def test_health_reports_both_gauges() -> None:
    """`/health` 必须把两个数都吐出来——一次 curl 区分"进程死/线程池饿死/上游慢"。"""
    import app.main as m

    endpoint = next(
        (r.endpoint for r in m.app.routes if getattr(r, "path", None) == "/health"), None
    )
    check("CR9-45②：/health 端点存在", endpoint is not None)
    if endpoint is None:
        return
    body = asyncio.run(endpoint())
    check(
        "CR9-45②：返回体含 inflightWatchdogs / watchdogInflightCap（CR9-45 的判据字段）",
        isinstance(body.get("inflightWatchdogs"), int)
        and isinstance(body.get("watchdogInflightCap"), int),
        str(body),
    )
    check(
        "CR9-45②：CR-22 的 abandonedWatchdogs 仍在（观测字段只做加法，没删旧的）",
        isinstance(body.get("abandonedWatchdogs"), int),
        str(body),
    )


if __name__ == "__main__":
    test_cap_below_pool()
    test_gate_blocks_at_cap()
    test_abandoned_call_releases_slot()
    test_health_reports_both_gauges()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}  <- {detail[:160]}")
    sys.exit(1 if fails else 0)
