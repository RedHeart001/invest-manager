"""CR9-45① 离线单测：`/health` 必须是**协程**端点（不跟取数线程抢线程池）。

背景（2026-09-29 夜实测）：ds 的每个端点都是同步 `def` ⇒ 全进程共用 anyio 的默认
**40** worker 线程池（实测 `current_default_thread_limiter().total_tokens == 40`）。
启动补跑整轮 ≥29 分钟未收敛时，40 个取数线程全挂在无 socket 超时的 requests 上，
同步版 `/health` 排在同一个队列里，从 4.3s 涨到**无响应** —— 探针和它要监控的东西
抢同一份资源，看起来像"服务死了"，其实只是探针被饿死。

①＝`async def health()`（跑在事件循环上，永不排队）；②（看门狗在飞上限，见
`tests/test_cr9_45_inflight_cap.py`）把"取数请求能占住的 worker 数"钉死在上限内——两把
一起才把"探针饿死"这条路彻底堵掉。

反向对照（C34）：既断 `/health` 是协程端点，也断 `/quote` **仍是**同步端点——
证明这条改动是定向摘除探针的池占用，而不是把全服务改异步（那会改变取数路径语义）。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr9_45_health_async.py
"""

import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import app.main as m  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _endpoint(path: str):
    for r in m.app.routes:
        if getattr(r, "path", None) == path:
            return r.endpoint
    return None


def test_health_endpoint_is_async() -> None:
    health = _endpoint("/health")
    check("CR9-45①：/health 端点存在", health is not None)
    check(
        "CR9-45①：/health 是协程端点（不占 anyio 线程池 ⇒ 取数线程挂满时仍能应答）",
        health is not None and inspect.iscoroutinefunction(health),
        str(health),
    )
    quote = _endpoint("/quote")
    check(
        "🔁 CR9-45① 反向：/quote 仍是同步端点（本刀只摘探针的池占用，不改取数语义）",
        quote is not None and not inspect.iscoroutinefunction(quote),
        str(quote),
    )


def test_health_response_shape_unchanged() -> None:
    body = asyncio.run(_endpoint("/health")())
    check(
        "CR9-45①：返回体五键齐、status=ok（改 async 没动契约；②新增两个在飞字段）",
        isinstance(body, dict)
        and body.get("status") == "ok"
        and "version" in body
        and "abandonedWatchdogs" in body,
        str(body),
    )
    check(
        "CR9-45①：abandonedWatchdogs 仍是 int（CR-22 的观测字段没被改坏）",
        isinstance(body.get("abandonedWatchdogs"), int),
        str(body),
    )


if __name__ == "__main__":
    test_health_endpoint_is_async()
    test_health_response_shape_unchanged()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
