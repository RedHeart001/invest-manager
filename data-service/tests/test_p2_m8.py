"""R15/M8 离线单测：源族限速器、主备链降级、备源解析。

运行方式（无需服务在跑）：
    .venv/Scripts/python tests/test_p2_m8.py
"""

import os
import sys
import time

# 脚本从 tests/ 启动时，把项目根加入 import 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.providers.base import (
    BaseProvider,
    ProviderError,
    get_provider_chain,
    register,
    register_chain,
)
from app.providers.akshare_provider import _sina_symbol_exchange
from app.providers.sina_provider import _etf_symbol
from app.providers.tencent_provider import TencentProvider, _symbol
from app.utils.limiter import FamilyLimiter

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# ---------- 限速器 ----------


def test_limiter() -> None:
    lim = FamilyLimiter("t1", min_interval=0.3, burst=1, rate_per_min=100)
    check("限速器：首次直接放行", lim.acquire(timeout=1.0) is True)
    t0 = time.monotonic()
    check("限速器：突发用尽后强制最小间隔", lim.acquire(timeout=2.0) is True)
    check("限速器：间隔生效且 ≥0.25s", time.monotonic() - t0 >= 0.25,
          f"waited={time.monotonic() - t0:.3f}")

    lim2 = FamilyLimiter("t2", failure_threshold=2, cooldown_base=60.0)
    lim2.on_failure()
    check("限速器：单次失败不熔断", lim2.in_cooldown() is False)
    lim2.on_failure()
    check("限速器：连续失败 2 次进入冷却", lim2.in_cooldown() is True)
    check("限速器：冷却期 acquire 返回 False（转备源）",
          lim2.acquire(timeout=0.1) is False)
    lim2.on_success()
    check("限速器：成功后冷却解除", lim2.in_cooldown() is False)

    lim3 = FamilyLimiter("t3", min_interval=0.0, burst=100, rate_per_min=3)
    for _ in range(3):
        lim3.acquire(timeout=1.0)
    check("限速器：每分钟上限超限不硬等", lim3.acquire(timeout=0.3) is False)


# ---------- 符号映射 ----------


def test_symbol_mapping() -> None:
    check("腾讯符号：600519→sh", _symbol("600519") == "sh600519")
    check("腾讯符号：159915→sz", _symbol("159915") == "sz159915")
    check("腾讯符号：113710→sh（沪转债）", _symbol("113710") == "sh113710")
    check("腾讯符号：123285→sz（深转债）", _symbol("123285") == "sz123285")
    check("腾讯符号：920001→bj", _symbol("920001") == "bj920001")
    check("新浪符号：159915→sz", _etf_symbol("159915") == "sz159915")
    check("新浪符号：510300→sh", _etf_symbol("510300") == "sh510300")
    check("新浪符号：场外基金不支持", _etf_symbol("110022") is None)
    # CR-17：新浪转债 symbol → 交易所显式解析（不依赖数字前缀推断）
    check("CR-17：sh113050→SH", _sina_symbol_exchange("sh113050") == "SH")
    check("CR-17：sz123285→SZ", _sina_symbol_exchange("sz123285") == "SZ")
    check("CR-17：未知前缀→空", _sina_symbol_exchange("xx000000") == "")


# ---------- 主备链 ----------


class _FailingProvider(BaseProvider):
    source = "failp"

    def get_quote(self, type_: str, code: str) -> dict:
        raise ProviderError("boom")

    def get_kline(self, type_, code, start=None, end=None, interval="1d") -> dict:
        raise ProviderError("boom")


class _GoodProvider(BaseProvider):
    source = "goodp"

    def get_quote(self, type_: str, code: str) -> dict:
        return {"source": self.source, "price": 1.0}

    def get_kline(self, type_, code, start=None, end=None, interval="1d") -> dict:
        return {"source": self.source, "candles": [1, 2]}


def test_chain() -> None:
    register(["__chain_a"], _FailingProvider())
    register_chain(["__chain_a"], _GoodProvider(), position=1)
    chain = [p.source for p in get_provider_chain("__chain_a")]
    check("链路顺序：主源在前、备源在后", chain == ["failp", "goodp"], str(chain))

    from app.main import _chain_call

    register(["__chain_b"], _FailingProvider())
    register_chain(["__chain_b"], _GoodProvider(), position=1)
    result = _chain_call("__chain_b", lambda p: p.get_quote("__chain_b", "X"))
    check("链路：主源失败自动降级备源", result.get("source") == "goodp", str(result))
    check("链路：降级响应带 note 标注",
          "已降级至" in str(result.get("note")), str(result.get("note")))

    register(["__chain_c"], _FailingProvider())
    raised = False
    try:
        _chain_call("__chain_c", lambda p: p.get_quote("__chain_c", "X"))
    except ProviderError:
        raised = True
    check("链路：全部失败抛 ProviderError（页面降级说明）", raised)


