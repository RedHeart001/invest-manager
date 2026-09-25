"""C6a 离线单测：腾讯分钟线备源（累计→增量 diff、日期/时区口径、注册链生效）。

背景（2026-09-25）：分钟线此前仅东财单源，端点抖动/熔断时 1D 档位必挂
（verify-all p2「1D 分钟线」inconclusive 的根因）。腾讯分时接口实测形态：
- data.<sym>.data.data = ["0930 1250.01 183 22875182.71", ...]（HHMM、价、累计量手、累计额元）
- 东财主源 volume 为每分钟增量 → 备源必须 diff，否则量柱形态不一致。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_tencent_minute.py
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.providers.tencent_provider as tp  # noqa: E402
from app.providers import get_provider_chain  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# 按实测形态构造的 mock 响应（0930 竞价 + 两根 + 1530 收）
_RAW_ROWS = [
    "0930 1250.01 183 22875182.71",
    "0931 1249.99 1393 174122899.37",
    "0932 1247.28 1393 174122899.37",  # 平量（diff 后为 0）
    "1530 1237.00 31245 3868009791.36",
]


def _mock_response() -> dict:
    return {
        "code": 0,
        "msg": "",
        "data": {
            "sh600519": {
                "data": {"data": _RAW_ROWS, "date": "20260924"},
                "qt": {
                    "v_ff_sh600519": "",
                    "sh600519": ["1", "贵州茅台", "600519", "1237.00", "1251.24"],
                    "market": "",
                },
                "mx_price": {"price": "", "mx": ""},
            }
        },
    }


def _run_minute(code: str = "600519"):
    orig_requests = tp.requests
    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return _mock_response()

    def _get(url, params=None, **kw):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return _Resp()

    tp.requests = types.SimpleNamespace(get=_get)
    try:
        result = tp._provider.get_kline("stock", code, interval="1m")
    finally:
        tp.requests = orig_requests
    return result, captured


def test_minute_candles_cumulative_diff() -> None:
    res, _ = _run_minute()
    c = res["candles"]
    check("C6a：candles 数量与行数一致", len(c) == len(_RAW_ROWS), str(len(c)))
    # 累计 → 增量：183 原样 / 1393-183=1210 / 1393-1393=0 / 31245-1393=29852
    vols = [x["volume"] for x in c]
    check("C6a：首行量为竞价原值 183", vols[0] == 183.0, str(vols[0]))
    check("C6a：第二行为 diff 增量 1210", vols[1] == 1210.0, str(vols[1]))
    check("C6a：平量行为 0（不出现累计值）", vols[2] == 0.0, str(vols[2]))
    check(
        "C6a：总量守恒（diff 后 sum = 末行累计）",
        abs(sum(vols) - 31245.0) < 1e-6,
        str(sum(vols)),
    )


def test_minute_date_and_shape() -> None:
    res, _ = _run_minute()
    c = res["candles"]
    check("C6a：date 为带连字符的当日 + HH:MM", c[0]["date"] == "2026-09-24 09:30", c[0]["date"])
    check("C6a：OHLC 四值同价（分时仅单价）", c[1]["open"] == c[1]["close"] == c[1]["high"] == c[1]["low"] == 1249.99)
    check("C6a：interval=1m 标注", res["interval"] == "1m", str(res.get("interval")))
    check("C6a：source=tencent", res["source"] == "tencent")
    amount = c[1]["amount"]
    check("C6a：amount 同口径 diff", abs(amount - (174122899.37 - 22875182.71)) < 0.01, str(amount))


def test_minute_via_provider_chain() -> None:
    """主源失败时 chain_call 落到腾讯分钟线（备源生效的端到端证明）。"""
    chain = [p.source for p in get_provider_chain("stock")]
    check("C6a：stock 链含腾讯备源", "tencent" in chain, str(chain))

    import app.providers.akshare_provider as ap
    from app.providers.chain import chain_call

    orig_em = ap._em_request
    orig_requests = tp.requests

    def _fail_em(fn):
        raise ap.ProviderError("eastmoney cooling down (rate-limited); fallback to backup source")

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return _mock_response()

    tp.requests = types.SimpleNamespace(
        get=lambda url, params=None, **kw: _Resp()
    )
    ap._em_request = _fail_em
    try:
        res = chain_call("stock", lambda p: p.get_kline("stock", "600519", interval="1m"))
        check("C6a：主源熔断 → chain 降级到腾讯分钟线", res.get("source") == "tencent", str(res.get("source")))
        check("C6a：降级标注写入 note", "降级至 tencent" in (res.get("note") or ""), str(res.get("note"))[:120])
    finally:
        ap._em_request = orig_em
        tp.requests = orig_requests


def test_minute_unsupported_type_rejected() -> None:
    """us（yfinance 域）不支持分钟线——显式 ProviderNotSupported，不得静默。

    注：场外基金（非 ETF 前缀，如 012414）实测腾讯返回单行占位 "  0"（空数据）
    → 解析后 parsed 为空 → ProviderError（走失败窗口），同样不会静默半成品。
    """
    try:
        tp._provider.get_kline("us", "AAPL", interval="1m")
        check("C6a：us 分钟线被拒绝", False, "未抛异常")
    except tp.ProviderNotSupported:
        check("C6a：us 分钟线被拒绝（显式 NotSupported）", True)
    except Exception as e:  # noqa: BLE001
        check("C6a：us 分钟线被拒绝", False, f"异常类型错误: {type(e).__name__}: {e}")

    # 转债 110022 → sh110022（_symbol 的 11 前缀映射正确，属支持范围，仅验证映射）
    check("C6a：转债代码映射 sh 前缀", tp._symbol("110022") == "sh110022", str(tp._symbol("110022")))


def test_minute_otc_fund_empty_raises() -> None:
    """场外基金（012414 实测返回单行占位 '  0'）→ 解析为空 → ProviderError，不静默半成品。"""
    orig_requests = tp.requests

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "code": 0,
                "msg": "",
                "data": {"sz012414": {"data": {"data": ["  0"], "date": "20260924"}, "qt": {}}},
            }

    tp.requests = types.SimpleNamespace(get=lambda url, params=None, **kw: _Resp())
    try:
        tp._provider.get_kline("fund", "012414", interval="1m")
        check("C6a：场外基金空数据 → ProviderError", False, "未抛异常")
    except tp.ProviderError:
        check("C6a：场外基金空数据 → ProviderError（不静默半成品）", True)
    finally:
        tp.requests = orig_requests


def test_minute_empty_raises() -> None:
    """空响应/缺日期 → ProviderError（进失败窗口，而非返回半成品）。"""

    def _run_with(rows, date):
        orig_requests = tp.requests

        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "data": {
                        "sh600519": {
                            "data": {"data": rows, "date": date},
                            "qt": {},
                        }
                    }
                }

        tp.requests = types.SimpleNamespace(get=lambda url, params=None, **kw: _Resp())
        try:
            tp._provider.get_kline("stock", "600519", interval="1m")
            return False
        except tp.ProviderError:
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            tp.requests = orig_requests

    check("C6a：空 rows → ProviderError", _run_with([], "20260924"))
    check("C6a：缺 date → ProviderError", _run_with(_RAW_ROWS, ""))


if __name__ == "__main__":
    test_minute_candles_cumulative_diff()
    test_minute_date_and_shape()
    test_minute_via_provider_chain()
    test_minute_unsupported_type_rejected()
    test_minute_otc_fund_empty_raises()
    test_minute_empty_raises()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
