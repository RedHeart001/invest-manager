"""CR10-28：腾讯 provider 边界的网络/HTTP/非法 JSON 异常必须归一为 ProviderError。

缺陷形状（11-12 静态确定、本套件取证）：三处 I/O 出口裸抛 requests 原始异常，而
`chain_call` 只捕 `(ProviderError, ProviderNotSupported)`（chain.py:28）⇒ 原始异常越过
降级面。`fund`/`us` 链上腾讯后面还有 sina ⇒ 那一源被整个吃掉；`stock`/`hk` 腾讯是末源
⇒ 端点直接崩而不是降级。

成对形状（C34）：
- 正向＝三类失败都变成 ProviderError 且原因（类型名＋原话＋__cause__）留着；
- 🔁 反向＝摘掉任一处归一，对应那几枚必红；
- 🔁 会红的样本＝**不许宽抓 Exception**：调用方与桩用 AssertionError 表达"不该发请求"，
  宽抓会把编程错误伪装成上游失败（规格明令不许，本套件末尾那三枚就是它的尺）；
- 边界＝成功响应与字段映射一字不变、既有空载荷文案不变、ProviderNotSupported 不被吞。

零出网：上游请求全换替身；不碰真库、不起线程、不动 backups/。
运行：PYTHONPATH=. .venv/Scripts/python tests/test_cr10_28_tencent_error_normalization.py
"""

import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含中文/🔁，Windows GBK 控制台会 UnicodeEncodeError；自带 UTF-8 输出。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402  真模块，但只用它的异常类，一发请求都不出

from app.providers import chain as chain_mod  # noqa: E402
from app.providers import tencent_provider as tp  # noqa: E402
from app.providers.base import (  # noqa: E402
    ProviderError,
    ProviderNotSupported,
    get_provider_chain,
)

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: object = "") -> None:
    results.append((name, bool(cond), str(detail)))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if not cond else ""))


# ---------- 替身与失败注入 ----------


class _Resp:
    """只实现被调用的那三件：content / raise_for_status / json。"""

    def __init__(self, content: bytes = b"", payload=None, http_error=None, json_error=None):
        self.content = content
        self._payload = payload
        self._http = http_error
        self._json = json_error

    def raise_for_status(self) -> None:
        if self._http is not None:
            raise self._http

    def json(self):
        if self._json is not None:
            raise self._json
        return self._payload


def _install(resp=None, exc=None):
    """把本模块的 `requests` 名换成只有 get 的替身（与既有套件同形），返回原值供还原。"""

    def _get(url, params=None, **kw):
        if exc is not None:
            raise exc
        return resp

    orig = tp.requests
    tp.requests = types.SimpleNamespace(get=_get)
    return orig


def _call(fn):
    """返回 `(值, 异常)`——两者必须分得开：链降级成功时是有值无异常，
    只回异常的写法会把"已经走到第三源"读成失败（本套件首跑就踩过这枚假红）。"""
    try:
        return fn(), None
    except Exception as e:  # noqa: BLE001 用例要读的就是"抛了什么"
        return None, e


# 失败注入按**协议**分派：现价是 GBK 文本协议（根本不调 r.json()），给它注入 JSON
# 异常是空放——那枚会撞上空载荷文案变成假绿。JSON 两类只对分时/日K 有效。
_NET = lambda: requests.exceptions.ConnectionError("Remote end closed connection without response")  # noqa: E731
_HTTP = lambda: requests.exceptions.HTTPError("502 Server Error: Bad Gateway for url: https://qt.gtimg.cn/q=sh600519")  # noqa: E731
_JSON = lambda: requests.exceptions.JSONDecodeError("Expecting value", "<html>502 Bad Gateway</html>", 0)  # noqa: E731
_JSON_RAW = lambda: json.JSONDecodeError("Expecting value", "<html>502 Bad Gateway</html>", 0)  # noqa: E731