# ---------- 备源解析（离线 monkeypatch） ----------


def test_tencent_parsers() -> None:
    import app.providers.tencent_provider as tp

    # K 线解析
    class KResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "sz159915": {
                        "qfqday": [
                            ["2026-09-11", "3.323", "3.341", "3.354", "3.280", "19052972"]
                        ]
                    }
                }
            }

    orig = tp.requests.get
    tp.requests.get = lambda *a, **k: KResp()
    try:
        out = TencentProvider().get_kline("fund", "159915", "20260701", "20260912")
    finally:
        tp.requests.get = orig
    c = out["candles"][0]
    check("腾讯 K 线：source/candles 解析正确",
          out["source"] == "tencent" and c["open"] == 3.323 and c["close"] == 3.341
          and c["high"] == 3.354 and c["low"] == 3.280,
          str(c))

    # 行情解析（程序化构造，字段位标 30/31/32/33/34）
    fields = ["51", "创业板ETF易方达", "159915", "3.341", "3.358", "3.323", "19052972", "9905270", "9147702"]
    fields += [str(i) for i in range(20)]
    fields += ["3.341/19052972/6320257883", "20260911150000", "-0.017", "-0.51", "3.354", "3.280"]
    payload = 'v_sz159915="' + "~".join(fields) + '";'

    class QResp:
        content = payload.encode("gbk")

        def raise_for_status(self):
            pass

    tp.requests.get = lambda *a, **k: QResp()
    try:
        q = TencentProvider().get_quote("fund", "159915")
    finally:
        tp.requests.get = orig
    check("腾讯行情：价格/涨跌幅/高低解析正确",
          q["price"] == 3.341 and q["changePct"] == -0.51
          and q["high"] == 3.354 and q["low"] == 3.280,
          str({k: q[k] for k in ("price", "changePct", "high", "low")}))
    check("腾讯行情：时间字段解析", q["timestamp"] == "20260911150000", str(q["timestamp"]))


# ---------- CR5-1：CoinGecko 失败负缓存（修复静默失效的回归防线） ----------


def test_crypto_failure_negative_cache() -> None:
    """CR5-1（2026-09-17 review）：失败路径必须与成功路径对称记账。

    背景：`_markets_fail_ts` 此前只在 __init__ 与**成功**路径置 0，失败路径从不写入，
    导致守卫 `now - fail_ts < CG_FAIL_COOLDOWN` 恒假 → 负缓存是死代码，
    CoinGecko 不可达时每个 crypto 请求仍完整重试约 41s。
    """
    import app.providers.crypto_provider as cp

    provider = cp.CoinGeckoProvider()
    calls = {"n": 0}

    def _boom(path, params):
        calls["n"] += 1
        raise ProviderError("coingecko unreachable (simulated)")

    orig_request = provider._request
    orig_sleep = cp.time.sleep
    orig_time = cp.time.time
    provider._request = _boom
    cp.time.sleep = lambda *_: None  # 避免测试真的 sleep
    try:
        # 第一次：真实尝试并失败
        raised1 = False
        try:
            provider.get_quote("crypto", "BTC")
        except ProviderError:
            raised1 = True
        check("CR5-1：首次失败如实抛错", raised1)
        check("CR5-1：首次失败确实发起了外部请求", calls["n"] == 1, str(calls))

        # 第二次：必须命中负缓存，**不得**再发起外部请求
        raised2 = False
        msg = ""
        try:
            provider.get_quote("crypto", "BTC")
        except ProviderError as e:
            raised2 = True
            msg = str(e)
        check("CR5-1：冷却期内再次调用仍抛降级错误", raised2)
        check("CR5-1：冷却期内不再发起外部请求（负缓存生效）", calls["n"] == 1, str(calls))
        check("CR5-1：降级说明含冷却提示", "cooling down" in msg, msg)

        # 越过冷却窗口后应可恢复重试
        cp.time.time = lambda: 1e12  # 远大于 _markets_fail_ts
        provider._request = lambda path, params: [
            {"symbol": "btc", "name": "Bitcoin", "current_price": 1.0}
        ]
        quote = provider.get_quote("crypto", "BTC")
        check("CR5-1：冷却窗口过后可恢复", quote.get("code") == "BTC", str(quote))
    finally:
        provider._request = orig_request
        cp.time.sleep = orig_sleep
        cp.time.time = orig_time


# ---------- CR6-P1-3：K 线脏行（null OHLC）契约统一 ----------


