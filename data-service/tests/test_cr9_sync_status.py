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


class _Legs:
    """按 URL 分派的假 web（刀 3/甲-1 之后一轮有**两条腿**，不能再一份响应糊两次调用）。

    记录每次调用的 (url, timeout)，让"刷新腿用的是它自己的预算"这件事可断言。
    """

    def __init__(self, sync_resp=None, sync_exc=None, refresh_resp=None, refresh_exc=None):
        self.calls: list[tuple[str, object]] = []
        self.running_during_refresh: list[bool] = []
        self._sync_resp = sync_resp
        self._sync_exc = sync_exc
        self._refresh_resp = refresh_resp
        self._refresh_exc = refresh_exc

    def __call__(self, url, timeout=None, **kw):
        self.calls.append((url, timeout))
        if "market/refresh" in url:
            # running 必须仍为 True：单飞要覆盖整轮两条腿，否则刷新中途能被再点一次同步
            self.running_during_refresh.append(bool(ss._state["running"]))
            if self._refresh_exc:
                raise self._refresh_exc
            return self._refresh_resp or _Resp({"tookMs": 10, "results": []})
        if self._sync_exc:
            raise self._sync_exc
        return self._sync_resp or _Resp({"ok": True, "tookMs": 1, "results": []})


def _run_two_legs(sync_resp=None, sync_exc=None, refresh_resp=None, refresh_exc=None):
    """跑一次完整的 `_execute`（两条腿），返回 (同步腿结果, 刷新腿结果, 假 web 记录)。"""
    legs = _Legs(sync_resp, sync_exc, refresh_resp, refresh_exc)
    orig = requests.post
    requests.post = legs  # type: ignore[assignment]
    saved = dict(ss._state)
    try:
        ss._state["running"] = True
        ss._state["lastRefresh"] = None
        r = ss._execute("unit-test")
        return r, dict(ss._state.get("lastRefresh") or {}), legs
    finally:
        requests.post = orig
        ss._state.clear()
        ss._state.update(saved)


def test_chain_refresh_fires_after_sync_leg() -> None:
    """刀 3/甲-1：同步腿完成后**链式**触发刷新腿，且刷新腿用的是它自己的预算。"""
    ok_body = _Resp({"ok": True, "tookMs": 61_000,
                     "results": [{"type": "stock", "count": 5913}]})
    r, refresh, legs = _run_two_legs(sync_resp=ok_body)
    urls = [u for u, _t in legs.calls]
    check("甲-1：一轮里有两条腿，第二条是 /api/market/refresh?type=all",
          len(urls) == 2 and "market/refresh" in urls[1], str(urls))
    check("甲-1：同步腿仍用 CR9-33 的形态预算（拆腿没顺手改它）",
          legs.calls[0][1] == ss.SCHEDULED_CALLBACK_TIMEOUT_S, str(legs.calls[0]))
    check("甲-1：刷新腿自带独立预算 2400s（≈ 实测基数 1,700s 的 1.4 倍）",
          legs.calls[1][1] == ss.REFRESH_CALLBACK_TIMEOUT_S == 2400.0, str(legs.calls[1]))
    check("甲-1🔁：两条腿的预算**不同**（相同就等于没拆——一件事又去盖另一件事）",
          ss.REFRESH_CALLBACK_TIMEOUT_S != ss.SCHEDULED_CALLBACK_TIMEOUT_S)
    check("甲-1：刷新腿的结果单独成家（lastRefresh，不污染 lastResult）",
          refresh.get("outcome") == "completed" and refresh.get("ok") is True, str(refresh))
    check("甲-1：`running` 覆盖整轮两条腿 ⇒ 刷新中途不会被再点一次同步",
          legs.running_during_refresh == [True], str(legs.running_during_refresh))
    check("甲-1：_execute 返回的仍是**同步腿**那份（状态位各自归家）",
          r.get("outcome") == "completed" and "refresh" not in r, str(r)[:160])


def test_chain_refresh_also_fires_on_partial_failure() -> None:
    """部分类型失败仍要刷：成功入库的那几类没有价，分类浏览就整类排序失效。"""
    body = _Resp({"ok": False, "tookMs": 1, "results": [
        {"type": "stock", "error": "eastmoney cooling down"},
        {"type": "fund", "count": 27954},
    ]})
    _r, refresh, legs = _run_two_legs(sync_resp=body)
    check("甲-1：同步腿 partial_failed ⇒ 刷新腿照常触发（不是只在 full success 才刷）",
          len(legs.calls) == 2 and refresh.get("outcome") == "completed", str(refresh))


