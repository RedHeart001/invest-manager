"""CoinGecko 数据源适配器：加密货币列表/行情/K线（P1 列表，P2 补齐行情与 K 线）。

免费公开 API，无需 key；按市值取前 250 个币种（避免收录大量同名垃圾币，
symbol 作为 code 在头部币种内基本唯一）。

R12 策略：CoinGecko 属海外源。若设置了 HTTPS_PROXY/HTTP_PROXY 环境变量
则优先经代理访问（用户本地代理可用）；否则直连。不可达时上层降级为
"该类型数据缺失"并标注缺口，不阻塞其余功能。
"""

import os
import time
from datetime import datetime, timezone

import requests

from .base import BaseProvider, ProviderError, register, register_list

CG_BASE = "https://api.coingecko.com/api/v3"
REQUEST_TIMEOUT = 20
MARKETS_TTL_SECONDS = 60
TOP_N = 250
MAX_KLINE_DAYS = 365


def _proxies() -> dict | None:
    """R12：显式环境代理优先（系统注册表代理在 data-service 已被 NO_PROXY=* 屏蔽）。

    注意：main.py 默认 NO_PROXY=*（保护国内源直连），requests 的 select_proxy
    会因此绕过任何显式代理——所以海外请求必须走 trust_env=False 的独立 Session
    （见 _request），由 _proxies() 显式传代理，两套逻辑互不干扰。
    """
    px = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
    return {"http": px, "https": px} if px else None


_session: requests.Session | None = None


def _overseas_session() -> requests.Session:
    """trust_env=False 的独立会话：绕开全局 NO_PROXY=*，显式代理可用。"""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.trust_env = False
    return _session


class CoinGeckoProvider(BaseProvider):
    source = "coingecko"

    def __init__(self):
        self._markets: list[dict] | None = None
        self._markets_ts = 0.0

    def _request(self, path: str, params: dict) -> dict:
        last_err = None
        for _attempt in range(2):
            try:
                r = _overseas_session().get(
                    f"{CG_BASE}{path}",
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                    proxies=_proxies(),
                )
                r.raise_for_status()
                return r.json()
            except Exception as e:  # noqa: BLE001 网络不可达/限流
                last_err = e
                time.sleep(1)
        raise ProviderError(f"coingecko unreachable: {last_err}")

    def _fetch_markets(self) -> list[dict]:
        if self._markets is not None and time.time() - self._markets_ts < MARKETS_TTL_SECONDS:
            return self._markets
        self._markets = self._request(
            "/coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": TOP_N,
                "page": 1,
                "price_change_percentage": "24h",
            },
        )
        self._markets_ts = time.time()
        return self._markets

    def _market_item(self, code: str) -> dict:
        want = code.upper()
        for item in self._fetch_markets():
            if str(item.get("symbol", "")).upper() == want:
                return item
        raise ProviderError(f"crypto code not found: {code}")

    def get_quote(self, type_: str, code: str) -> dict:
        item = self._market_item(code)
        return {
            "type": "crypto",
            "code": str(item.get("symbol", "")).upper(),
            "name": str(item.get("name", "")),
            "price": item.get("current_price"),
            "change": None,
            "changePct": item.get("price_change_percentage_24h"),
            "high": item.get("high_24h"),
            "low": item.get("low_24h"),
            "marketCap": item.get("market_cap"),
            "marketCapRank": item.get("market_cap_rank"),
            "volume": item.get("total_volume"),
            "source": self.source,
        }

    def get_kline(
        self,
        type_: str,
        code: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
    ) -> dict:
        if interval != "1d":
            raise ProviderError("crypto minute kline not supported")
        item = self._market_item(code)
        coin_id = str(item.get("id", "") or "")
        if not coin_id:
            raise ProviderError(f"crypto id missing for {code}")
        # 计算天数窗口（免费档仅支持 days 参数，日线粒度）
        days = MAX_KLINE_DAYS
        if start:
            try:
                s = datetime.strptime(start, "%Y%m%d").replace(tzinfo=timezone.utc)
                e = (
                    datetime.strptime(end, "%Y%m%d").replace(tzinfo=timezone.utc)
                    if end
                    else datetime.now(timezone.utc)
                )
                days = min(MAX_KLINE_DAYS, max(2, (e - s).days + 1))
            except ValueError:
                pass
        payload = self._request(
            f"/coins/{coin_id}/market_chart",
            {"vs_currency": "usd", "days": days, "interval": "daily"},
        )
        prices = payload.get("prices") or []
        candles = []
        for ts_ms, price in prices:
            if price is None:
                continue
            date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            candles.append(
                {
                    "date": date,
                    "open": float(price),
                    "high": float(price),
                    "low": float(price),
                    "close": float(price),
                    "volume": None,
                }
            )
        return {
            "type": "crypto",
            "code": code.upper(),
            "interval": "1d",
            "valueOnly": True,  # 免费档仅收盘价序列，OHLC 同值
            "source": self.source,
            "candles": candles,
        }

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        want = {c.upper() for c in codes}
        out: dict[str, dict] = {}
        for item in self._fetch_markets():
            symbol = str(item.get("symbol", "")).upper()
            if symbol in want:
                out[symbol] = {
                    "type": "crypto",
                    "code": symbol,
                    "name": str(item.get("name", "")),
                    "price": item.get("current_price"),
                    "changePct": item.get("price_change_percentage_24h"),
                    "source": self.source,
                }
        return out

    def list_products(self, type_: str) -> list[dict]:
        products = []
        for item in self._fetch_markets():
            symbol = str(item.get("symbol", "")).upper()
            name = str(item.get("name", ""))
            if not symbol or not name:
                continue
            products.append(
                {
                    "type": "crypto",
                    "code": symbol,
                    "name": name,
                    "pinyin": "",
                    "pinyinInitials": "",
                    "exchange": "crypto",
                    "tags": ["加密货币"],
                }
            )
        return products


_crypto = CoinGeckoProvider()
register(["crypto"], _crypto)  # P2：行情/K线注册（此前仅列表）
register_list(["crypto"], _crypto)