def test_kline_null_ohlc_filtered() -> None:
    """CR6-P1-3（2026-09-18 review）：akshare/tencent 必须剔除 OHLC 缺失的行。

    KlineDaily.open/high/low/close 为 NOT NULL，单行 null 会让 web 侧整批
    upsert 失败、该标的 K 线持续不可用。以 sina 为契约基准，任一 OHLC
    为 None 即跳过该行（其余行保留）。
    """
    import app.providers.akshare_provider as akp
    import app.providers.tencent_provider as tp

    # --- akshare/eastmoney：一行正常 + 一行 open 为 "-"（→ None）---
    # 格式：日期,开,收,高,低,量,额,...
    good = "2026-09-11,10.0,10.5,10.8,9.9,1000,10500,1.0,5.0,0.5,1.0"
    bad = "2026-09-12,-,10.5,10.8,9.9,1000,10500,1.0,5.0,0.5,1.0"
    orig_em = akp._em_request
    akp._em_request = lambda fn: [good, bad]
    try:
        out = akp.AkshareProvider().get_kline("stock", "600000", "20260911", "20260912")
    finally:
        akp._em_request = orig_em
    dates = [c["date"] for c in out["candles"]]
    check("CR6-P1-3：akshare 剔除 null OHLC 行（保留正常行）",
          dates == ["2026-09-11"], str(dates))

    # --- tencent：一行正常 + 一行 high 为 "-"（非数值）---
    class KResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "sz159915": {
                        "qfqday": [
                            ["2026-09-11", "3.323", "3.341", "3.354", "3.280", "100"],
                            ["2026-09-12", "3.400", "3.410", "-", "3.390", "100"],
                        ]
                    }
                }
            }

    orig_get = tp.requests.get
    tp.requests.get = lambda *a, **k: KResp()
    try:
        tout = tp.TencentProvider().get_kline("fund", "159915", "20260911", "20260912")
    finally:
        tp.requests.get = orig_get
    tdates = [c["date"] for c in tout["candles"]]
    check("CR6-P1-3：tencent 剔除 null OHLC 行（保留正常行）",
          tdates == ["2026-09-11"], str(tdates))


# ---------- CR-19：场外基金净值表单失败负缓存 ----------


def test_fund_nav_failure_negative_cache() -> None:
    """CR-19（本轮 code review）：失败路径必须与成功路径对称记账。

    此前 `_fund_nav_table` 失败时不写任何冷却时间戳 → 限流期每个场外基金请求
    都会整表重拉（60s 看门狗），反复捶打天天基金。修复后失败写 `_fund_nav_fail_ts`，
    冷却期内直接降级不再发起外部请求。
    """
    import app.providers.akshare_provider as akp

    provider = akp.AkshareProvider()
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("nav table blocked (simulated)")

    orig = akp._ak_request
    akp._ak_request = _boom
    try:
        # 第一次：真实尝试并失败
        raised1 = False
        try:
            provider._fund_nav_table()
        except ProviderError:
            raised1 = True
        check("CR-19：净值表首次失败如实抛错", raised1)
        check("CR-19：首次失败确实发起外部请求", calls["n"] == 1, str(calls))

        # 第二次：命中失败冷却，不再发起外部请求
        raised2 = False
        msg = ""
        try:
            provider._fund_nav_table()
        except ProviderError as e:
            raised2 = True
            msg = str(e)
        check("CR-19：冷却期内仍抛降级错误", raised2)
        check("CR-19：冷却期内不再发起外部请求（负缓存生效）", calls["n"] == 1, str(calls))
        check("CR-19：降级说明含冷却提示", "cooling down" in msg, msg)
    finally:
        akp._ak_request = orig


