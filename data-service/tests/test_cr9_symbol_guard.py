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


def test_error_message_names_subject_when_rate_limited() -> None:
    """CR9-30（2026-09-26）：限速/熔断态下错误文案必须仍点名标的。

    实测两次（今天 16:4x 与 17:5x）把 test_p0 变成红：东财冷却时逐源理由是
    "eastmoney cooling down (rate-limited)"（CR9-26① 之前尾巴上还挂着谎称的
    "; fallback to backup source"）——这句话**与入参无关**，于是 detail 里再没有
    999999，"是环境噪声还是真回归"无法判定。修法在端点边界补主语（type/code），
    本用例把该契约钉住。
    """
    from fastapi import HTTPException

    import app.main as m
    import app.providers.akshare_provider as akp

    orig_acquire = akp.EM_LIMITER.acquire
    akp.EM_LIMITER.acquire = lambda *a, **k: False  # 强制"限速排队失败"
    try:
        try:
            m.quote(type="stock", code="999999")
            check("CR9-30🔁：限速态下仍抛 502", False, "居然成功了")
        except HTTPException as e:
            detail = str(e.detail)
            check("CR9-30🔁：限速态 → 502", e.status_code == 502, str(e.status_code))
            check("CR9-30🔁：detail 点名标的（type/code）", "stock/999999" in detail, detail[:160])
            check("CR9-30🔁：逐源理由原文保留（不吞诊断）", "cooling down" in detail, detail[:160])
            # CR9-26①：限速发生在"哪一源、有没有备源"之外，文案不许替结果下结论
            check(
                "CR9-26①：限速文案不谎称已降级（R16）",
                "fallback" not in detail and "已降级" not in detail,
                detail[:160],
            )
    finally:
        akp.EM_LIMITER.acquire = orig_acquire


# ---------- E. #46（CR9-74）：us 批量要"声明不能"，好让会批量的那家顶上 ----------
#
# 为什么要这一组：`openbb.get_quotes` 逐只取、`codes[:20]` 截断，并且**每只失败都吞掉**——
# 它从不抛异常。`chain_call` 只在异常时换源 ⇒ 腾讯（有真批量口）在批量路径上**永远轮不到**：
# 快照刷新给 100 只 us，最多 20 只有价，剩下 80 只静默为空，而回执 `updated≥0` 看着像跑了。
# 修法是把"我没有批量接口"变成**声明**（`ProviderNotSupported`），不是把上限偷偷调高、
# 也不是让 web 去猜。单只现价路径（`get_quote`）不经过这里，CR9-52 的链序一个字节都没动。
#
# ⚠️ 10-07 #48 乙把 cap 从 20 收到 **1**：CR9-74 当初按"快照刷新一次 100 只"设计 cap，漏了
# **第二个调用方＝分类浏览一页正好 20 只**（`web/lib/browse.ts` 的 `PAGE_SIZE`）——那一档在 cap=20
# 下不抛，于是逐只打 20 发、每只失败都被 `continue` 吞掉、最后交出一个可能为空的 dict 而不报错
# ⇒ 腾讯在浏览路径上仍然轮不到。下面 1) 的"2 只／20 只"两格与 2b) 那一组就是这一档的收据。

def _tencent_us_line(sym: str, ticker: str) -> str:
    f = [""] * 40
    f[1] = "测试美股"
    f[2] = f"{ticker}.OQ"  # 串号守卫读的就是这一格（CR9-1 同族）
    f[3] = "333.36"
    f[4] = "330.00"
    f[5] = "331.00"
    f[6] = "1234"
    f[30] = "2026-10-07 09:30:00"
    f[31] = "3.36"
    f[32] = "1.01"
    return f'v_{sym}="{"~".join(f)}"'


def _install_fake_tencent_us_http(tickers: list[str]) -> dict:
    calls: dict = {"n": 0}
    payload = ";".join(_tencent_us_line("us" + t, t) for t in tickers).encode("gbk")

    class _Resp:
        status_code = 200
        content = payload

        def raise_for_status(self) -> None:
            return None

    def _get(url, params=None, **kw):
        calls["n"] += 1
        return _Resp()

    tp.requests = types.SimpleNamespace(get=_get)
    return calls


