"""CR7-1 / CR7-2 离线单测：研报数据支撑门控 + K 线回读日期契约。

CR7-1：技术分析师此前硬编码 `dataBased: True`，无 K 线仍进多空辩论并参与评级。
CR7-2：`collect_kline_with_phases` 回读 web /api/kline 时曾发紧凑 8 位日期，
       被 web 侧 `normalizeRange` 判为非法并静默回落 90 天 → `days` 参数失效。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr7_research.py
"""

import json
import os
import re
import sys
import types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.research.adapter as ad
import app.research.engine as en

results: list[tuple[str, bool, str]] = []

TZ_CN = timezone(timedelta(hours=8))
# web/lib/kline.ts normalizeRange 的同一条正则（跨服务契约，两侧必须一致）
WEB_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _miss() -> dict:
    return {"ok": False, "note": "模拟不可用"}


def _payload(kline_ok: bool, fund_ok: bool = True, news_ok: bool = True) -> dict:
    """各维度按 engine._compact_* 期望的真实形态构造（news.data 为列表）。"""
    market = {
        "ok": True,
        "source": "akshare",
        "note": None,
        "data": {"price": 10.0, "changePct": 1.2, "currency": "CNY"},
    }
    kline = (
        {
            "ok": True,
            "source": "akshare",
            "note": None,
            "data": {"candles": [{"date": "2026-09-01", "close": 10.0}], "phases": []},
        }
        if kline_ok
        else _miss()
    )
    news = (
        {
            "ok": True,
            "source": "cninfo",
            "note": None,
            "data": [{"title": "关于 xx 的公告", "summary": ""}],
        }
        if news_ok
        else _miss()
    )
    fundamentals = (
        {"ok": True, "source": "ths", "note": None, "data": {"periods": [{"报告期": "2026Q2"}]}}
        if fund_ok
        else _miss()
    )
    return {"market": market, "kline": kline, "news": news, "fundamentals": fundamentals}