def test_fund_nav_empty_table_and_missing_columns() -> None:
    """C2（CR7-8，2026-09-25）：空表/列缺失必须显式降级，不得"成功但空"。

    此前：① `_fund_nav_table` 拿到空 df 照样写缓存 30min（"成功但空"），
    期间**所有**场外基金静默无净值；② `_fund_nav_quotes` 定位不到净值列时
    `return {}` 无 note 无冷却。修复后两者都抛 ProviderError 进失败窗口。
    """
    import pandas as pd

    import app.providers.akshare_provider as akp

    provider = akp.AkshareProvider()
    # 复位实例缓存（该 provider 实例可能与其它测试共享模块级单例）
    provider._fund_nav = None
    provider._fund_nav_ts = 0.0
    provider._fund_nav_fail_ts = 0.0

    orig = akp._ak_request

    # ① 空 df → 抛 ProviderError 且记失败冷却
    akp._ak_request = lambda *a, **k: pd.DataFrame()
    try:
        raised = False
        try:
            provider._fund_nav_table()
        except ProviderError as e:
            raised = "empty" in str(e)
        check("C2🔁：空表如实抛错（不写成功缓存）", raised)
        check(
            "C2🔁：空表计入失败冷却",
            provider._fund_nav_fail_ts > 0,
            str(provider._fund_nav_fail_ts),
        )
        # 冷却期内再次调用不发外部请求
        calls = {"n": 0}

        def _count(*a, **k):
            calls["n"] += 1
            return pd.DataFrame()

        akp._ak_request = _count
        try:
            provider._fund_nav_table()
            check("C2🔁：空表冷却期内不再请求", False, "未抛错")
        except ProviderError:
            check("C2🔁：空表冷却期内不再请求", calls["n"] == 0, str(calls))
    finally:
        akp._ak_request = orig
        provider._fund_nav = None
        provider._fund_nav_ts = 0.0
        provider._fund_nav_fail_ts = 0.0

    # ② 列缺失（上游改列名）→ _fund_nav_quotes 抛 ProviderError 而非 return {}
    ok_df = pd.DataFrame(
        {
            "基金代码": ["012414"],
            "基金简称": ["测试基金"],
            "2026-09-24-单位净值": [1.2345],
            "日增长率": [0.12],
        }
    )
    provider._fund_nav = ok_df
    provider._fund_nav_ts = time.time() + 10**9  # 缓存命中，跳过外部请求
    try:
        quotes = provider._fund_nav_quotes(["012414"])
        check("C2🔁：列齐全时正常产出", quotes.get("012414", {}).get("price") == 1.2345, str(quotes)[:80])

        bad_df = ok_df.rename(columns={"2026-09-24-单位净值": "单位净值"})  # 去掉日期前缀
        provider._fund_nav = bad_df
        raised = False
        msg = ""
        try:
            provider._fund_nav_quotes(["012414"])
        except ProviderError as e:
            raised = True
            msg = str(e)
        check("C2🔁：净值列缺失 → ProviderError（不再 return {}）", raised, msg[:120])
        check("C2🔁：错误说明含列名诊断", "columns missing" in msg and "日增长率" in msg, msg[:160])
    finally:
        provider._fund_nav = None
        provider._fund_nav_ts = 0.0
        provider._fund_nav_fail_ts = 0.0


def test_abandoned_watchdog_count() -> None:
    """CR-22：超时放弃的看门狗线程应被计数（观测用）。"""
    import time as _t

    from app.utils import timeout as to

    before = to.abandoned_count()
    # 一个必然超时的调用：fn 睡 2s，超时 0.1s
    value, err = to.run_with_timeout(lambda: _t.sleep(2.0) or "done", 0.1, "cr22-slow")
    check("CR-22：超时返回 (None, TimeoutError)", value is None and isinstance(err, TimeoutError))
    check("CR-22：放弃线程计数 +1", to.abandoned_count() == before + 1, str(to.abandoned_count()))
    # 正常完成的调用不计入
    v2, e2 = to.run_with_timeout(lambda: "ok", 1.0, "cr22-fast")
    check("CR-22：正常完成不计入", v2 == "ok" and e2 is None and to.abandoned_count() == before + 1)


def test_abandoned_count_race_narrow_window() -> None:
    """D2（CR7-12，2026-09-25）：窄窗口竞态——超时放弃后线程立刻自然结束。

    此前时序：主线程 join 超时 → 锁外置 box["_abandoned"]=True → 拿锁 +1；
    runner 恰在"置标志前"走到 finally 读标志（无值）→ 不递减 → 计数虚高 +1。
    修复后置标志/递减同锁互斥，且主线程拿锁后二次确认 is_alive()。
    压测 N 次"超时阈值极贴边"的调用（fn 快速完成但 join 更快到期），
    断言计数最终精确回落——修复前此断言会偶发虚高。
    """
    import time as _t

    from app.utils import timeout as to

    before = to.abandoned_count()
    # fn 立即完成，join 用极短超时——制造"主线程判超时 vs 线程实际已完成"的贴边窗口
    for i in range(50):
        to.run_with_timeout(lambda: i, 0.0005, f"race-{i}")
    # 等 runner 们全部走完 finally
    _t.sleep(0.5)
    after = to.abandoned_count()
    check(
        "D2🔁：贴边竞态 50 次后计数精确（无虚增）",
        after == before,
        f"before={before} after={after}（虚增 {after - before}）",
    )


if __name__ == "__main__":
    test_limiter()
    test_symbol_mapping()
    test_chain()
    test_tencent_parsers()
    test_crypto_failure_negative_cache()
    test_kline_null_ohlc_filtered()
    test_fund_nav_failure_negative_cache()
    test_fund_nav_empty_table_and_missing_columns()
    test_abandoned_watchdog_count()
    test_abandoned_count_race_narrow_window()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