def test_us_batch_quotes_declare_inability() -> None:
    import app.providers.openbb_provider as obb

    codes2 = ["A00", "A01"]  # cap=1 之后，"两只"就已经是批量 —— #48 乙的最小那一格
    codes20 = [f"A{i:02d}" for i in range(20)]
    codes21 = codes20 + ["B01"]
    codes2 = codes20[:2]  # 最小批量＝2 只：cap=1 之后"两只"就已经是批量（#48 乙）
    calls: dict = {"n": 0}

    def _fake_get_quote(self, type_, code):
        calls["n"] += 1
        return {"code": code, "price": 1.0, "source": self.source}

    orig_gq = obb.OpenBBProvider.get_quote
    obb.OpenBBProvider.get_quote = _fake_get_quote
    tk = None
    try:
        # 1) 边界成对（#48 乙之后 cap=1）：≥2 只 ⇒ 声明不能；正好 1 只 ⇒ 逐只取一次
        _expect_not_supported(
            lambda: obb._provider.get_quotes("us", codes21),
            "#46：21 只批量 ⇒ 不静默截成 20 条，而是抛 ProviderNotSupported")
        check("#46：抛在循环**之前** ⇒ 一只 yfinance 请求都没发（不是先打 20 只再扔）",
              calls["n"] == 0, f"实际发了 {calls['n']} 次")
        calls["n"] = 0
        _expect_not_supported(
            lambda: obb._provider.get_quotes("us", codes2),
            "#48 乙：**两只**就算批量 ⇒ 也声明不能（cap=1 是能力定义，不是把上限调到 20）")
        check("#48 乙：2 只这一格同样**零次** yfinance 请求",
              calls["n"] == 0, f"实际发了 {calls['n']} 次")
        calls["n"] = 0
        # 分类浏览一页的量＝20 只（`web/lib/browse.ts` 的 PAGE_SIZE）——改 cap 前这一格是 20 发
        _expect_not_supported(
            lambda: obb._provider.get_quotes("us", codes20),
            "#48 乙：一页 20 只 ⇒ 不再逐只打 20 发，交给真会批量的那家")
        check("#48 乙：20 只这一格**零次** yfinance 请求（改 cap 前这里是 20 发，且逐只失败会被吞掉）",
              calls["n"] == 0, f"实际发了 {calls['n']} 次")
        calls["n"] = 0
        got1 = obb._provider.get_quotes("us", ["A00"])
        check("🔁 边界另一侧：正好 1 只不抛、逐只取一次（cap=1 说的是「没有批量口」，不是「拒绝服务」）",
              calls["n"] == 1 and len(got1) == 1, f"calls={calls['n']} got={len(got1)}")
        check("#46：cap 常数写死在断言里（改它＝改契约，得过这一格）",
              obb._QUOTE_BATCH_CAP == 1, str(obb._QUOTE_BATCH_CAP))

        # 2) 链上端到端：批量由腾讯一次供齐
        calls["n"] = 0
        tk = _install_fake_tencent_us_http(codes21)
        res = chain_call("us", lambda p: {"quotes": p.get_quotes("us", codes21)})
        q = res.get("quotes", {})
        check("链按声明换源：21 只批量 ⇒ **21 只都有价**（此前是静默 0～20 只）",
              len(q) == 21 and all(v.get("source") == "tencent" for v in q.values()),
              f"n={len(q)} sources={sorted({v.get('source') for v in q.values()})}")
        check("真批量的形状＝**一次**腾讯 HTTP 请求（不是 21 次逐只）",
              tk["n"] == 1, f"腾讯被打了 {tk['n']} 次")
        check("note 说的是「没有批量接口」而不是「主源挂了」（降级文案要如实指到成因）",
              "no batch quote API" in (res.get("note") or ""), str(res.get("note"))[:200])

        # 2b) 分类浏览那一页的真实形状经链（#48 乙的本体：一页 20 只，改前落进"逐只 20 发"那一支）
        calls["n"] = 0
        tk20 = _install_fake_tencent_us_http(codes20)
        res20 = chain_call("us", lambda p: {"quotes": p.get_quotes("us", codes20)})
        q20 = res20.get("quotes", {})
        check("#48 乙：一页 20 只经链 ⇒ **20 只都有价且全来自腾讯**（改前＝逐只 20 发，或逐只失败被吞成空壳）",
              len(q20) == 20 and all(v.get("source") == "tencent" for v in q20.values()),
              f"n={len(q20)} sources={sorted({v.get('source') for v in q20.values()})}")
        check("#48 乙：这一页只打**一次**腾讯 HTTP（不是 20 次逐只）",
              tk20["n"] == 1, f"腾讯被打了 {tk20['n']} 次")
        check("#48 乙：这一页**零次** yfinance 请求（cap=1 之后浏览路径不再碰 Yahoo）",
              calls["n"] == 0, f"yfinance 发了 {calls['n']} 次")

        # 3) 链序与单只路径不受影响
        check("🔁 us 链序的前两家一个字没动（CR9-52 由 `tencent_minute` 钉着：Yahoo 仍是单只现价主源）"
              "＋#55 乙 追加的第三家＝新浪（只在前两家都不给时才轮到它）",
              [p.source for p in get_provider_chain("us")] == ["yfinance", "tencent", "sina"],
              str([p.source for p in get_provider_chain("us")]))
        calls["n"] = 0
        one = chain_call("us", lambda p: {"quotes": p.get_quotes("us", ["AAPL"])})
        check("🔁 单只批量（1 只）仍由主源供 ⇒ 这条 raise 没有把 us 的现价主源换掉",
              one["quotes"]["AAPL"]["source"] == "yfinance" and calls["n"] == 1,
              str(one)[:200])
    finally:
        obb.OpenBBProvider.get_quote = orig_gq
        _restore_tencent_http()


