"""M6 数据 provider：美股（OpenBB 归位，yfinance 免费档后端起步）。

PLAN M6：OpenBB Platform SDK 体积庞大，按补强思路以 yfinance 免费档作为
`openbb_provider` 的首个后端（vendor 可插拔：后续可换 OpenBB SDK / Alpha
Vantage key 增强），字段映射到与 AkShare 相同的内部 schema。

R12：yfinance 为海外源——优先尝试环境代理（本地代理优先），不可达时抛
ProviderError 由上层降级并标注来源。
"""

from __future__ import annotations

import logging

import requests

from .base import (
    BaseProvider,
    ProviderError,
    ProviderNotSupported,
    register_chain,
)

log = logging.getLogger("openbb")

REQ_TIMEOUT = 25


class OpenBBProvider(BaseProvider):
    """美股 provider（yfinance 后端）。source 标注 yfinance。"""

    source = "yfinance"

    def _yf(self):
        # 延迟导入：未安装时给出明确错误（由上层降级）
        try:
            import yfinance as yf

            return yf
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"yfinance not installed: {e}") from e

    # ---------- 实时行情 ----------

    def get_quote(self, type_: str, code: str) -> dict:
        if type_ != "us":
            raise ProviderNotSupported(f"openbb provider serves US market only, got {type_}")
        yf = self._yf()
        t = yf.Ticker(code)
        try:
            fi = t.fast_info
            price = float(fi["last_price"])
            prev = float(fi["previous_close"])
            open_ = float(fi["open"]) if fi.get("open") is not None else None
            day_high = float(fi["day_high"]) if fi.get("day_high") is not None else None
            day_low = float(fi["day_low"]) if fi.get("day_low") is not None else None
            currency = str(fi.get("currency") or "USD")
        except Exception as e:  # noqa: BLE001 网络/代码无效
            raise ProviderError(f"yfinance quote failed: {e}") from e
        change = price - prev if prev else None
        return {
            "type": type_,
            "code": code,
            "name": code,  # yfinance fast_info 无名称；详情页用 Product 表名称
            "price": round(price, 4),
            "prevClose": round(prev, 4) if prev else None,
            "open": round(open_, 4) if open_ else None,
            "high": round(day_high, 4) if day_high else None,
            "low": round(day_low, 4) if day_low else None,
            "change": round(change, 4) if change is not None else None,
            "changePct": round(change / prev * 100, 2) if change is not None and prev else None,
            "currency": currency,
            "source": self.source,
        }

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for c in codes[:20]:  # yfinance 无批量接口，逐只取（限 20）
            try:
                out[c] = self.get_quote(type_, c)
            except ProviderError:
                continue
        return out

    # ---------- 日 K ----------

    def get_kline(
        self,
        type_: str,
        code: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
    ) -> dict:
        if type_ != "us" or interval != "1d":
            raise ProviderNotSupported("openbb provider serves US daily kline only")
        yf = self._yf()
        t = yf.Ticker(code)

        def iso(ymd: str | None, default: str) -> str:
            if ymd and len(ymd) == 8:
                return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
            return default

        s = iso(start, "2015-01-01")
        e = iso(end, "2099-12-31")
        try:
            df = t.history(start=s, end=e, interval="1d", auto_adjust=True)
        except Exception as ex:  # noqa: BLE001
            raise ProviderError(f"yfinance kline failed: {ex}") from ex
        if df is None or len(df) == 0:
            raise ProviderError(f"yfinance kline empty: {code}")

        candles = []
        for idx, row in df.iterrows():
            d = str(idx)[:10]
            try:
                candles.append(
                    {
                        "date": d,
                        "open": round(float(row["Open"]), 4),
                        "high": round(float(row["High"]), 4),
                        "low": round(float(row["Low"]), 4),
                        "close": round(float(row["Close"]), 4),
                        "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else None,
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        if not candles:
            raise ProviderError(f"yfinance kline unparsable: {code}")
        return {
            "type": type_,
            "code": code,
            "interval": "1d",
            "source": self.source,
            "candles": candles,
        }

    # ---------- 新闻（美股原生 vendor：无 Alpha Vantage key 时用 yfinance news） ----------

    def get_news(self, code: str, limit: int = 8) -> dict:
        """美股新闻（yfinance news；Alpha Vantage key 配置后可增强，P5 未配置走免费档）。"""
        yf = self._yf()
        try:
            items = yf.Ticker(code).news or []
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"yfinance news failed: {e}") from e
        out = []
        for n in items[:limit]:
            content = n.get("content") or n
            title = str(content.get("title", "") or "").strip()
            if not title:
                continue
            out.append(
                {
                    "title": title,
                    "summary": str(content.get("summary", "") or "").strip()[:200],
                    "url": str(
                        (content.get("canonicalUrl") or {}).get("url", "")
                        or content.get("link", "")
                        or ""
                    ),
                    "time": str(content.get("pubDate", "") or content.get("providerPublishTime", "") or ""),
                }
            )
        if not out:
            raise ProviderError("yfinance news empty")
        return {"items": out, "source": "yfinance-news", "degraded": False, "note": None}


# 注册为主源（us 类型：A股 provider 不支持 us，主备链自动落到这里）
_provider = OpenBBProvider()
register_chain(["us"], _provider, position=0)
