"""CR9-28 离线单测：/sync/status 的 ok 必须等于 web 的真 ok。

编号说明：本项原登记为 **CR9-5**（"`/sync/run` 无 type 白名单"），实施前复核发现
`main.py` 的 `sync_run(trigger=...)` 根本没有 type 参数、web `/api/sync` 也早有
`SYNC_TYPES` 白名单 ⇒ **CR9-5 已撤回**，同处发现的真缺陷另立 **CR9-28**。
背景（2026-09-26 实测）：`_execute` 此前把结果硬写成 `{"ok": True, ...}`，而 web
`POST /api/sync` 返回的是 `results.every(r => !r.error)`。于是当天 5 类里 4 类
（stock/bond/crypto/hk）全失败时，`/sync/status` 仍显示 `ok:true` —— 唯一能判断
"今天要不要补跑"的状态位是假的。

反向验证成对断言（C34）：既断"部分失败 → ok=False"，也断"全成功 → ok=True"，
证明 `ok` 不是恒假桩，而是真跟着 web 的判定走。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr9_sync_status.py
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

import app.sync_scheduler as ss  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


class _Resp:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def _run_with(body: dict, status: int = 200) -> dict:
    """用假 web 响应跑一次 _execute，返回 lastResult。"""
    orig = requests.post
    requests.post = lambda *a, **k: _Resp(body, status)
    saved = dict(ss._state)
    try:
        ss._state["running"] = True  # _execute 假定调用方已认领
        return ss._execute("unit-test")
    finally:
        requests.post = orig
        ss._state.clear()
        ss._state.update(saved)


def test_partial_failure_is_not_ok() -> None:
    body = {
        "tookMs": 455066,
        "ok": False,  # web 的真实判定
        "results": [
            {"type": "stock", "error": "eastmoney request failed on all hosts", "tookMs": 18982},
            {"type": "fund", "count": 27954, "tookMs": 434754},
            {"type": "bond", "error": "payload shrunk", "tookMs": 1293},
            {"type": "crypto", "error": "coingecko cooling down", "tookMs": 11},
            {"type": "hk", "error": "eastmoney cooling down", "tookMs": 13},
        ],
    }
    r = _run_with(body)
    check("CR9-28：部分类型失败 → ok=False（不再硬写成功）", r.get("ok") is False, str(r.get("ok")))
    check("CR9-28：failedTypes 精确列出 4 类",
          r.get("failedTypes") == ["stock", "bond", "crypto", "hk"], str(r.get("failedTypes")))
    check("CR9-28：note 显式说明不自动重试与补跑入口（R16）",
          "部分类型失败" in str(r.get("note") or "") and "/sync/run" in str(r.get("note") or ""),
          str(r.get("note")))
    check("CR9-28：results 原文保留（逐类型 error 不被吞）", len(r.get("results") or []) == 5,
          str(len(r.get("results") or [])))


def test_full_success_is_ok() -> None:
    # 反向验证的第二条：若把 `ok` 写成常量 False，本断言即失败
    body = {
        "tookMs": 500000,
        "ok": True,
        "results": [
            {"type": "stock", "count": 5913},
            {"type": "fund", "count": 27954},
            {"type": "bond", "count": 1059},
            {"type": "crypto", "count": 250},
            {"type": "hk", "count": 4707},
        ],
    }
    r = _run_with(body)
    check("CR9-28：全类型成功 → ok=True 且无 failedTypes（证明不是恒假桩）",
          r.get("ok") is True and "failedTypes" not in r, str(r))


def test_lastdate_set_even_on_partial() -> None:
    """有意的取舍：部分失败仍置 lastDate（避免 10min 级同步被反复重试打爆东财源族）。

    这里断言的是"记录与行为一致"——若将来改成失败不置位，本断言会失败并要求同步更新文档。
    """
    body = {"ok": False, "results": [{"type": "hk", "error": "boom"}], "tookMs": 1}
    orig = requests.post
    requests.post = lambda *a, **k: _Resp(body)
    saved = dict(ss._state)
    try:
        ss._state["running"] = True
        ss._execute("unit-test")
        check("CR9-28：失败轮仍置 lastDate（不重试是有意设计，需改动时先改文档）",
              ss._state["lastDate"] == ss.beijing_today(), str(ss._state["lastDate"]))
    finally:
        requests.post = orig
        ss._state.clear()
        ss._state.update(saved)


def test_http_rejection_still_error() -> None:
    r = _run_with({"error": "forbidden"}, status=403)
    check("CR9-28：web 拒绝（非 2xx）仍记 error，不被 ok 逻辑影响",
          r.get("ok") is not True and "HTTP 403" in str(r.get("error")), str(r))


def main() -> int:
    test_partial_failure_is_not_ok()
    test_full_success_is_ok()
    test_lastdate_set_even_on_partial()
    test_http_rejection_still_error()
    passed = sum(1 for _n, ok, _d in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"[FAIL] {name}  <- {detail}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
