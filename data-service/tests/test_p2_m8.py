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


if __name__ == "__main__":
    test_limiter()
    test_symbol_mapping()
    test_chain()
    test_tencent_parsers()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
