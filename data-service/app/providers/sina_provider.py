"""新浪备源（R15/M8）：场内基金（ETF/LOF）与美股（#55 乙）日 K。

经 akshare `fund_etf_hist_sina`（实测 3584 行可用）与 `stock_us_daily`（实测 10048 行可用）。
覆盖范围之外（股票/转债/场外基金）抛 ProviderNotSupported，由链路继续。
注意：两条路都是不复权数据，响应 note 中标注；`stock_us_daily` 返回列只有
date/open/high/low/close/volume，**没有成交额**，所以 us 这份的 `amount` 天然缺席
（与腾讯日 K 同形）。
"""

import time

from ..utils.lru import Lru, env_capacity
from ..utils.num import to_float
from ..utils.timeout import run_with_timeout
from .base import BaseProvider, ProviderError, ProviderNotSupported, register_chain

CACHE_TTL = 6 * 3600  # 全量序列 6 小时，日线数据一天一变

# us 那条一只≈一万行，与 fund 共用 256 上限会把驻留内存顶穿 ⇒ 单独一条小缓存。
US_KLINE_CACHE_MAX = 8


def _etf_symbol(code: str) -> str | None:
    if code.startswith(("15", "16", "18")):
        return f"sz{code}"
    if code.startswith(("50", "51", "52", "53", "56", "58")):
        return f"sh{code}"
    return None


def _us_symbol(code: str) -> str | None:
    """新浪 us 日 K 的路径是 `staticdata/us/{裸 ticker}`，与库内 us 码同形（含 BRK.A 这类点号）。"""
    c = (code or "").strip().upper()
    if not c or len(c) > 10:
        return None
    if not all(("A" <= ch <= "Z") or ch in ".-" for ch in c):
        return None
    return c


def _range_key(ymd: str | None) -> str | None:
    """窗口端点归一成 `YYYY-MM-DD`（与 candles 里的 `date` 同形，比较才成立）。

    `/kline` 的声明是 `YYYYMMDD`，而 web 侧（`web/lib/kline.ts` 的 `iso()`）校验并发出的是
    `YYYY-MM-DD`——**两形都会到 provider 眼前**。腾讯／雅虎各自有 `iso()` 兜住，本文件此前只
    认紧凑一形：ISO 进来会被切成 `2026--09-9-` 这种垃圾串，于是整段过滤成空、报
    「empty after filter」。fund 那条腿要两家都挂了才轮得到它，所以这个形状一直没被踩到；
    us 这条腿恰恰是"Yahoo 挂了才打新浪"＝天天走这条路，一落地就会撞上。
    读不懂的串原样交给下游比较（宁可过滤成空后响亮地抛，也不悄悄把窗口放大＝CR7-2/A2-②）。
    """
    if not ymd:
        return None
    d = ymd.replace("-", "")
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return ymd


