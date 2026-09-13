"""转债实时行情 provider（新浪 cov_spot 全量快照，非东财链路）。

背景（2026-09-13）：
- bond 类型原只有东财主源，无备源；东财 IP 级限流期间转债行情完全不可用
  （搜索结果无法富集行情、详情页无报价）
- 实测确认可用备源：`ak.bond_zh_hs_cov_spot()`（新浪，全量约 320 只沪深转债，
  含真实成交；**非东财域名**，绕开限流）
- 实测确认**不可用**的路径（已排除，勿重复尝试）：
  · `ak.bond_zh_hs_cov_daily`（新浪转债日线）→ 接口返回空（JS 解码后无数据，已废弃）
  · 腾讯 `fqkline`/`kline` → 转债 `day` 恒为空（不覆盖转债 K 线）
  · 腾讯 `qt.gtimg.cn` → 格式兼容但非交易时段恒为面值 100.000/零成交，不可靠
  · 新浪通用 K 线（CN_MarketData.getKLineData）→ 转债返回 null
  · 网易 chddata → 沙箱 502（本机环境待验证，作为候选源记录在 PLAN）

因此本 provider **只提供实时行情（quote/quotes）**，K 线不支持（由链式降级处理）。
另注：**未上市/已退市转债不在 cov_spot 列表内**，取数时给出明确错误（而非静默缺失）。
"""

from __future__ import annotations

import logging
import threading
import time

from ..utils.num import to_float
from ..utils.timeout import run_with_timeout
from .base import BaseProvider, ProviderError, ProviderNotSupported, register_chain

log = logging.getLogger("sina_bond")

CACHE_TTL = 60.0  # 全量快照缓存（320 只一次拉取，避免高频请求）


class SinaBondProvider(BaseProvider):
    """沪深可转债实时行情（新浪 cov_spot 快照）。"""

    source = "sina-bond"

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}
        self._ts = 0.0
        self._lock = threading.Lock()

    # ---------- 快照加载（带缓存与并发去重） ----------

    def _load(self) -> dict[str, dict]:
        now = time.time()
        if self._rows and now - self._ts < CACHE_TTL:
            return self._rows
        with self._lock:
            # 双检：等锁期间其他线程可能已刷新
            if self._rows and time.time() - self._ts < CACHE_TTL:
                return self._rows

            def _fetch():
                import akshare as ak

                df = ak.bond_zh_hs_cov_spot()
                if df is None or len(df) == 0:
                    raise RuntimeError("empty snapshot")
                return df

            df, err = run_with_timeout(_fetch, 45.0, "ak.bond_zh_hs_cov_spot")
            if err is not None:
                # 刷新失败：沿用旧快照（若有），否则向上抛错触发后续降级
                if self._rows:
                    log.warning("bond snapshot refresh failed, reuse stale cache: %s", err)
                    return self._rows
                raise ProviderError(f"新浪转债快照不可用: {type(err).__name__}: {err}") from err

            rows: dict[str, dict] = {}
            for _, r in df.iterrows():
                code = str(r.get("code") or "").strip()
                symbol = str(r.get("symbol") or "").strip()
                if not code and symbol:
                    code = symbol[2:]  # sh113xxx / sz123xxx → 数字代码
                if not code:
                    continue
                price = to_float(r.get("trade"))
                prev = to_float(r.get("settlement"))
                change = None if price is None or prev is None else price - prev
                rows[code] = {
                    "type": "bond",
                    "code": code,
                    "name": str(r.get("name") or "").strip(),
                    "price": price,
                    "prevClose": prev,
                    "open": to_float(r.get("open")),
                    "high": to_float(r.get("high")),
                    "low": to_float(r.get("low")),
                    "change": change,
                    "changePct": to_float(r.get("changepercent")),
                    "volume": to_float(r.get("volume")),
                    "amount": to_float(r.get("amount")),
                    "currency": "CNY",
                    "source": self.source,
                }
            if not rows:
                raise ProviderError("新浪转债快照解析后为空")
            self._rows = rows
            self._ts = time.time()
            return rows

    # ---------- 行情 ----------

    def get_quote(self, type_: str, code: str) -> dict:
        if type_ != "bond":
            raise ProviderNotSupported(f"sina-bond serves bond only, got {type_}")
        rows = self._load()
        q = rows.get(str(code))
        if q is None:
            raise ProviderError(
                f"转债 {code} 不在实时列表（可能未上市 / 已退市 / 非沪深转债）"
            )
        return dict(q)

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        if type_ != "bond":
            raise ProviderNotSupported(f"sina-bond serves bond only, got {type_}")
        rows = self._load()
        return {c: dict(rows[c]) for c in codes if c in rows}

    # ---------- K 线（不支持：见模块 docstring 的排除清单） ----------

    def get_kline(self, *args, **kwargs) -> dict:  # noqa: ANN002, ANN003
        raise ProviderNotSupported(
            "sina-bond 不提供转债 K 线（新浪转债日线接口已废弃、腾讯不覆盖转债）"
        )


_provider = SinaBondProvider()
# 备源位（R15）：bond 主源仍为 akshare（东财），本 provider 在其限流/失败时接管
register_chain(["bond"], _provider, position=1)