# ---------- F. #49 乙（CR9-77）：整批皆空要抛，不许把空壳当"这一批成功了" ----------
#
# 为什么要这一组：`_QUOTE_BATCH_CAP` 收到 1 之后，**混排页（`type=all`）里那 1 只 us 仍走 yfinance**
# （1 只不越上面那道批量闸），而循环里每只失败都被 `continue` 吞掉 ⇒ 返回 `{}` ⇒ `chain_call`
# 看到的是"主源成功" ⇒ 会真批量的腾讯轮不到 ⇒ 那一行静默退回快照价。10-07 15:4x 第一枚实样本＝
# ds 日志 `codes=CEG` 前面一行 `Crumb fetch rate-limited (HTTP 429)`，屏上那一行连「美元」后缀都没有
# （后缀来自 `web/lib/browse.ts` 的 `q?.currency`＝实时在场才给值）。
#
# ⚠️ 这组的 🔁 半是**从实钻里长出来的**：原先设想的第三半"2 只里 1 只失败仍只交回有的那只"在这条
# 路径上是**空集**——≥2 只在循环之前就 `ProviderNotSupported` 了。证据是那一格两侧都红、红因里
# `yf=0 腾讯=1`（它实际测的是"换源"，不是"容忍部分失败"）。⇒ 成对的两半＝**全空要抛**／**单只成功不许被换源**。
# 另一条必须钉住的区分＝这里抛的是"这次没拿到"（`ProviderError`），**不是**"这类我不做"
# （`ProviderNotSupported`）——后者是上面 E 段与 `:142` 那条 fund 空 dict 的合法答复，两种空壳
# 在返回体上同形，所以语义得分开。

def _expect_plain_provider_error(fn, label: str) -> None:
    """要求抛 `ProviderError`，且**不能**是子类 `ProviderNotSupported`（那是另一种答复）。"""
    try:
        fn()
        check(label, False, "未抛异常")
    except ProviderNotSupported as e:
        check(label, False, f"抛成了 ProviderNotSupported（把「这次没拿到」写成「这类不做」）: {e}")
    except ProviderError as e:
        check(label + "（ProviderError，非 ProviderNotSupported）", True)
    except Exception as e:  # noqa: BLE001
        check(label, False, f"异常类型错误: {type(e).__name__}: {e}")