def _candles_from(df) -> list[dict]:
    """DataFrame → 统一 candles；任一价字段缺失或非有限值就丢该行（CR4：裸 float() 拦不住 NaN）。"""
    candles: list[dict] = []
    for _, r in df.iterrows():
        d = str(r.get("date", ""))[:10]
        open_ = to_float(r.get("open"))
        high = to_float(r.get("high"))
        low = to_float(r.get("low"))
        close = to_float(r.get("close"))
        volume = to_float(r.get("volume"))
        if not d or close is None or open_ is None or high is None or low is None:
            continue
        candles.append(
            {
                "date": d,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    return candles


class SinaProvider(BaseProvider):
    source = "sina"

    def __init__(self) -> None:
        # CR6-P2-1：原为无界 dict（按 symbol 缓存整段序列，长期运行单调增长）。
        # 上限可经 env 覆盖：SINA_KLINE_CACHE_MAX。
        self._cache: Lru[str, tuple[float, list[dict]]] = Lru(
            env_capacity("SINA_KLINE_CACHE_MAX", 256)
        )
        # #55 乙：us 一只就是上万行，与 fund 共用 256 上限等于把驻留内存交给他浏览 history。
        self._us_cache: Lru[str, tuple[float, list[dict]]] = Lru(
            env_capacity("SINA_US_KLINE_CACHE_MAX", US_KLINE_CACHE_MAX)
        )

    def get_quote(self, type_: str, code: str) -> dict:
        raise ProviderNotSupported("sina quote not needed (tencent covers)")

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        raise ProviderNotSupported("sina quotes not needed (tencent covers)")

    def _series(self, symbol: str) -> list[dict]:
        cached = self._cache.get(symbol)
        if cached and time.time() - cached[0] < CACHE_TTL:
            return cached[1]
        import akshare as ak

        # C7：akshare 内部无 timeout，必须经看门狗（2026-09-13 code review 补漏：
        # 本 provider 此前直调，上游挂死会永久占住 FastAPI 线程池 worker）
        df, err = run_with_timeout(
            lambda: ak.fund_etf_hist_sina(symbol=symbol), 40.0, "ak.fund_etf_hist_sina"
        )
        if err is not None:
            raise ProviderError(f"sina etf kline failed: {err}") from err
        if df is None or len(df) == 0:
            raise ProviderError(f"sina etf kline empty: {symbol}")

        # CR4（2026-09-15 review）：C21 漏网——NaN 进 candles 被缓存 6h → 序列化 500，
        # 逐行清洗住在 `_candles_from`。
        candles = _candles_from(df)
        if not candles:
            raise ProviderError(f"sina etf kline unparsable: {symbol}")
        self._cache[symbol] = (time.time(), candles)
        return candles

    def _us_series(self, symbol: str) -> list[dict]:
        cached = self._us_cache.get(symbol)
        if cached and time.time() - cached[0] < CACHE_TTL:
            return cached[1]
        import akshare as ak

        # C7 同 fund：akshare 内部无 timeout，必须过看门狗。
        # `adjust=""`＝不复权——qfq 档要再打一次复权因子接口，而 akshare 自己的 docstring
        # 就写着 CIEN/AI 的复权因子是错的；宁可给不复权并在 note 里说清。
        df, err = run_with_timeout(
            lambda: ak.stock_us_daily(symbol=symbol, adjust=""), 40.0, "ak.stock_us_daily"
        )
        if err is not None:
            raise ProviderError(f"sina us kline failed: {err}") from err
        if df is None or len(df) == 0:
            raise ProviderError(f"sina us kline empty: {symbol}")
        candles = _candles_from(df)
        if not candles:
            raise ProviderError(f"sina us kline unparsable: {symbol}")
        self._us_cache[symbol] = (time.time(), candles)
        return candles

    def get_kline(
        self,
        type_: str,
        code: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
    ) -> dict:
        if type_ == "fund" and interval == "1d":
            symbol = _etf_symbol(code)
            if symbol is None:
                raise ProviderNotSupported(f"sina unsupported fund code: {code}")
            series = self._series(symbol)
            note = "备源数据（新浪，不复权）"
        elif type_ == "us" and interval == "1d":
            symbol = _us_symbol(code)
            if symbol is None:
                raise ProviderNotSupported(f"sina unsupported us code: {code}")
            series = self._us_series(symbol)
            # 成交额缺席是这份数据的固有形状（腾讯日 K 同形），不是"这一次没拿到"。
            note = "备源数据（新浪美股日线，不复权；不提供成交额，amount 恒为 null）"
        else:
            raise ProviderNotSupported("sina kline only serves fund/us daily")

        s = _range_key(start)
        e = _range_key(end)
        candles = [
            c
            for c in series
            if (not s or c["date"] >= s) and (not e or c["date"] <= e)
        ]
        if not candles:
            raise ProviderError(f"sina {type_} kline empty after filter: {code}")
        return {
            "type": type_,
            "code": code,
            "interval": "1d",
            "source": self.source,
            "note": note,
            "candles": candles,
        }


_provider = SinaProvider()
register_chain(["fund"], _provider, position=2)
# #55 乙（10-09 主人的字＝「#55 乙 落码」）：us 日 K 此前只有 Yahoo 一家会真给数据——
# 链上的腾讯那条腿对 us 码直接抛 NotSupported（`tencent_provider._symbol_for` 不认 us 码），
# 所以 Yahoo 一限流，us 详情页的 K 线区就空。position=2＝排最后：前两家都不给才打新浪，
# 正常态一次上游都不多花。与 fund 共用同一枚实例＝共用那两条 Lru。
register_chain(["us"], _provider, position=2)
