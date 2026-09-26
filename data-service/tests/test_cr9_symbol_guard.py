"""CR9-1 离线单测：腾讯备源的"标的身份"守卫（场外基金不得串成同码品种）。

背景（2026-09-26 实测）：`_symbol()` 只按数字前缀猜交易所，而 `_symbol_for()` 此前
对 `fund` 没有收窄——同一 6 位数字在两个空间指代两个品种：
    000001 = 华夏成长混合（净值 1.295）  ↔ sz000001 = 平安银行
    110022 = 易方达消费行业（净值 2.78） ↔ sh110022 = 交易所品种（140+ 元级序列）
东财/天天基金冷却时主源失败 → chain_call 降级到腾讯 → **别家品种的价格序列被当成该
基金交付**，并被标成"已降级但成功"；web 一取数就 upsert 进 KlineDaily(type,code,date)
形成持久污染（C26 / §C-4 / R16）。修法：`_symbol_for` 对 fund 用 `_is_exchange_traded_fund`
收窄，不匹配即 None → ProviderNotSupported → 上层显式降级。

判据的权威在 `akshare_provider._is_exchange_traded_fund`（与 sina 的 `_etf_symbol` 同集合），
本文件用 `_symbol()` 的旧行为作"不分派就会串号"的对照断言（与 test_g6_hk 同套路）。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr9_symbol_guard.py
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


import app.providers.tencent_provider as tp  # noqa: E402
from app.providers import get_provider_chain  # noqa: E402
from app.providers.akshare_provider import _is_exchange_traded_fund  # noqa: E402
from app.providers.chain import chain_call  # noqa: E402
from app.providers.base import ProviderError, ProviderNotSupported  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# ---------- mock：腾讯行情响应（字段位与 _fields_to_quote 对齐） ----------

def _tencent_line(sym: str) -> str:
    f = [""] * 40
    f[1] = "测试标的"
    f[3] = "3.21"
    f[4] = "3.20"
    f[5] = "3.20"
    f[6] = "1234"
    f[30] = "2026-09-25 15:00:00"
    f[31] = "0.01"
    f[32] = "0.31"
    f[33] = "3.22"
    f[34] = "3.19"
    return f'v_{sym}="{"~".join(f)}"'


def _install_fake_tencent_http(symbols: tuple[str, ...]) -> dict:
    """替换 tp.requests，记录调用次数；只对被请求的 symbol 返回数据。"""
    calls: dict = {"n": 0, "urls": []}
    payload = ";".join(_tencent_line(s) for s in symbols).encode("gbk")

    class _Resp:
        status_code = 200
        content = payload

        def raise_for_status(self) -> None:
            return None

    def _get(url, params=None, **kw):
        calls["n"] += 1
        calls["urls"].append(str(url))
        return _Resp()

    tp.requests = types.SimpleNamespace(get=_get)
    return calls


def _restore_tencent_http() -> None:
    import requests as real_requests

    tp.requests = real_requests


# ---------- A. 单元：按类型收窄 ----------

def test_symbol_for_narrowing() -> None:
    # 场外基金：必须拒（这两个码恰好与深市股票/沪市交易所品种同号）
    check("CR9-1：fund 000001（场外）→ None", tp._symbol_for("fund", "000001") is None,
          str(tp._symbol_for("fund", "000001")))
    check("CR9-1：fund 110022（场外）→ None", tp._symbol_for("fund", "110022") is None,
          str(tp._symbol_for("fund", "110022")))
    check("CR9-1：fund 123456（非场内前缀）→ None", tp._symbol_for("fund", "123456") is None,
          str(tp._symbol_for("fund", "123456")))
    # 场内 ETF/LOF：放行（守卫不得把备源能力打死）
    check("CR9-1：fund 159915（场内 ETF）→ sz159915",
          tp._symbol_for("fund", "159915") == "sz159915", str(tp._symbol_for("fund", "159915")))
    check("CR9-1：fund 510300（场内 ETF）→ sh510300",
          tp._symbol_for("fund", "510300") == "sh510300", str(tp._symbol_for("fund", "510300")))
    # 其它类型零改动
    check("CR9-1：stock 000001 不受影响 → sz000001",
          tp._symbol_for("stock", "000001") == "sz000001", str(tp._symbol_for("stock", "000001")))
    check("CR9-1：stock 600519 不受影响 → sh600519",
          tp._symbol_for("stock", "600519") == "sh600519", str(tp._symbol_for("stock", "600519")))
    check("CR9-1：hk 00700 不受影响 → hk00700",
          tp._symbol_for("hk", "00700") == "hk00700", str(tp._symbol_for("hk", "00700")))
    # 对照：证明"不按类型分派就会串号"——_symbol 本身仍会把场外基金码映射成交易所码
    check("对照：_symbol 对 000001 仍映射 sz000001（守卫确实在 _symbol_for 层）",
          tp._symbol("000001") == "sz000001", str(tp._symbol("000001")))
    check("对照：_symbol 对 110022 仍映射 sh110022",
          tp._symbol("110022") == "sh110022", str(tp._symbol("110022")))
    # 判据单一来源：守卫用的就是 akshare 侧的场内权威集合，不得另起一套
    check("CR9-1：判据与 _is_exchange_traded_fund 一致（000001 场外 / 159915 场内）",
          (not _is_exchange_traded_fund("000001")) and _is_exchange_traded_fund("159915"))


# ---------- B. provider 端到端：被拒时不得发出任何 HTTP 请求 ----------

def _expect_not_supported(fn, label: str) -> None:
    try:
        fn()
        check(label, False, "未抛异常")
    except ProviderNotSupported:
        check(label + "（ProviderNotSupported）", True)
    except Exception as e:  # noqa: BLE001
        check(label, False, f"异常类型错误: {type(e).__name__}: {e}")


def test_provider_rejects_without_http() -> None:
    calls = _install_fake_tencent_http(("sz000001", "sh110022"))
    try:
        _expect_not_supported(lambda: tp._provider.get_quote("fund", "000001"),
                             "CR9-1：get_quote fund 000001 被拒")
        _expect_not_supported(lambda: tp._provider.get_kline("fund", "110022", interval="1d"),
                             "CR9-1：get_kline fund 110022(1d) 被拒")
        _expect_not_supported(lambda: tp._provider.get_kline("fund", "000001", interval="1m"),
                             "CR9-1：get_kline fund 000001(1m) 被拒（C6a 路径同样收口）")
        check("CR9-1：批量 get_quotes 场外基金 → {} 且不请求",
              tp._provider.get_quotes("fund", ["000001", "110022"]) == {}, "")
        check("CR9-1：以上四条**零次**腾讯 HTTP 请求（没机会拿到同码品种数据）",
              calls["n"] == 0, f"实际 {calls['n']} 次: {calls['urls']}")
    finally:
        _restore_tencent_http()


# ---------- C. 主备链：场外必须失败，场内仍可降级 ----------

def _with_primary_down(body):
    """把 akshare 与 sina 两个 fund 源钉成失败，只留腾讯在链上。"""
    import app.providers.akshare_provider as ak
    import app.providers.sina_provider as sp

    orig_ak = ak.AkshareProvider.get_quote
    orig_sp = sp.SinaProvider.get_quote
    ak.AkshareProvider.get_quote = lambda self, type_, code: (_ for _ in ()).throw(
        ProviderError("fund nav table cooling down (simulated)")
    )
    sp.SinaProvider.get_quote = lambda self, type_, code: (_ for _ in ()).throw(
        ProviderNotSupported("sina 不提供该码（simulated）")
    )
    try:
        body()
    finally:
        ak.AkshareProvider.get_quote = orig_ak
        sp.SinaProvider.get_quote = orig_sp


def test_chain_behaviour() -> None:
    chain = get_provider_chain("fund")
    check("CR9-1：fund 备源链完好（akshare 主 + 腾讯/新浪备，共 3 家）", len(chain) == 3,
          str([p.source for p in chain]))

    calls = _install_fake_tencent_http(("sz159915",))
    try:
        # ① 场外：全链失败 → 抛 ProviderError，绝不返回腾讯的同码序列
        def _otc():
            try:
                r = chain_call("fund", lambda p: p.get_quote("fund", "000001"))
                check("CR9-1：场外基金主源失败时链上不得返回任何数据", False,
                      f"竟返回了 source={r.get('source')} price={r.get('price')}")
            except ProviderError as e:
                check("CR9-1：场外基金主源失败 → 显式 ProviderError（不冒领）", True, str(e))
        _with_primary_down(_otc)
        check("CR9-1：场外路径未向腾讯发请求", calls["n"] == 0, f"实际 {calls['n']} 次")

        # ② 场内 ETF：主源失败 → 仍可降级到腾讯（守卫没误杀备源能力）
        def _etf():
            r = chain_call("fund", lambda p: p.get_quote("fund", "159915"))
            check("CR9-1：场内 ETF 主源失败 → 降级至 tencent", r.get("source") == "tencent",
                  str(r.get("source")))
            check("CR9-1：降级时 note 如实标注（R16）",
                  "已降级至 tencent" in str(r.get("note") or ""), str(r.get("note")))
        _with_primary_down(_etf)
    finally:
        _restore_tencent_http()


def main() -> int:
    test_symbol_for_narrowing()
    test_provider_rejects_without_http()
    test_chain_behaviour()
    passed = sum(1 for _n, ok, _d in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"[FAIL] {name}  <- {detail}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