def test_us_batch_all_empty_raises() -> None:
    import app.providers.openbb_provider as obb

    calls: dict = {"n": 0}

    def _boom(self, type_, code):
        calls["n"] += 1
        raise ProviderError("yfinance: HTTP 429 (crumb rate-limited)")

    orig_gq = obb.OpenBBProvider.get_quote
    obb.OpenBBProvider.get_quote = _boom
    try:
        # 1) 单元：单码批量而这一只没拿到 ⇒ 抛，不许交回空 dict
        _expect_plain_provider_error(
            lambda: obb._provider.get_quotes("us", ["CEG"]),
            "#49 乙：1 只、整批皆空 ⇒ 抛（此前是静默返回 {}）")
        check("🔁 乙 确实先打了那一发（抛是在循环之后＝真的试过）",
              calls["n"] == 1, f"实际发了 {calls['n']} 次")
        try:
            obb._provider.get_quotes("us", ["CEG"])
            msg = "(没抛)"
        except ProviderError as e:
            msg = str(e)
        check("抛的消息点名数量与「这批没拿到」（降级文案要指得到成因，CR9-30 同族）",
              "got nothing for all 1 code" in msg, msg[:120])

        # 2) 空 codes 维持原样：乙 没把"任何空答复"都扩成抛
        calls["n"] = 0
        empty = obb._provider.get_quotes("us", [])
        check("🔁 空 codes 仍返回 {} 且不抛（那是调用方的事，CR9-74 的形状没被扩写）",
              empty == {} and calls["n"] == 0, f"got={empty} calls={calls['n']}")
    finally:
        obb.OpenBBProvider.get_quote = orig_gq

    # 3) 链上端到端：单码失败 ⇒ 换源到腾讯，且只打一次
    def _boom2(self, type_, code):
        raise ProviderError("yfinance: HTTP 429 (crumb rate-limited)")

    obb.OpenBBProvider.get_quote = _boom2
    tk = _install_fake_tencent_us_http(["CEG"])
    try:
        res = chain_call("us", lambda p: {"quotes": p.get_quotes("us", ["CEG"])})
        q = res.get("quotes", {})
        check("#49 乙：混排页里那 1 只 us 在主源 429 之后**有价**、来源＝备源（此前＝空壳）",
              list(q.keys()) == ["CEG"] and q["CEG"].get("source") == "tencent",
              f"keys={list(q.keys())} sources={sorted({v.get('source') for v in q.values()})}")
        check("#49 乙：换源只打**一次**腾讯 HTTP", tk["n"] == 1, f"腾讯被打了 {tk['n']} 次")
        check("note 说的是「got nothing（这次没拿到）」而不是「没有批量接口」（两种成因不能混成一句）",
              "got nothing" in (res.get("note") or ""), str(res.get("note"))[:200])
    finally:
        obb.OpenBBProvider.get_quote = orig_gq
        _restore_tencent_http()

    # 4) 🔁 单只成功不许被换源（成对的另一半；"部分失败"那一格在 cap=1 下是空集，见上方注释）
    def _ok(self, type_, code):
        return {"code": code, "price": 1.5, "source": self.source, "currency": "USD"}

    obb.OpenBBProvider.get_quote = _ok
    tk2 = _install_fake_tencent_us_http(["GOOD"])
    try:
        res2 = chain_call("us", lambda p: {"quotes": p.get_quotes("us", ["GOOD"])})
        check("🔁 那 1 只成功时仍由主源供、一次腾讯都不该打（乙 没把 us 的现价主源换掉）",
              list(res2.get("quotes", {}).keys()) == ["GOOD"]
              and res2["quotes"]["GOOD"]["source"] == "yfinance"
              and tk2["n"] == 0 and res2.get("note") is None,
              f"sources={sorted({v.get('source') for v in res2.get('quotes', {}).values()})} 腾讯={tk2['n']} 次 note={str(res2.get('note'))[:80]}")
    finally:
        obb.OpenBBProvider.get_quote = orig_gq
        _restore_tencent_http()

    # 5) 🔁 那条既有形状不许被顺手改掉：腾讯对 fund 批量交 {} 且**不请求**（`:142` 同一条的邻侧守卫）
    calls2 = {"n": 0}

    def _counting_get(url, params=None, **kw):
        calls2["n"] += 1
        raise AssertionError("fund 批量不该发请求")

    orig_req = tp.requests
    tp.requests = types.SimpleNamespace(get=_counting_get)
    try:
        got_fund = tp._provider.get_quotes("fund", ["000001", "110022"])
        check("🔁 「这家不做这类」仍答 {}（乙 只把「这次没拿到」变抛；两种空壳必须分开答复）",
              got_fund == {} and calls2["n"] == 0, f"got={got_fund} http={calls2['n']}")
    finally:
        tp.requests = orig_req


