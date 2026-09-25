"""C3（CR7-9）离线单测：读超时 ≠ 同步失败 + 超时参数依据。

背景（2026-09-25 C0 实测）：全 5 类型同步 9.6~13 分钟。此前 ds 侧对
web 回调的 ReadTimeout 会记成 error——但 web 侧同步仍在后台执行且
lastDate 已置位不再重跑，状态失真（"实际成功被记成失败"）。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_c3_readtimeout.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.sync_scheduler as ss  # noqa: E402
import requests as real_requests  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def test_read_timeout_is_not_failure() -> None:
    """① ReadTimeout → ok=True + 中性 note（非失败标记），error 保留原始异常。"""
    def _boom(url, timeout=None, **kw):
        raise real_requests.exceptions.ReadTimeout("read timed out")

    orig_post = real_requests.post
    real_requests.post = _boom
    ss._state["running"] = True
    try:
        res = ss._execute("test")
        check("C3：ReadTimeout 时 ok=True（非失败标记）", res.get("ok") is True, str(res)[:160])
        check("C3：note 说明去向（查 /api/sync 或 updatedAt）", "Product.updatedAt" in (res.get("note") or ""), str(res.get("note"))[:160])
        check("C3：error 字段保留原始异常供排查", "ReadTimeout" in (res.get("error") or ""), str(res.get("error")))
        check("C3：lastDate 已置位（今日不重跑）", ss._state.get("lastDate") is not None, str(ss._state.get("lastDate")))
    finally:
        real_requests.post = orig_post
        ss._state["running"] = False
        ss._state["lastDate"] = None
        ss._state["lastResult"] = None


def test_other_errors_still_failure() -> None:
    """② 非 ReadTimeout 异常（如连接拒绝）→ 仍如实记 error（不粉饰）。"""
    def _boom(url, timeout=None, **kw):
        raise ConnectionError("connection refused")

    orig_post = real_requests.post
    real_requests.post = _boom
    ss._state["running"] = True
    try:
        res = ss._execute("test")
        check("C3：连接拒绝仍记失败", res.get("ok") is None and "ConnectionError" in (res.get("error") or ""), str(res)[:160])
    finally:
        real_requests.post = orig_post
        ss._state["running"] = False
        ss._state["lastDate"] = None
        ss._state["lastResult"] = None


if __name__ == "__main__":
    test_read_timeout_is_not_failure()
    test_other_errors_still_failure()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