class _LlmStub:
    """按角色 system prompt 分派假回复，并记录发给辩论的输入。"""

    def __init__(self, tech_reply: dict | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.debate_input: dict | None = None
        self._tech_reply = tech_reply

    def chat_json(self, system: str, user: str, timeout: int = 120):
        self.calls.append((system, user))
        if "技术分析师" in system:
            return self._tech_reply or {"view": "看多", "points": ["近 20 日涨 12%"]}
        if "基本面分析师" in system:
            return {"view": "中性", "points": ["营收同比 +5%"], "dataBased": True}
        if "新闻" in system and "情绪" in system:
            return {"view": "中性", "points": ["无重大新闻"], "dataBased": True}
        if "辩论主持人" in system:
            self.debate_input = json.loads(user)
            return {"bull": ["多方：涨 12%"], "bear": ["空方：估值高"]}
        if "研究经理" in system:
            return {
                "rating": "中性",
                "summary": "综合结论。仅供参考，不构成投资建议。",
                "risk": ["市场有风险"],
            }
        return None


def _run_with(payload: dict, tech_reply: dict | None = None) -> tuple[dict, _LlmStub]:
    orig_collect = ad.collect_all
    orig_chat = en.llm_client.chat_json

    def _collect(type_, code):
        gaps = [f"{d}：模拟不可用" for d, r in payload.items() if not r.get("ok")]
        return payload, gaps

    stub = _LlmStub(tech_reply)
    ad.collect_all = _collect
    en.llm_client.chat_json = stub.chat_json
    try:
        report = en.run_research("stock", "600519", "贵州茅台")
    finally:
        ad.collect_all = orig_collect
        en.llm_client.chat_json = orig_chat
    return report, stub


def _by_role(report: dict, role: str) -> dict | None:
    return next((a for a in report.get("analysts", []) if a["role"] == role), None)


# ---------------- CR7-1：dataBased 必须反映真实数据可用性 ----------------


def test_technical_not_data_based_without_kline() -> None:
    report, stub = _run_with(_payload(kline_ok=False))
    tech = _by_role(report, "技术分析师")
    check("CR7-1：无 K 线时技术分析师仍产出观点（不被整段丢弃）", tech is not None, json.dumps(report)[:160])
    check("CR7-1：无 K 线时技术分析师 dataBased 为 False", tech is not None and tech["dataBased"] is False, str(tech))
    entered = [a["role"] for a in (stub.debate_input or {}).get("analysts", [])]
    check("CR7-1：无数据支撑的技术分析师不进辩论输入", "技术分析师" not in entered, str(entered))
    check(
        "CR7-1：辩论输入里带缺口说明（点名被剔除的角色）",
        "技术分析师" in (stub.debate_input or {}).get("缺口说明", ""),
        str((stub.debate_input or {}).get("缺口说明")),
    )


def test_technical_data_based_with_kline() -> None:
    """反向验证：门控不是恒假桩——有 K 线时必须判定为有数据支撑。"""
    report, stub = _run_with(_payload(kline_ok=True))
    tech = _by_role(report, "技术分析师")
    check("CR7-1🔁：有 K 线时技术分析师 dataBased 为 True", tech is not None and tech["dataBased"] is True, str(tech))
    entered = [a["role"] for a in (stub.debate_input or {}).get("analysts", [])]
    check("CR7-1🔁：有 K 线时技术分析师参与辩论", "技术分析师" in entered, str(entered))


def test_all_dims_missing_no_analyst_claims_data() -> None:
    """三维度全不可用 → 任何角色都不得自称有数据支撑（R16：缺口不得渲染成有据结论）。"""
    report, _ = _run_with(_payload(kline_ok=False, fund_ok=False, news_ok=False))
    flags = {a["role"]: a["dataBased"] for a in report.get("analysts", [])}
    check("CR7-1：全维度缺口下无角色 dataBased 为真", flags and all(v is False for v in flags.values()), str(flags))
    check(
        "CR7-1：K线/新闻缺口不进入 meta.dimensions（仅行情可用）",
        report.get("meta", {}).get("dimensions") == ["market"],
        str(report.get("meta", {}).get("dimensions")),
    )
    check("CR7-1：全维度缺口被标为 degraded", report.get("meta", {}).get("degraded") is True)


def test_llm_dataBased_field_cannot_override_missing_data() -> None:
    """模型自报 dataBased:true 也不得越过真实数据可用性（LLM 输出不可信）。"""
    report, _ = _run_with(_payload(kline_ok=False))
    tech = _by_role(report, "技术分析师")
    check("CR7-1：模型自报字段不能覆盖缺口判定", tech is not None and tech["dataBased"] is False, str(tech))


def test_model_false_is_not_flipped_to_true() -> None:
    """双向都不越权：模型自报 `dataBased:false` 时，即便 K 线可用也不得被翻真。"""
    report, stub = _run_with(
        _payload(kline_ok=True),
        tech_reply={"view": "看空", "points": ["形态破位"], "dataBased": False},
    )
    tech = _by_role(report, "技术分析师")
    check("CR7-1🔁：模型自报 false 不被翻真（有 K 线）", tech is not None and tech["dataBased"] is False, str(tech))
    entered = [a["role"] for a in (stub.debate_input or {}).get("analysts", [])]
    check("CR7-1🔁：自报 false 的技术分析师不进辩论", "技术分析师" not in entered, str(entered))


# ---------------- CR7-2：回读 /api/kline 的日期格式与 days 生效 ----------------


def _capture_kline_request(days: int) -> dict:
    orig_requests = ad.requests
    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "candles": [{"date": "2026-09-01", "close": 10.0}],
                "phases": [],
                "source": "akshare",
            }

    def _get(url, params=None, **kw):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return _Resp()

    # 整体替换 adapter 的 requests 引用，避免污染共享的 requests 模块
    ad.requests = types.SimpleNamespace(get=_get)
    try:
        res = ad.collect_kline_with_phases("stock", "600519", days=days)
    finally:
        ad.requests = orig_requests
    captured["result"] = res
    return captured


