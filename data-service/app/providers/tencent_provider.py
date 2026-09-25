"""腾讯备源（R15/M8）：覆盖 A股 / 场内基金 / 港股 的实时行情、日 K 与分钟线。

- 行情：`qt.gtimg.cn/q=<sym>`（一次可批量多个，逗号分隔）
- 日 K：`web.ifzq.gtimg.cn/appstock/app/fqkline/get`（前复权 qfq）
- 分钟线：`ifzq.gtimg.cn/appstock/app/minute/query`（当日分时，C6a 2026-09-25；
  **累计量/额必须 diff 成增量**再返回——东财主源口径为每分钟增量）
- 不覆盖：可转债日 K（实测返回空）、场外基金（无）、加密
"""

import os

import requests

from .base import BaseProvider, ProviderError, ProviderNotSupported, register_chain

REQ_TIMEOUT = 15
SYMBOL_MARKETS = {"sh", "sz", "bj"}


def _symbol(code: str) -> str | None:
    """腾讯行情代码：sh/sz/bj + 6 位代码。**仅用于 A股/场内基金**。"""
    if code.startswith(("920", "921")):
        return f"bj{code}"
    if code.startswith(("6", "5", "9", "11")):
        return f"sh{code}"
    if code.startswith(("0", "3", "12", "15", "16", "18")):
        return f"sz{code}"
    return None


def _hk_symbol(code: str) -> str | None:
    """腾讯港股符号：hk + 5 位代码（不足补零）。

    港股代码为 **5 位数字**，与 A股/基金的 6 位不同——**绝不能复用 `_symbol`**：
    其前缀规则会把 `00700` 误判为 `sz00700`、`89988` 误判为 `sh89988`
    （2026-09-20 实测认知，见 PLAN M8）。
    """
    c = code.strip()
    if not c.isdigit() or len(c) > 5:
        return None
    return f"hk{c.zfill(5)}"


def _symbol_for(type_: str, code: str) -> str | None:
    """按**产品类型**显式分派符号映射（港股的 5 位数字与 A股前缀规则冲突）。

    禁止改用"按长度猜类型"的隐式约定（与 CR-17 同类反模式）。
    """
    if type_ == "hk":
        return _hk_symbol(code)
    return _symbol(code)


# B4：_num 下沉到 app/utils/num.py（与 akshare_provider 共用）
from ..utils.num import to_float as _num  # noqa: E402


