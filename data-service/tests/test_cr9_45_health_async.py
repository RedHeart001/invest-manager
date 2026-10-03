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
import tempfile

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
        "CR9-45①：返回体键齐、status=ok（改 async 没动契约；②加了在飞两字段、刀 4 加了 ingestTokenConfigured、① 加了 dbBackup）",
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
    # 🔁 反向态必须**用例自己制造**：10-03 之前 `orig` 恒为 None（本机确实没配），
    # 于是下面的 finally 走 pop 分支、这次读就是 False——那时这条断言实际测的是
    # "这台机没配"，而不是"未配 ⇒ False"。主人把值写进 `web/.env` 之后，`load_env()`
    # 会把它灌进 os.environ ⇒ `orig` 非 None ⇒ 原样放回 ⇒ 假红（10-03 实测 13/14）。
    # 与"演练不能改用例自己当输入读的那个常数"同族：判据只能由用例控制。
    try:
        os.environ.pop("INGEST_TOKEN", None)
        body2 = asyncio.run(_endpoint("/health")())
    finally:
        if orig is None:
            os.environ.pop("INGEST_TOKEN", None)
        else:
            os.environ["INGEST_TOKEN"] = orig
    check(
        "🔁 刀4/G7：显式清空 INGEST_TOKEN ⇒ False（不依赖本机配没配）",
        body2.get("ingestTokenConfigured") is False,
        str(body2),
    )
    check(
        "🔁 刀4/G7：用例结束后环境恢复原值（别的用例不得被污染）",
        os.environ.get("INGEST_TOKEN") == orig or (orig is None and "INGEST_TOKEN" not in os.environ),
        "restore mismatch",
    )