def test_kline_read_back_uses_iso_hyphen_dates() -> None:
    cap = _capture_kline_request(120)
    p = cap["params"]
    start, end = str(p.get("start", "")), str(p.get("end", ""))
    check("CR7-2：start 为带连字符 ISO 日期", bool(WEB_ISO_RE.match(start)), start)
    check("CR7-2：end 为带连字符 ISO 日期", bool(WEB_ISO_RE.match(end)), end)
    check(
        "CR7-2🔁（反向验证）：不再是紧凑 8 位（旧缺陷形态）",
        re.fullmatch(r"\d{8}", start) is None and re.fullmatch(r"\d{8}", end) is None,
        f"{start}/{end}",
    )
    check(
        "CR7-2🔁：web 侧正则可接受（回发紧凑格式必被回落）",
        WEB_ISO_RE.match("20260601") is None and WEB_ISO_RE.match(start) is not None,
        start,
    )


def test_kline_days_window_actually_applied() -> None:
    """`days` 必须真正决定回读窗口——旧缺陷下 web 静默回落 90 天，120 与 30 无差别。"""
    span_120 = None
    span_30 = None
    for days, label in ((120, "120"), (30, "30")):
        p = _capture_kline_request(days)["params"]
        d0 = datetime.strptime(p["start"], "%Y-%m-%d")
        d1 = datetime.strptime(p["end"], "%Y-%m-%d")
        span = (d1 - d0).days
        if label == "120":
            span_120 = span
        else:
            span_30 = span
        check(f"CR7-2：days={label} 时窗口跨度为 {label} 天", span == days, str(span))
    check("CR7-2：不同 days 产出不同窗口（未被静默回落）", span_120 != span_30, f"{span_120} vs {span_30}")


def test_kline_dates_are_beijing_time() -> None:
    """日期口径必须是北京时间（C-06/§B：跨时区部署不得偏移）。"""
    p = _capture_kline_request(10)["params"]
    check("CR7-2：end 等于北京时区当日", p["end"] == datetime.now(TZ_CN).strftime("%Y-%m-%d"), str(p.get("end")))


def test_akshare_side_keeps_compact_dates() -> None:
    """akshare/cninfo 侧仍须紧凑 8 位——防止后续"统一日期格式"把这一侧一起改掉。"""
    captured: dict = {}

    def _fn(**kw):
        captured.update(kw)
        return []  # 空表 → 被测函数抛 RuntimeError，参数已捕获

    fake = types.ModuleType("akshare")
    fake.stock_zh_a_disclosure_report_cninfo = _fn
    orig = sys.modules.get("akshare")
    sys.modules["akshare"] = fake
    try:
        try:
            ad.ak_stock_disclosures("600519")
        except RuntimeError:
            pass
    finally:
        if orig is not None:
            sys.modules["akshare"] = orig
        else:
            sys.modules.pop("akshare", None)

    sd = str(captured.get("start_date", ""))
    ed = str(captured.get("end_date", ""))
    check(
        "CR7-2🔁：cninfo 侧日期仍为紧凑 8 位（未受本次改动波及）",
        bool(re.fullmatch(r"\d{8}", sd)) and bool(re.fullmatch(r"\d{8}", ed)),
        f"{sd}/{ed}",
    )
    check("CR7-2🔁：cninfo 侧不含连字符", "-" not in sd and "-" not in ed, f"{sd}/{ed}")


if __name__ == "__main__":
    test_technical_not_data_based_without_kline()
    test_technical_data_based_with_kline()
    test_all_dims_missing_no_analyst_claims_data()
    test_llm_dataBased_field_cannot_override_missing_data()
    test_model_false_is_not_flipped_to_true()
    test_kline_read_back_uses_iso_hyphen_dates()
    test_kline_days_window_actually_applied()
    test_kline_dates_are_beijing_time()
    test_akshare_side_keeps_compact_dates()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
