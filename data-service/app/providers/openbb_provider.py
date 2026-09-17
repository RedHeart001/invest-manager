"""M6 数据 provider：美股（OpenBB 归位，yfinance 免费档后端起步）。

PLAN M6：OpenBB Platform SDK 体积庞大，按补强思路以 yfinance 免费档作为
`openbb_provider` 的首个后端（vendor 可插拔：后续可换 OpenBB SDK / Alpha
Vantage key 增强），字段映射到与 AkShare 相同的内部 schema。

R12：yfinance 为海外源——优先尝试环境代理（本地代理优先），不可达时抛
ProviderError 由上层降级并标注来源。

代理实现（CR4 / 2026-09-15 review 修复）：经 `_overseas_session()`（trust_env=False +
显式 proxies）注入 `yf.Ticker(code, session=...)`——main.py 默认 NO_PROXY=*，
否则 yfinance 的默认会话会绕过一切环境代理，dev 下美股恒降级（与 crypto_provider
对齐）。yfinance ≥1.7 的 Ticker 构造器原生支持 session 参数。
"""

from __future__ import annotations

import logging
import os

import requests

from ..utils.num import to_float
from .base import (
    BaseProvider,
    ProviderError,
    ProviderNotSupported,
    register_chain,
)

log = logging.getLogger("openbb")

REQ_TIMEOUT = 25


def _proxies() -> dict | None:
    """R12：显式环境代理优先（与 crypto_provider 同策略）。

    注意：main.py 默认 NO_PROXY=*（保护国内源直连），requests 的 select_proxy
    会因此绕过一切 env 代理——所以海外请求必须走 trust_env=False 的独立 Session
    并显式设置 proxies（CR4 / 2026-09-15 review 修复：此前 docstring 宣称代理优先
    但代码从未传递，dev 下美股恒降级）。
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
        px = _proxies()
        if px:
            _session.proxies = px
    return _session


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

    def _ticker(self, code: str):
        """CR4：构造带显式代理会话的 Ticker（见模块 docstring）。"""
        return self._yf().Ticker(code, session=_overseas_session())

    # ---------- 实时行情 ----------

    def get_quote(self, type_: str, code: str) -> dict:
        if type_ != "us":
            raise ProviderNotSupported(f"openbb provider serves US market only, got {type_}")
        t = self._ticker(code)
        try:
            fi = t.fast_info
            # 2026-09-13 code review：yfinance 对退市/无行情标的常返回 nan，
            # 直接 float() 会产出非法 JSON（Starlette allow_nan=False → 500）。
            # 统一走 to_float，非有限值一律 None（C4：缺价一律 null）。
            price = to_float(fi["last_price"])
            prev = to_float(fi["previous_close"])
            open_ = to_float(fi.get("open"))
            day_high = to_float(fi.get("day_high"))
            day_low = to_float(fi.get("day_low"))
            currency = str(fi.get("currency") or "USD")
            if price is None:
                raise ProviderError(f"yfinance returned no price for {code}（可能已退市/无行情）")
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001 网络/代码无效
            raise ProviderError(f"yfinance quote failed: {e}") from e
        change = price - prev if prev else None
        return {
            "type": type_,
            "code": code,
            "name": code,  # yfinance fast_info 无名称；详情页用 Product 表名称
            "price": round(price, 4),
            "prevClose": round(prev, 4) if prev is not None else None,
            "open": round(open_, 4) if open_ is not None else None,
            "high": round(day_high, 4) if day_high is not None else None,
            "low": round(day_low, 4) if day_low is not None else None,
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
        t = self._ticker(code)

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
                o, h, low_, c = (
                    to_float(row["Open"]),
                    to_float(row["High"]),
                    to_float(row["Low"]),
                    to_float(row["Close"]),
                )
                if None in (o, h, low_, c):
                    continue  # 非有限值（nan）行丢弃，避免非法 JSON
                vol = to_float(row["Volume"])
                candles.append(
                    {
                        "date": d,
                        "open": round(o, 4),
                        "high": round(h, 4),
                        "low": round(low_, 4),
                        "close": round(c, 4),
                        "volume": int(vol) if vol is not None else None,
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

    def get_news(self, code: str, limit: int = 8) -> list[dict]:
        """美股新闻（yfinance news；Alpha Vantage key 配置后可增强，P5 未配置走免费档）。

        C5 契约（2026-09-13 code review）：统一返回 list[dict]，调用方自取 provider.source。
        """
        try:
            items = self._ticker(code).news or []
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
        # C5 契约统一（2026-09-13 code review）：provider.get_news 一律返回 list[dict]，
        # 调用方（research/adapter）自取 provider.source 作为来源标注。
        return out


# 注册为主源（us 类型：A股 provider 不支持 us，主备链自动落到这里）
_provider = OpenBBProvider()
register_chain(["us"], _provider, position=0)