FAILS = {
    "现价": {"网络": _NET, "HTTP": _HTTP},
    "分时": {"网络": _NET, "HTTP": _HTTP, "非法JSON": _JSON, "非法JSON(裸解析)": _JSON_RAW},
    "日K": {"网络": _NET, "HTTP": _HTTP, "非法JSON": _JSON, "非法JSON(裸解析)": _JSON_RAW},
}

PATHS = {
    "现价": lambda: tp._provider.get_quote("stock", "600519"),
    "分时": lambda: tp._provider.get_kline("stock", "600519", interval="1m"),
    "日K": lambda: tp._provider.get_kline("stock", "600519", interval="1d"),
}


def _resp_for(kind: str, exc):
    if kind == "HTTP":
        return _Resp(http_error=exc)
    if kind.startswith("非法JSON"):
        return _Resp(json_error=exc)
    return None  # 网络：get 本身就抛


# ---------- ① 三类失败 × 三条路径：归一＋保留原因 ----------


def test_normalization() -> None:
    for label, fn in PATHS.items():
        for kind, factory in FAILS[label].items():
            exc = factory()
            orig = _install(resp=_resp_for(kind, exc), exc=exc if kind == "网络" else None)
            try:
                _, got = _call(fn)
            finally:
                tp.requests = orig
            check(
                f"①{label}／{kind} → ProviderError（原始异常不许越过降级面）",
                type(got) is ProviderError,
                f"{type(got).__name__}: {got}",
            )
            check(
                f"①{label}／{kind} 原因留着（__cause__ 是原异常＋消息带类型名与原话）",
                got is not None
                and got.__cause__ is exc
                and type(exc).__name__ in str(got)
                and str(exc)[:24] in str(got),
                f"cause={type(got.__cause__).__name__ if got is not None else None} msg={got}",
            )


def test_module_level_entries() -> None:
    """实时区（realtime.py:237/267）直接点这两个模块级函数，不经 provider 类 ⇒ 同样要归一。"""
    for label, fn in (
        ("fetch_quote_fields", lambda: tp.fetch_quote_fields(["sh600519"])),
        ("fetch_minute_payload", lambda: tp.fetch_minute_payload("sh600519")),
    ):
        exc = _NET()
        orig = _install(exc=exc)
        try:
            _, got = _call(fn)
        finally:
            tp.requests = orig
        check(f"②模块级 {label}／网络 → ProviderError 且原因留着",
              type(got) is ProviderError and got.__cause__ is exc, f"{type(got).__name__}: {got}")


# ---------- ③ 链上后果：下一源必须被尝试；全失败仍抛 ProviderError ----------


class _StubProvider:
    def __init__(self, source: str, result=None, error=None):
        self.source = source
        self._result = result
        self._error = error

    def get_kline(self, type_: str, code: str, start=None, end=None, interval: str = "1d") -> dict:
        if self._error is not None:
            raise self._error
        return dict(self._result)


def test_chain_fallthrough() -> None:
    """链上后果走**日K**（JSON 协议）⇒ 网络/HTTP/非法JSON 三类都真的被行使。"""
    real_chain = chain_mod.get_provider_chain
    fn = lambda p: p.get_kline("stock", "600519", interval="1d")  # noqa: E731
    for kind, factory in FAILS["日K"].items():
        exc = factory()
        third = _StubProvider("sina", result={"source": "sina", "interval": "1d", "candles": []})
        providers = [
            _StubProvider("primary", error=ProviderError("primary down")),
            tp._provider,
            third,
        ]
        chain_mod.get_provider_chain = lambda _t: providers
        orig = _install(resp=_resp_for(kind, exc), exc=exc if kind == "网络" else None)
        try:
            val, got = _call(lambda: chain_mod.chain_call("stock", fn))
        finally:
            tp.requests = orig
            chain_mod.get_provider_chain = real_chain
        ok = got is None and isinstance(val, dict) and val.get("source") == "sina"
        check(f"③腾讯/{kind} 失败 ⇒ 链继续走到第三源（不是把整链带崩）", ok,
              f"{type(got).__name__}: {got}" if got is not None else str(val))
        check(f"③腾讯/{kind} 降级说明写进 note", ok and "已降级至 sina" in (val.get("note") or ""),
              str(val.get("note") if ok else got))

    # 全部失败：仍抛 ProviderError，且三家原因都在（不许静默返回空）
    exc = _NET()
    providers = [
        _StubProvider("primary", error=ProviderError("primary down")),
        tp._provider,
        _StubProvider("sina", error=ProviderError("sina down")),
    ]
    chain_mod.get_provider_chain = lambda _t: providers
    orig = _install(exc=exc)
    try:
        _, got = _call(lambda: chain_mod.chain_call("stock", fn))
    finally:
        tp.requests = orig
        chain_mod.get_provider_chain = real_chain
    check("③三家全失败 ⇒ ProviderError（不是原始异常）", type(got) is ProviderError,
          f"{type(got).__name__}: {got}")
    check("③全失败的消息里三家都在案",
          got is not None and all(s in str(got) for s in ("all sources failed", "primary", "tencent", "sina")),
          str(got))


