"""C3（CR7-9）+ CR9-33 离线单测：读超时 ≠ 同步失败 + 超时参数依据。

背景（2026-09-25 C0 实测）：全 5 类型同步 9.6~13 分钟。此前 ds 侧对
web 回调的 ReadTimeout 会记成 error——但 web 侧同步仍在后台执行且
lastDate 已置位不再重跑，状态失真（"实际成功被记成失败"）。
CR9-33（2026-09-27）追加：补跑态实测 ≥29 分钟会打穿定时态预算 ⇒ 预算分形态。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_c3_readtimeout.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
# 自带 UTF-8 输出后，跑本脚本不再需要 PYTHONIOENCODING（errors=replace 兜极端情况）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


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


def test_callback_timeout_by_form() -> None:
    """③ CR9-33：回调读超时按**触发形态**取预算（一轮同步耗时实测差一个数量级）。

    定时态 runs=1 逐类合计约 430s；补跑态 09-26 实测 ≥29 分钟仍未收敛——
    两者共用 1800s 时，补跑态必然把"仍在正常执行的同步"记成读超时。
    """
    seen: dict[str, object] = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"ok": True, "tookMs": 1, "results": []}

    def _capture(url, timeout=None, **kw):
        seen["timeout"] = timeout
        return _Resp()

    orig_post = real_requests.post
    real_requests.post = _capture
    try:
        for trigger, expected in (
            ("daily", ss.SCHEDULED_CALLBACK_TIMEOUT_S),
            (ss.CATCHUP_TRIGGER, ss.CATCHUP_CALLBACK_TIMEOUT_S),
            ("manual-ui", ss.SCHEDULED_CALLBACK_TIMEOUT_S),  # 未知/手动 → 定时态口径
        ):
            ss._state["running"] = True
            res = ss._execute(trigger)
            check(f"CR9-33：形态 {trigger} 的回调预算 = {int(expected)}s",
                  seen.get("timeout") == expected, f"got={seen.get('timeout')}")
            check(f"CR9-33：本次预算回写进状态（/sync/status 可判定）",
                  res.get("callbackTimeoutS") == int(expected), str(res)[:120])
    finally:
        real_requests.post = orig_post
        ss._state["running"] = False
        ss._state["lastDate"] = None
        ss._state["lastResult"] = None

    check("CR9-33🔁：两个形态确实分别取数（相同就等于没分形态）",
          ss.SCHEDULED_CALLBACK_TIMEOUT_S != ss.CATCHUP_CALLBACK_TIMEOUT_S)
    check("CR9-33🔁：补跑态预算盖过 09-26 实测的 ≥29 分钟",
          ss.CATCHUP_CALLBACK_TIMEOUT_S > 29 * 60, f"{ss.CATCHUP_CALLBACK_TIMEOUT_S}s")
    check("CR9-33🔁：补跑态 trigger 与 _catch_up_if_needed 用的是同一个常量",
          ss.CATCHUP_TRIGGER == "startup-catchup")


if __name__ == "__main__":
    test_read_timeout_is_not_failure()
    test_other_errors_still_failure()
    test_callback_timeout_by_form()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
