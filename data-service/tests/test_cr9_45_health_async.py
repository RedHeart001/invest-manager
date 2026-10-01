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

刀 4/G7（2026-10-01）追加：本端点还报 `ingestTokenConfigured`——入库鉴权"配没配"的状态位
（只布尔、不回显值），让"只配了一侧 ⇒ 入库全 401 且静默丢失"这种失败一条 curl 就能查出。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr9_45_health_async.py
"""

import asyncio
import inspect
import json
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
        "CR9-45①：返回体键齐、status=ok（改 async 没动契约；②加了在飞两字段、刀 4 加了 ingestTokenConfigured）",
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


def test_ingest_token_flag_is_configured_state_only() -> None:
    """刀 4/G7：`/health` 把"ds 侧配没配 `INGEST_TOKEN`"做成状态位——**只报布尔、不回显值**。

    为什么要有这个位：入库回调带 token 的代码早就在（`hotspot/pipeline.py:652`、
    `research/tasks.py:131`），开启鉴权只剩"两侧同名 env 填成同一个值"这一件事；配错的
    表现是入库全 401 且热点/研报静默丢失，而 ds 的 `log.warning` 在 uvicorn 默认配置下
    不一定看得见（#21 同族理由）。⇒ 一条 curl 就该能核对出来。
    """
    sentinel = "SENTINEL-DO-NOT-LEAK-123"
    orig = os.environ.get("INGEST_TOKEN")
    try:
        os.environ["INGEST_TOKEN"] = sentinel
        body = asyncio.run(_endpoint("/health")())
        dumped = json.dumps(body, ensure_ascii=False)
        check(
            "刀4/G7：配了 INGEST_TOKEN ⇒ ingestTokenConfigured 为 True",
            body.get("ingestTokenConfigured") is True,
            str(body),
        )
        check(
            "刀4/G7：这个位是布尔、不是 token 本身",
            isinstance(body.get("ingestTokenConfigured"), bool),
            str(body),
        )
        check(
            "🔁 刀4/G7：返回体任何位置都不出现 token 值（观测位不得变成泄露口）",
            sentinel not in dumped,
            dumped[:160],
        )
    finally:
        if orig is None:
            os.environ.pop("INGEST_TOKEN", None)
        else:
            os.environ["INGEST_TOKEN"] = orig
    body2 = asyncio.run(_endpoint("/health")())
    check(
        "🔁 刀4/G7：未配 INGEST_TOKEN ⇒ False（本机现状＝web 侧鉴权分支恒不生效）",
        body2.get("ingestTokenConfigured") is False,
        str(body2),
    )


if __name__ == "__main__":
    test_health_endpoint_is_async()
    test_health_response_shape_unchanged()
    test_ingest_token_flag_is_configured_state_only()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