def test_real_chain_shape() -> None:
    """前提取证：腾讯在 fund/us 链上**不是末源** ⇒ 逃逸真的会吃掉下一源（不是假想危害）。"""
    for t in ("fund", "us"):
        srcs = [p.source for p in get_provider_chain(t)]
        check(f"④真链 {t}：腾讯后面还有源", "tencent" in srcs and srcs.index("tencent") < len(srcs) - 1, srcs)


# ---------- ⑤ 成功响应与字段映射一字不变 ----------


def _quote_fields(price: float = 1250.0, prev: float = 1240.0, ts: str = "20261113093100") -> list[str]:
    f = [""] * 40
    f[1], f[2], f[3], f[4], f[5], f[6] = "贵州茅台", "600519", str(price), str(prev), str(prev), "18300"
    f[30], f[31], f[32], f[33], f[34] = ts, str(price - prev), f"{(price - prev) / prev * 100:.2f}", "1260.0", "1240.0"
    return f


KROWS = [
    ["2026-11-11", "10.00", "10.50", "10.80", "9.90", "1000"],
    ["2026-11-12", "10.50", "10.20", "10.60", "10.10", "1200"],
]
MROWS = [
    "0930 1250.01 183 22875182.71",
    "0931 1251.00 400 50000000.00",
    "0932 1252.50 900 90000000.00",
]


def test_success_unchanged() -> None:
    body = ('v_sh600519="' + "~".join(_quote_fields()) + '";').encode("gbk")
    orig = _install(resp=_Resp(content=body))
    try:
        q = tp._provider.get_quote("stock", "600519")
    finally:
        tp.requests = orig
    check("⑤现价成功：整张映射表逐键不变", q == {
        "type": "stock", "code": "600519", "name": "贵州茅台", "price": 1250.0,
        "prevClose": 1240.0, "open": 1240.0, "volume": 18300.0,
        "timestamp": "2026-11-13T09:31:00", "change": 10.0, "changePct": 0.81,
        "high": 1260.0, "low": 1240.0, "currency": "CNY", "source": "tencent",
    }, q)

    orig = _install(resp=_Resp(payload={"data": {"sh600519": {"qfqday": KROWS}}}))
    try:
        k = tp._provider.get_kline("stock", "600519", start="20261111", end="20261112", interval="1d")
    finally:
        tp.requests = orig
    check("⑤日K成功：根数/来源/interval 不变",
          len(k["candles"]) == 2 and k["source"] == "tencent" and k["interval"] == "1d", k.get("source"))
    check("⑤日K成功：amount 恒 null＋note 原话不变",
          all(c["amount"] is None for c in k["candles"])
          and k["note"] == "备源（腾讯日 K）不提供成交额，amount 恒为 null", k.get("note"))
    check("⑤日K成功：OHLCV 位序不变",
          k["candles"][0] == {"date": "2026-11-11", "open": 10.0, "close": 10.5,
                              "high": 10.8, "low": 9.9, "volume": 1000.0, "amount": None},
          k["candles"][0])

    orig = _install(resp=_Resp(payload={"data": {"sh600519": {"data": {"date": "20261113", "data": MROWS}}}}))
    try:
        m = tp._provider.get_kline("stock", "600519", interval="1m")
    finally:
        tp.requests = orig
    c = m["candles"]
    check("⑤分时成功：累计量仍 diff 成增量（183/217/500）",
          [x["volume"] for x in c] == [183.0, 217.0, 500.0], [x["volume"] for x in c])
    check("⑤分时成功：归属日与 OHLC 同价口径不变",
          c[0]["date"] == "2026-11-13 09:30" and c[1]["open"] == c[1]["close"] == c[1]["high"] == c[1]["low"] == 1251.0,
          c[0])
    check("⑤分时成功：amount 同口径 diff",
          abs(c[1]["amount"] - (50000000.00 - 22875182.71)) < 0.01, c[1]["amount"])