def test_db_backup_flag_is_state_only() -> None:
    """①（2026-10-02）：`/health` 的 `dbBackup` 观测位——形状稳定、未跑不谎报、不回显路径。

    为什么挂在这里：本端点的返回体就是契约面（刀 4 的 `ingestTokenConfigured` 同族）。
    备份 job 本身的行为断言在 `tests/test_backup_db.py`，这里只管"这个位能不能被一条 curl 读"。
    **#29（10-03 断电轮）之后这个位会回落读 `backups/state.json`** ⇒ 用例必须把 `BACKUP_DIR`
    收进临时目录，否则这几条断言实际在测"这台机历史上备过没有"（与刀 4 那条"用例不得把本机
    配置当输入常数"同族）。
    """
    import app.backup_scheduler as bs

    orig_backup_dir = os.environ.get("BACKUP_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["BACKUP_DIR"] = tmp
        _phase_a_never_ran(tmp)
        _phase_b_failed_round(tmp)
        _phase_c_from_disk_after_process_death()
    for _k, _v in (("BACKUP_DIR", orig_backup_dir),):
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v


def _phase_a_never_ran(tmp: str) -> None:
    """从未跑过且磁盘无状态 ⇒ 全 null（观测位不得把"没发生"渲染成"成功"）。"""
    import app.backup_scheduler as bs

    saved = dict(bs._state)
    try:
        bs._state.update({"running": False, "lastRun": None, "lastResult": None, "runs": 0})
        body = asyncio.run(_endpoint("/health")())
        bb = body.get("dbBackup")
        check("①：/health 带 dbBackup 位，且是 dict（不是裸布尔——'今天没跑过'与'跑失败'必须分得开）",
              isinstance(bb, dict), str(bb))
        check("①：从未跑过且磁盘无状态 ⇒ ok=None／lastRun=None／fromDisk=False（#29 后形状多两键）",
              bb == {"lastRun": None, "ok": None, "outcome": None, "runs": 0,
                     "nextRun": None, "fromDisk": False}, str(bb))
    finally:
        bs._state.clear()
        bs._state.update(saved)


def _phase_b_failed_round(tmp: str) -> None:
    """跑过一次（指向不存在的源库＝零写入、零出网的最便宜真实路径）。"""
    import app.backup_scheduler as bs

    orig_db_path = os.environ.get("DB_PATH")
    saved = dict(bs._state)
    try:
        os.environ["DB_PATH"] = "Z:/definitely/not/a/db/dev.db"
        bs._state.update({"running": False, "lastRun": None, "lastResult": None, "runs": 0})
        r = bs.run_once("unit-test")
        body = asyncio.run(_endpoint("/health")())
        bb = body.get("dbBackup") or {}
        dumped = json.dumps(body, ensure_ascii=False)
        check("①：失败轮 ⇒ dbBackup.ok 为 False（备份静默 no-op 必须变成可读的假）",
              r.get("ok") is False and bb.get("ok") is False, f"{r} / {bb}")
        check("①：跑过之后 lastRun 带时刻、runs 计数 +1",
              bool(bb.get("lastRun")) and bb.get("runs") == 1, str(bb))
        check("🔁 ①：返回体不出现源库路径（观测位不是文件系统清单）",
              "Z:" not in dumped,
              dumped[:200])
        check("🔁 #29：返回体也不出现状态目录路径（落盘不得开出新的文件系统面）",
              tmp not in dumped, dumped[:200])
    finally:
        if orig_db_path is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = orig_db_path
        bs._state.clear()
        bs._state.update(saved)


def _phase_c_from_disk_after_process_death() -> None:
    """#29 的正身：内存清空（＝进程死过一次的等价形态）后同一条 curl 仍读得到那一轮。"""
    import app.backup_scheduler as bs

    saved = dict(bs._state)
    try:
        bs._state.update({"running": False, "lastRun": None, "lastResult": None, "runs": 0})
        bb = (asyncio.run(_endpoint("/health")()).get("dbBackup")) or {}
        check("#29：内存清空 ⇒ 回落读磁盘那份、fromDisk=True 且 ok 仍是上轮的真值",
              bb.get("fromDisk") is True and bb.get("ok") is False and bool(bb.get("lastRun")),
              str(bb))
        check("🔁 #29：回落读来的 runs 是那份文件累计的次数（不是本进程的 0，读数口径要说满）",
              bb.get("runs") == 1, str(bb))
    finally:
        bs._state.clear()
        bs._state.update(saved)


def test_limiters_field_is_observable() -> None:
    """#27 第一步：`/health` 的 `limiters` 是**纯观测位**——有数可读，但不拦任何东西。

    挂在这里的原因与前两同一族：本端点的返回体就是契约面。要防的失败形态是"给桶外请求
    补了个族，结果那条路开始被拒"，而这件事只有 granted/denied 两个数能一眼看出来。
    """
    body = asyncio.run(_endpoint("/health")())
    lim = body.get("limiters")
    check("#27：/health 带 limiters，且是 list（不是裸布尔——'没注册'与'注册了没被调'要分得开）",
          isinstance(lim, list), str(lim))
    names = [x.get("name") for x in lim or []]
    check("#27：两个族都读得到：真桶 `eastmoney` ＋ 观测族 `akshare-obs`",
          "eastmoney" in names and "akshare-obs" in names, str(names))
    obs = next((x for x in lim or [] if x.get("name") == "akshare-obs"), {})
    check("🔁 #27：观测族 granted 恒 0（它只 observe、从不 acquire ⇒ 不可能拦下一条请求）",
          obs.get("granted") == 0 and obs.get("denied") == 0 and obs.get("cooldown") == 0.0,
          str(obs))
    dumped = json.dumps(lim, ensure_ascii=False)
    check("🔁 #27：这个位不出现 URL／域名／绝对路径（计数面不是清单，别把观测做成新的泄露口）",
          "http" not in dumped and ".com" not in dumped and "\\" not in dumped,
          dumped[:200])


if __name__ == "__main__":
    test_health_endpoint_is_async()
    test_health_response_shape_unchanged()
    test_ingest_token_flag_is_configured_state_only()
    test_db_backup_flag_is_state_only()
    test_limiters_field_is_observable()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