def test_chain_refresh_skipped_when_sync_leg_unanswered() -> None:
    """🔁 反向：web 没把列表这件事收尾 ⇒ **不刷**。

    两条理由不同（都写进 skippedReason）：
      · inconclusive（读超时）＝web 可能还在 DELETE＋INSERT 换表，此刻刷价格会把结果
        写进即将被删的行（`web/lib/sync.ts` 的整表替换语义）；
      · rejected/failed＝web 根本没接活，刷的仍是昨天那批行。
    """
    _r, refresh, legs = _run_two_legs(sync_exc=requests.exceptions.ReadTimeout("read timeout"))
    check("甲-1🔁：同步腿读超时 ⇒ 刷新腿不触发（零第二次调用）",
          len(legs.calls) == 1 and refresh.get("outcome") == "skipped", str(refresh))
    check("甲-1：skipped 的理由说得出「会被删除的行」这个具体危害（R16）",
          "即将被删除的行" in str(refresh.get("skippedReason") or ""),
          str(refresh.get("skippedReason")))

    _r2, refresh2, legs2 = _run_two_legs(sync_resp=_Resp({"error": "no"}, status=403))
    check("甲-1🔁：同步腿被拒（4xx）⇒ 刷新腿也不触发",
          len(legs2.calls) == 1 and refresh2.get("outcome") == "skipped", str(refresh2))
    check("甲-1：被拒档的理由是「web 未接活」，与读超时档不同",
          "未接活" in str(refresh2.get("skippedReason") or ""),
          str(refresh2.get("skippedReason")))


def test_refresh_leg_own_outcome_semantics() -> None:
    """刷新腿继承同步腿那条不变量：`ok` 只在 web 真回答时带真假。

    web 的 `/api/market/refresh` **不返回 ok**（只有 tookMs/results），所以 ds 侧的 `ok`
    由逐类 `failedBatches` 导出——这不是"替 web 下结论"，而是"web 没给的绝不编造"：
    任一类有失败批次即 `ok=False`，读超时仍是 `None`。
    """
    weak = _Resp({"tookMs": 1_700_000, "results": [
        {"type": "fund", "total": 28000, "updated": 24069, "failedBatches": 3,
         "snapshotAt": "2026-10-02T01:20:00.000Z"},
        {"type": "stock", "total": 5913, "updated": 5902, "failedBatches": 0,
         "snapshotAt": "2026-10-02T01:10:00.000Z"},
    ]})
    _r, refresh, _legs = _run_two_legs(
        sync_resp=_Resp({"ok": True, "tookMs": 1, "results": []}), refresh_resp=weak
    )
    check("甲-1：刷新腿按 failedBatches 判失败 ⇒ ok=False／outcome=partial_failed",
          refresh.get("ok") is False and refresh.get("outcome") == "partial_failed",
          str(refresh))
    check("甲-1：weakTypes 点名到类（fund 那 3 个失败批次不能只写成一句「部分失败」）",
          refresh.get("weakTypes") == ["fund"], str(refresh.get("weakTypes")))
    check("甲-1：逐类 results 原文保留（updated/total/snapshotAt 是可判据）",
          len(refresh.get("results") or []) == 2, str(refresh.get("results"))[:160])
    check("甲-1：刷新腿自己的预算也回写进状态（CR9-33 同族纪律）",
          refresh.get("callbackTimeoutS") == 2400, str(refresh.get("callbackTimeoutS")))

    _r2, refresh2, _l2 = _run_two_legs(
        sync_resp=_Resp({"ok": True, "tookMs": 1, "results": []}),
        refresh_exc=requests.exceptions.ReadTimeout("read timeout=2400.0"),
    )
    check("🔁 甲-1：刷新腿读超时 ⇒ ok=None＋inconclusive（与同步腿同一不变量，不是失败）",
          refresh2.get("ok") is None and refresh2.get("outcome") == "inconclusive",
          str(refresh2))


def test_status_exposes_skip_and_refresh() -> None:
    """#21＋甲-1：`/sync/status` 必须自己说得出"刷新腿这一轮去哪了"。"""
    saved = dict(ss._state)
    try:
        ss._state.update({"skippedReason": None, "lastRefresh": None})
        st = ss.status()
        check("#21：status 带 skippedReason 键（None＝没有待说明的跳过，不是缺字段）",
              "skippedReason" in st and st["skippedReason"] is None, str(st)[:120])
        check("甲-1：status 带 lastRefresh 键", "lastRefresh" in st, str(st)[:120])
        ss._set_skip("catchup: SYNC_CATCHUP=off（每日 cron 不受影响）")
        st2 = ss.status()
        check("#21：跳过原因写进状态位后可被 curl 读出（不必翻日志）",
              "SYNC_CATCHUP=off" in str(st2.get("skippedReason")), str(st2.get("skippedReason")))
    finally:
        ss._state.clear()
        ss._state.update(saved)


def main() -> int:
    test_partial_failure_is_not_ok()
    test_full_success_is_ok()
    test_read_timeout_is_inconclusive_not_ok()
    test_lastdate_set_even_on_partial()
    test_http_rejection_still_error()
    test_chain_refresh_fires_after_sync_leg()
    test_chain_refresh_also_fires_on_partial_failure()
    test_chain_refresh_skipped_when_sync_leg_unanswered()
    test_refresh_leg_own_outcome_semantics()
    test_status_exposes_skip_and_refresh()
    passed = sum(1 for _n, ok, _d in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"[FAIL] {name}  <- {detail}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