# ---------- ⑥ 既有失败文案与 NotSupported 不被归一吞掉 ----------


def test_existing_messages_intact() -> None:
    cases = [
        ("现价空载荷", lambda: tp._provider.get_quote("stock", "600519"),
         _Resp(content=b""), "tencent quote empty"),
        ("日K空载荷", lambda: tp._provider.get_kline("stock", "600519", interval="1d"),
         _Resp(payload={"data": {}}), "tencent kline empty: 600519"),
        ("分时行", lambda: tp._provider.get_kline("stock", "600519", interval="1m"),
         _Resp(payload={"data": {"sh600519": {"data": {"date": "20261113", "data": []}}}}),
         "tencent minute empty: 600519"),
    ]
    for label, fn, resp, want in cases:
        orig = _install(resp=resp)
        try:
            _, got = _call(fn)
        finally:
            tp.requests = orig
        check(f"⑥{label}：仍是 ProviderError 且文案一字不变",
              type(got) is ProviderError and str(got) == want, f"{type(got).__name__}: {got}")


def test_not_supported_passthrough() -> None:
    """能力拒绝发生在请求之前 ⇒ 既不该发请求，也不该被归一改写成别的类型。"""
    boom = AssertionError("能力拒绝不该发请求")
    for label, fn in (
        ("us 分时", lambda: tp._provider.get_kline("us", "AAPL", interval="1m")),
        ("场外基金日K", lambda: tp._provider.get_kline("fund", "012414", interval="1d")),
    ):
        orig = _install(exc=boom)
        try:
            _, got = _call(fn)
        finally:
            tp.requests = orig
        check(f"⑥{label} → ProviderNotSupported 原样（零请求）",
              type(got) is ProviderNotSupported, f"{type(got).__name__}: {got}")


def test_programming_errors_not_masked() -> None:
    """🔁 窄抓的尺：AssertionError 是编程错误，不许被伪装成上游失败。

    把归一改成 `except Exception` 本组三枚必红——那正是规格禁止的"掩盖编程错误"。
    """
    for label, fn in PATHS.items():
        boom = AssertionError("不该发请求／桩的白名单外域名")
        orig = _install(exc=boom)
        try:
            _, got = _call(fn)
        finally:
            tp.requests = orig
        check(f"⑦🔁 {label}：AssertionError 原样逃逸（不被归一吞掉）",
              got is boom, f"{type(got).__name__}: {got}")


def main() -> None:
    test_normalization()
    test_module_level_entries()
    test_chain_fallthrough()
    test_real_chain_shape()
    test_success_unchanged()
    test_existing_messages_intact()
    test_not_supported_passthrough()
    test_programming_errors_not_masked()

    failed = [r for r in results if not r[1]]
    print(f"===== {len(results) - len(failed)}/{len(results)} 通过 =====")
    if failed:
        for name, _, detail in failed:
            print(f"[FAIL] {name}  <- {detail}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()