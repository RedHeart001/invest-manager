"""新浪备源（R15/M8）：场内基金（ETF/LOF）日 K。

经 akshare `fund_etf_hist_sina`（新浪源，实测 3584 行可用）。
覆盖范围之外（股票/转债/场外基金）抛 ProviderNotSupported，由链路继续。
注意：该源为不复权数据，响应 note 中标注。
"""

import time

from .base import BaseProvider, ProviderError, ProviderNotSupported, register_chain

CACHE_TTL = 6 * 3600  # 全量序列 6 小时，日线数据一天一变


def _etf_symbol(code: str) -> str | None:
    if code.startswith(("15", "16", "18")):
        return f"sz{code}"
    if code.startswith(("50", "51", "52", "53", "56", "58")):
        return f"sh{code}"
    return None


class SinaProvider(BaseProvider):
    source = "sina"

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    def get_quote(self, type_: str, code: str) -> dict:
        raise ProviderNotSupported("sina quote not needed (tencent covers)")

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        raise ProviderNotSupported("sina quotes not needed (tencent covers)")

    def _series(self, symbol: str) -> list[dict]:
        cached = self._cache.get(symbol)
        if cached and time.time() - cached[0] < CACHE_TTL:
            return cached[1]
        import akshare as ak

        try:
            df = ak.fund_etf_hist_sina(symbol=symbol)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"sina etf kline failed: {e}") from e
        if df is None or len(df) == 0:
            raise ProviderError(f"sina etf kline empty: {symbol}")

        candles: list[dict] = []
        for _, r in df.iterrows():
            d = str(r.get("date", ""))[:10]
            close = r.get("close")
            if not d or close is None:
                continue
            try:
                candles.append(
                    {
                        "date": d,
                        "open": float(r.get("open")),
                        "high": float(r.get("high")),
                        "low": float(r.get("low")),
                        "close": float(close),
                        "volume": float(r.get("volume")) if r.get("volume") is not None else None,
                    }
                )
            except (TypeError, ValueError):
                continue
        if not candles:
            raise ProviderError(f"sina etf kline unparsable: {symbol}")
        self._cache[symbol] = (time.time(), candles)
        return candles

    def get_kline(
        self,
        type_: str,
        code: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
    ) -> dict:
        if type_ != "fund" or interval != "1d":
            raise ProviderNotSupported("sina kline only serves fund daily")
        symbol = _etf_symbol(code)
        if symbol is None:
            raise ProviderNotSupported(f"sina unsupported fund code: {code}")

        s = f"{start[:4]}-{start[4:6]}-{start[6:8]}" if start else None
        e = f"{end[:4]}-{end[4:6]}-{end[6:8]}" if end else None
        candles = [
            c
            for c in self._series(symbol)
            if (not s or c["date"] >= s) and (not e or c["date"] <= e)
        ]
        if not candles:
            raise ProviderError(f"sina etf kline empty after filter: {code}")
        return {
            "type": type_,
            "code": code,
            "interval": "1d",
            "source": self.source,
            "note": "备源数据（新浪，不复权）",
            "candles": candles,
        }


register_chain(["fund"], SinaProvider(), position=2)