class TencentProvider(BaseProvider):
    source = "tencent"

    # ---------- 实时行情 ----------

    def _fetch_quotes_raw(self, symbols: list[str]) -> dict[str, list[str]]:
        # NO_PROXY=* 已在 main 侧设置，这里直连国内源
        out: dict[str, list[str]] = {}
        for i in range(0, len(symbols), 60):  # 腾讯单次建议 ≤60 个
            chunk = symbols[i : i + 60]
            r = requests.get(
                "https://qt.gtimg.cn/q=" + ",".join(chunk),
                timeout=REQ_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
            text = r.content.decode("gbk", errors="ignore")
            for line in text.split(";"):
                line = line.strip()
                if not line.startswith("v_"):
                    continue
                head, _, payload = line.partition("=")
                sym = head[2:]
                fields = payload.strip().strip('"').split("~")
                if len(fields) > 34:
                    out[sym] = fields
        if not out:
            raise ProviderError("tencent quote empty")
        return out

    def _fields_to_quote(self, type_: str, code: str, f: list[str]) -> dict:
        # 仅映射位置确定的字段（1 名称、3 现价、4 昨收、5 今开、6 成交量、30 时间、
        # 31 涨跌、32 涨跌幅、33 最高、34 最低）；不确定的扩展字段不映射，避免展示错数据
        return {
            "type": type_,
            "code": code,
            "name": f[1],
            "price": _num(f[3]),
            "prevClose": _num(f[4]),
            "open": _num(f[5]),
            "volume": _num(f[6]),  # 手
            "timestamp": f[30],
            "change": _num(f[31]),
            "changePct": _num(f[32]),
            "high": _num(f[33]),
            "low": _num(f[34]),
            "source": self.source,
        }

    def get_quote(self, type_: str, code: str) -> dict:
        sym = _symbol_for(type_, code)
        if sym is None:
            raise ProviderNotSupported(f"tencent does not support code: {code}")
        raw = self._fetch_quotes_raw([sym])
        f = raw.get(sym)
        if not f:
            raise ProviderError(f"tencent quote missing: {code}")
        return self._fields_to_quote(type_, code, f)

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        syms = [(c, _symbol_for(type_, c)) for c in codes]
        syms = [(c, s) for c, s in syms if s]
        if not syms:
            return {}
        raw = self._fetch_quotes_raw([s for _, s in syms])
        out: dict[str, dict] = {}
        for code, s in syms:
            f = raw.get(s)
            if f:
                out[code] = self._fields_to_quote(type_, code, f)
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
        # C6a（2026-09-25）：分钟线备源——此前分钟线仅东财单源，端点抖动/熔断时
        # 1D 档位必挂（2026-09-25 verify-all p2 inconclusive 的根因）。
        if interval == "1m":
            return self._minute_kline(type_, code)
        if interval != "1d":
            raise ProviderNotSupported(f"tencent kline interval not supported: {interval}")
        sym = _symbol_for(type_, code)
        if sym is None:
            raise ProviderNotSupported(f"tencent does not support code: {code}")

        def iso(ymd: str | None, default: str) -> str:
            if ymd and len(ymd) == 8:
                return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
            return default

        s = iso(start, "2015-01-01")
        e = iso(end, "2099-12-31")
        import datetime as _dt

        try:
            days = min(
                1200,
                max(
                    30,
                    (
                        _dt.date.fromisoformat(e) - _dt.date.fromisoformat(s)
                    ).days
                    + 10,
                ),
            )
        except ValueError:
            days = 400

        r = requests.get(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": f"{sym},day,{s},{e},{days},qfq"},
            timeout=REQ_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        data = ((r.json() or {}).get("data") or {}).get(sym) or {}
        rows = data.get("qfqday") or data.get("day") or []
        candles = []
        for row in rows:
            # 行格式：[日期, 开, 收, 高, 低, 量, ...]
            if len(row) < 6:
                continue
            # CR6-P1-3：与 sina/akshare 对齐，任一 OHLC 缺失即跳过该行——
            # KlineDaily 列为 NOT NULL，null 会让 web 侧整批 upsert 失败。
            o, c, h, low_ = _num(row[1]), _num(row[2]), _num(row[3]), _num(row[4])
            if None in (o, c, h, low_):
                continue
            candles.append(
                {
                    "date": str(row[0]),
                    "open": o,
                    "close": c,
                    "high": h,
                    "low": low_,
                    "volume": _num(row[5]),
                }
            )
        if not candles:
            raise ProviderError(f"tencent kline empty: {code}")
        return {
            "type": type_,
            "code": code,
            "interval": "1d",
            "source": self.source,
            "candles": candles,
        }

    # ---------- 分钟线（C6a，2026-09-25） ----------

    def _minute_kline(self, type_: str, code: str) -> dict:
        """当日 1 分钟分时（C6a 备源）。仅 stock/fund(场内)/bond(转债)/hk——us 走 yfinance 另议。

        接口 `ifzq.gtimg.cn/appstock/app/minute/query`（2026-09-25 实测形态）：
        - `data.<sym>.data.data`：["0930 1250.01 183 22875182.71", ...]（时间 HHMM、价、**累计**量（手）、**累计**额（元））
        - `data.<sym>.data.date`：分时归属日 YYYYMMDD
        - `data.<sym>.qt.<sym>`：行情数组，[1]=名称 [3]=现价 [4]=昨收 [30]=时间

        **口径对齐（关键）**：东财主源 klt=1 的 f56 是**每分钟增量**（实测 sum≈全天总量），
        腾讯是**累计**——必须 diff 成增量再返回，否则 1D 图量柱与主源形态完全不同。
        首行（0930 竞价）原样保留；腾讯 0931 行含竞价外的第一分钟，diff 后总量与东财对账一致。
        分时仅单价 → OHLC 四值同价（与"分时"语义一致，isUsableCandle 可过）。
        """
        sym = _symbol_for(type_, code)
        if sym is None:
            raise ProviderNotSupported(f"tencent does not support code: {code}")

        r = requests.get(
            "https://ifzq.gtimg.cn/appstock/app/minute/query",
            params={"code": sym},
            timeout=REQ_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        payload = ((r.json() or {}).get("data") or {}).get(sym) or {}
        rows = ((payload.get("data") or {}).get("data")) or []
        day = str((payload.get("data") or {}).get("date") or "")
        if not rows or len(day) != 8:
            raise ProviderError(f"tencent minute empty: {code}")

        parsed: list[tuple[str, float, float, float]] = []
        for s in rows:
            parts = s.split()
            if len(parts) < 3:
                continue
            t, price, cum_vol = parts[0], _num(parts[1]), _num(parts[2])
            cum_amt = _num(parts[3]) if len(parts) > 3 else None
            if price is None or cum_vol is None:
                continue
            hhmm = t[:4].zfill(4)
            parsed.append((f"{day[:4]}-{day[4:6]}-{day[6:8]} {hhmm[:2]}:{hhmm[2:]}", price, cum_vol, cum_amt or 0.0))
        if not parsed:
            raise ProviderError(f"tencent minute unparsable: {code}")

        candles = []
        prev_vol = 0.0
        for i, (dt, price, cum_vol, cum_amt) in enumerate(parsed):
            # 累计 → 增量（首行原样；负值 = 上游数据异常，截 0 防御）
            vol = max(cum_vol - prev_vol, 0.0)
            prev_vol = cum_vol
            candles.append(
                {
                    "date": dt,
                    "open": price,
                    "close": price,
                    "high": price,
                    "low": price,
                    "volume": vol,
                    "amount": max(cum_amt - (parsed[i - 1][3] if i > 0 else 0.0), 0.0),
                }
            )
        return {
            "type": type_,
            "code": code,
            "interval": "1m",
            "source": self.source,
            "candles": candles,
        }


_provider = TencentProvider()
# 备源注册：A股 / 场内基金（行情 + 日K）。场内基金由调用方按代码判定，这里统一挂 fund。
register_chain(["stock", "fund"], _provider, position=1)
# G6（2026-09-20）：港股备源（行情 + 日K，符号 hk+5位）。
# 主源为 hk_provider（东财多 host）；腾讯在其全节点不可达/限流时接管。
# 注：港股**列表**无备源（腾讯无全量港股列表接口）→ 显式降级（R10）。
register_chain(["hk"], _provider, position=1)