# ---------- G. #55 乙（CR9-81）：us 日 K 的第二家＝新浪，挂在链尾 ----------
#
# 为什么要这一组：10-08 主人手测「粘贴美股没数据」的机制＝us 日 K 在链上只有一家会真给数据
# （Yahoo），而腾讯那条 K 线腿对 us 码直接抛 NotSupported（不发请求就拒）⇒ Yahoo 一限流整屏就空。
# 本组证的是**路由**（谁在什么时候被打、note 说不说得出成因），**不证**"新浪真有那只票"——
# 后者是 10-09 00:00 那枚只读探针的产出（一发 10048 行），且只覆盖 1 只（179 只的覆盖率仍未证）。

def test_us_kline_second_source() -> None:
    import app.providers.openbb_provider as obb
    import app.providers.sina_provider as sp

    fake = [
        {"date": "2026-10-06", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0},
        {"date": "2026-10-07", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 20.0},
    ]
    sina_calls: dict = {"n": 0, "symbols": []}

    def _fake_series(self, symbol: str) -> list[dict]:
        sina_calls["n"] += 1
        sina_calls["symbols"].append(symbol)
        return [dict(r) for r in fake]

    orig_us_series = sp.SinaProvider._us_series
    orig_gk = obb.OpenBBProvider.get_kline
    # 整组套一层腾讯假 HTTP：这条腿本该"不发请求就拒"，装上它就把"万一发了"也变成离线计数而不是真出网
    tk = _install_fake_tencent_http(())
    sp.SinaProvider._us_series = _fake_series
    try:
        # 1) 正向（承重的那枚）：Yahoo 挂 ⇒ 链尾的新浪供出 candles
        def _boom(self, type_, code, start=None, end=None, interval="1d"):
            raise ProviderError("yfinance kline failed: HTTP 429 Too Many Requests")

        obb.OpenBBProvider.get_kline = _boom
        res = chain_call("us", lambda p: p.get_kline("us", "CEG", start="2026-09-25", end="2026-10-09"))
        check("#55 乙：Yahoo 挂 ⇒ 链尾新浪供出 candles（10-09 之前这一格是「全链失败」、屏上只剩空态）",
              res.get("source") == "sina" and len(res.get("candles", [])) == 2, str(res)[:160])
        check("#55 乙：这一路只打了新浪一发、腾讯那条腿一次请求都没发",
              sina_calls["n"] == 1 and sina_calls["symbols"] == ["CEG"] and tk["n"] == 0,
              f"sina={sina_calls} 腾讯={tk['n']}")
        note = res.get("note") or ""
        check("#55 乙：note 两头都说得出——自己是不复权／没成交额，以及主源为什么没用",
              "不复权" in note and "amount 恒为 null" in note and "已降级至 sina" in note and "429" in note,
              note[:240])

        # 2) 🔁 成对的另一半：Yahoo 给得出时根本不该走到新浪（乙 没换主源、也没多花一发）
        def _ok(self, type_, code, start=None, end=None, interval="1d"):
            return {"type": type_, "code": code, "interval": "1d",
                    "source": self.source, "candles": [dict(r) for r in fake[:1]]}

        obb.OpenBBProvider.get_kline = _ok
        sina_calls["n"] = 0
        res2 = chain_call("us", lambda p: p.get_kline("us", "AAPL"))
        check("🔁 Yahoo 成功时链走不到新浪（us 日 K 主源仍是它，乙 只是多备一家）",
              res2.get("source") == "yfinance" and sina_calls["n"] == 0 and res2.get("note") is None,
              f"source={res2.get('source')} sina={sina_calls['n']} note={str(res2.get('note'))[:80]}")

        # 3) 三家都不给 ⇒ 仍是一句 all sources failed（#55 甲 那句上屏成因照样归一得出）
        def _boom2(self, type_, code, start=None, end=None, interval="1d"):
            raise ProviderError("yfinance kline failed: ConnectionResetError(10054)")

        obb.OpenBBProvider.get_kline = _boom2
        sp.SinaProvider._us_series = lambda self, symbol: (_ for _ in ()).throw(
            ProviderError(f"sina us kline empty: {symbol}")
        )
        try:
            chain_call("us", lambda p: p.get_kline("us", "CEG"))
            msg, raised = "(没抛)", False
        except ProviderError as e:
            msg, raised = str(e), True
        check("#55 乙：三家都不给时仍抛 all sources failed（web 空态归一的判据就是这串前缀）",
              raised and "all sources failed" in msg, msg[:200])

        # 4) 🔁 fund 那条腿没被 us 分支改写打散
        sp.SinaProvider._us_series = _fake_series
        orig_series = sp.SinaProvider._series
        sp.SinaProvider._series = lambda self, symbol: [dict(r) for r in fake]
        try:
            r3 = sp._provider.get_kline("fund", "159915", start="2026-09-25", end="2026-10-09")
            check("🔁 fund 仍由新浪供、note 仍是原来那句（us 分支没顺手改掉场内那条腿）",
                  r3.get("source") == "sina" and r3.get("note") == "备源数据（新浪，不复权）"
                  and len(r3.get("candles", [])) == 2, str(r3)[:160])
        finally:
            sp.SinaProvider._series = orig_series

        # 5) 窗口两形都要认（本轮实测挖出来的既有坑，不是预防性设计）
        for label, win in (("YYYY-MM-DD", ("2026-09-25", "2026-10-09")),
                           ("YYYYMMDD", ("20260925", "20261009"))):
            r = sp._provider.get_kline("us", "CEG", start=win[0], end=win[1])
            check(f"#55 乙：窗口两形都认 ⇒ {label} 出 2 根（改前 ISO 形被切成 `2026--09-9-`、整段过滤成空）",
                  len(r.get("candles", [])) == 2, f"{label} → {len(r.get('candles', []))} 根")

        # 6) 码清洗：路径是拼进 URL 的（`staticdata/us/{symbol}`），放过非 ASCII／越界就是白送注入面
        check("#55 乙：us 码＝裸 ticker 直送（含 BRK.A 这类带点号的，库内 us 码就有）",
              sp._us_symbol("brk.a") == "BRK.A" and sp._us_symbol(" CEG ") == "CEG",
              f"{sp._us_symbol('brk.a')}/{sp._us_symbol(' CEG ')}")
        check("#55 乙：清洗拒空／拒非 ASCII／拒超长／拒路径分隔符",
              sp._us_symbol("") is None and sp._us_symbol("贵A") is None
              and sp._us_symbol("A" * 11) is None and sp._us_symbol("CEG/../../x") is None,
              f"'' →{sp._us_symbol('')} 贵A →{sp._us_symbol('贵A')} 11字 →{sp._us_symbol('A'*11)}")
        _expect_not_supported(lambda: sp._provider.get_kline("us", "600519"),
                              "#55 乙：A 股码问新浪 us 腿 → 拒（清洗不放过数字码）")
        _expect_not_supported(lambda: sp._provider.get_kline("us", "CEG", interval="1m"),
                              "#55 乙：us 分钟线仍拒（乙 只补日 K，没顺手扩能力）")

        # 7) 一 fetch 整段历史 ⇒ 同一只第二次不许再打上游
        class _DF:
            def __init__(self, rows):
                self._rows = rows

            def __len__(self):
                return len(self._rows)

            def iterrows(self):
                return enumerate(self._rows)

        hits = {"n": 0}
        orig_rwt = sp.run_with_timeout

        def _fake_rwt(fn, timeout, label):
            hits["n"] += 1
            return _DF([dict(r) for r in fake]), None

        sp.run_with_timeout = _fake_rwt
        try:
            sp.SinaProvider._us_series = orig_us_series  # 这一枚要走真缓存逻辑，不能带假实现
            prov = sp.SinaProvider()  # 新实例＝空缓存，免得被同进程别处的读数污染
            prov.get_kline("us", "MSFT", start="2026-09-25", end="2026-10-09")
            r_b = prov.get_kline("us", "MSFT", start="2026-09-25", end="2026-10-09")
            check("#55 乙：同一只第二次走 6 小时缓存、不再打新浪（重复开页面＝零上游）",
                  hits["n"] == 1 and len(r_b.get("candles", [])) == 2,
                  f"看门狗被打了 {hits['n']} 次")
        finally:
            sp.run_with_timeout = orig_rwt
    finally:
        sp.SinaProvider._us_series = orig_us_series
        obb.OpenBBProvider.get_kline = orig_gk
        _restore_tencent_http()


def main() -> int:
    test_symbol_for_narrowing()
    test_provider_rejects_without_http()
    test_chain_behaviour()
    test_error_message_names_subject_when_rate_limited()
    test_us_batch_quotes_declare_inability()
    test_us_batch_all_empty_raises()
    test_us_kline_second_source()
    passed = sum(1 for _n, ok, _d in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"[FAIL] {name}  <- {detail}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
