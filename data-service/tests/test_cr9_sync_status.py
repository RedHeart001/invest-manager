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
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
# 自带 UTF-8 输出后，跑本脚本不再需要 PYTHONIOENCODING（errors=replace 兜极端情况）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


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


def _run_raising(exc: BaseException) -> dict:
    """让回调本身抛异常（刀 1 用它造 ReadTimeout＝web 根本不回答）。"""
    orig = requests.post

    def _boom(*a, **k):
        raise exc

    requests.post = _boom
    saved = dict(ss._state)
    try:
        ss._state["running"] = True
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
    # 刀 1（#20②）：outcome 四态之一——web 回答了且有类型失败
    check("刀1：outcome=partial_failed（与 ok=False 同源，不是另算的）",
          r.get("outcome") == "partial_failed", str(r.get("outcome")))


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
    # 刀 1：outcome 在"web 回答且全成功"这一档必须是 completed——
    # 🔁 与下面的 inconclusive 成对，证明 outcome 不是"凡超时都写同一句"的桩
    check("刀1：outcome=completed（成功档不被第三态污染）",
          r.get("outcome") == "completed", str(r.get("outcome")))


def test_read_timeout_is_inconclusive_not_ok() -> None:
    """刀 1（#20②）：读超时＝**未知**，不再写 `ok=True`。

    触发实据（10-01 手动全量同步）：`tookMsTotal=1800030`／`error=ReadTimeout`，
    而那一轮真入库的只有 fund（stock/crypto/hk 三条腿 502、bond 未写入）——
    旧语义下状态位却是 `ok:true`，等于把"这轮到底成没成"这个唯一判据丢掉。
    C3-③ 的原意（读超时 ≠ 失败）保留：`ok` 既不是真也不是假＝`None`，
    并由 `outcome="inconclusive"` 明确表达；lastDate 仍置位（不自动重跑是既定取舍）。
    """
    r = _run_raising(requests.exceptions.ReadTimeout("read timeout=1800.0"))
    check("刀1：读超时 → ok is None（不再是 True）", r.get("ok") is None, repr(r.get("ok")))
    check("🔁 刀1 反向：读超时的 ok 既不是真也不是假（若编码成 True/False 本断言即红）",
          r.get("ok") is not True and r.get("ok") is not False, repr(r.get("ok")))
    check("刀1：outcome=inconclusive", r.get("outcome") == "inconclusive", str(r.get("outcome")))
    check("刀1：note 说清「未知」并给出可查的两处证据（updatedAt/snapshotAt），R16",
          "未知" in str(r.get("note") or "") and "snapshotAt" in str(r.get("note") or ""),
          str(r.get("note")))
    check("刀1：原始异常仍保留在 error 字段（可排查，没被中性化吞掉）",
          "ReadTimeout" in str(r.get("error") or ""), str(r.get("error")))
    # 与 C3-③ 的既有语义一致：不自动重跑 ⇒ lastDate 照常置位（本改动只动状态位，不动调度）
    orig = requests.post

    def _boom(*a, **k):
        raise requests.exceptions.ReadTimeout("read timeout=1800.0")

    requests.post = _boom
    saved = dict(ss._state)
    try:
        ss._state["running"] = True
        ss._state["lastDate"] = None
        ss._execute("unit-test")
        check("刀1：第三态下 lastDate 仍置位（「不自动重跑」是有意取舍，本改动不动它）",
              ss._state.get("lastDate") == ss.beijing_today(), str(ss._state.get("lastDate")))
    finally:
        requests.post = orig
        ss._state.clear()
        ss._state.update(saved)


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
    test_read_timeout_is_inconclusive_not_ok()
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
