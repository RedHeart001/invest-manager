"""东财数据源适配器：A股 quote/kline/list + 基金/可转债列表。

接口约定见 PLAN.md。quote/kline 直连东财接口并做多 host 镜像降级 +
软失败重试（akshare 的在线接口无重试且软失败，不用于在线服务；仅在
产品列表同步时借用其封装）。东财对短时高频请求有反爬限流，同步类
接口应低频调用。
"""

import logging
import time
from datetime import datetime

import requests
from pypinyin import Style, lazy_pinyin

from .base import (
    BaseProvider,
    ProviderError,
    ProviderNotSupported,
    register,
    register_list,
)
from ..utils.limiter import get_limiter

logger = logging.getLogger("akshare")

# 东财行情 CDN 节点：按序降级尝试
EM_HOSTS = [
    "https://push2.eastmoney.com",
    "https://82.push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
]

# 东财历史 K 线 CDN 节点（akshare 硬编码单一 push2his，镜像来自其源码其他函数）
EM_HIST_HOSTS = [
    "https://push2his.eastmoney.com",
    "https://33.push2his.eastmoney.com",
    "https://63.push2his.eastmoney.com",
]

# 全部 A 股（沪深京）市场过滤，与东财行情首页一致
EM_ALL_A_SHARES = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"

# 单股实时行情字段映射（东财 f 字段 → 统一 schema）
EM_QUOTE_FIELDS = {
    "code": "f57",
    "name": "f58",
    "price": "f43",
    "change": "f169",
    "changePct": "f170",
    "open": "f46",
    "high": "f44",
    "low": "f45",
    "prevClose": "f60",
    "volume": "f47",
    "amount": "f48",
    "ts": "f86",  # unix 秒
    # P2 扩展（详情页身份区/指标卡；场外基金与转债部分字段为 "-"）
    "marketCap": "f116",  # 总市值（元）
    "floatCap": "f117",  # 流通市值（元）
    "peDyn": "f162",  # 市盈率（动）
    "peTtm": "f164",  # 市盈率（TTM）
    "pb": "f167",  # 市净率
    "turnover": "f168",  # 换手率（%）
}

REQUEST_TIMEOUT = 15

# R15/M8：东财为 IP 级滚动窗口限流，全部域名共享一个额度——按"源族"限速
EM_LIMITER = get_limiter(
    "eastmoney",
    min_interval=5.0,
    burst=2,
    rate_per_min=12,
    failure_threshold=2,
    cooldown_base=180.0,
    cooldown_max=900.0,
)


def _em_request(fn):
    """东财按需请求统一入口：限速排队 + 成功/失败回报（连续失败触发熔断）。"""
    if not EM_LIMITER.acquire():
        raise ProviderError(
            "eastmoney cooling down (rate-limited); fallback to backup source"
        )
    try:
        result = fn()
        EM_LIMITER.on_success()
        return result
    except Exception:
        EM_LIMITER.on_failure()
        raise


def _em_ak_request(fn, seconds: float = 30.0, name: str = "akshare"):
    """东财系 akshare 调用：源族限速 + **看门狗超时**。

    akshare 内部 requests 无 timeout，上游挂死会永久占住线程池 worker
    （代码审查修复）。此处统一叠加超时：超时/异常都按失败回报限速器。
    """
    from ..utils.timeout import run_with_timeout

    def _guarded():
        value, err = run_with_timeout(fn, seconds, name)
        if err is not None:
            raise ProviderError(str(err)) from err
        return value

    return _em_request(_guarded)


def _ak_request(fn, seconds: float = 30.0, name: str = "akshare"):
    """非东财域名族的 akshare 调用：仅加看门狗超时（不占东财额度）。"""
    from ..utils.timeout import run_with_timeout

    value, err = run_with_timeout(fn, seconds, name)
    if err is not None:
        raise ProviderError(f"{name} failed: {err}") from err
    return value


# B4：_num 下沉到 app/utils/num.py（与 tencent_provider 共用）
from ..utils.num import to_float as _num  # noqa: E402


def _secid(code: str) -> str:
    """东财 secid：沪市前缀 1，深市/北交所前缀 0。

    覆盖：6xxxxx 沪股、5xxxxx 沪市基金、4/8xxxxx 与 920xxx 北交所、
    0/3xxxxx 深股、15/16/18 深市基金、12xxxx 深市可转债、
    11xxxx 沪市可转债/可交换债（P2 修复：此前误用深市前缀导致无报价）。
    """
    if code.startswith(("920", "921")):  # 北交所新代码段
        return f"0.{code}"
    if code.startswith(("6", "5", "9")):  # 沪市：股票/基金/债/B股
        return f"1.{code}"
    if code.startswith("11"):  # 沪市可转债/可交换债（110~113、118 等）
        return f"1.{code}"
    return f"0.{code}"  # 深市：0/3 股票、12 转债、15/16/18 基金


def _is_exchange_traded_fund(code: str) -> bool:
    """场内基金（ETF/LOF）判断：有实时行情；其余为场外基金（仅每日净值）。"""
    return code.startswith(("15", "16", "18", "50", "51", "52", "53", "56", "58"))


def _exchange(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    if code.startswith(("4", "8", "9")):
        return "BJ"
    return ""


def _pinyin_pair(name: str) -> tuple[str, str]:
    """返回（全拼, 首字母缩写），用于搜索匹配。"""
    return (
        "".join(lazy_pinyin(name)),
        "".join(lazy_pinyin(name, style=Style.FIRST_LETTER)),
    )


def _em_get(path: str, params: dict) -> dict:
    """对东财行情接口做多 host 两轮降级请求，返回 JSON。

    实测东财 CDN 节点对连接存在间歇性丢弃（单次成功率非 100%），
    因此 host 降级 + 轮次重试双保险。

    注意（代码审查修复）：**状态码校验与 JSON 解析必须在传给 `_em_request`
    的闭包内完成**——否则 5xx / 非 JSON 响应也会被登记为成功（on_success），
    清零连续失败计数并解除冷却，熔断形同虚设、持续打东财。
    """
    last_err = None
    for _round in range(2):
        for host in EM_HOSTS:
            try:

                def _fetch(h: str = host) -> dict:
                    r = requests.get(
                        f"{h}{path}",
                        params=params,
                        timeout=REQUEST_TIMEOUT,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    r.raise_for_status()  # 校验放在限速器成功回报之前
                    return r.json()

                return _em_request(_fetch)
            except Exception as e:  # noqa: BLE001 网络/接口抖动，换 host 重试
                last_err = e
    raise ProviderError(f"eastmoney request failed on all hosts: {last_err}")


class AkshareProvider(BaseProvider):
    source = "akshare"

    def __init__(self):
        self._fund_nav = None
        self._fund_nav_ts = 0.0
        self._news_cache: dict[str, tuple[float, list[dict]]] = {}
        self._fund_report_cache: dict[str, tuple[float, dict]] = {}
        self._yield_curve = None
        self._yield_curve_ts = 0.0

    # ---------- 实时行情 ----------

    def get_quote(self, type_: str, code: str) -> dict:
        # 基金/债券复用批量通道（场内走实时行情，场外走每日净值）
        if type_ in ("fund", "bond"):
            quote = self.get_quotes(type_, [code]).get(code)
            if not quote:
                raise ProviderError(f"code not found: {code}")
            return quote

        data = _em_get(
            "/api/qt/stock/get",
            {
                "fltt": 2,
                "invt": 2,
                "fields": ",".join(EM_QUOTE_FIELDS.values()),
                "secid": _secid(code),
            },
        ).get("data")
        if not data:
            raise ProviderError(f"code not found: {code}")
        ts = _num(data.get("f86"))
        return {
            "type": type_,
            "code": str(data.get("f57", code)),
            "name": str(data.get("f58", "")),
            "price": _num(data.get("f43")),
            "change": _num(data.get("f169")),
            "changePct": _num(data.get("f170")),
            "open": _num(data.get("f46")),
            "high": _num(data.get("f44")),
            "low": _num(data.get("f45")),
            "prevClose": _num(data.get("f60")),
            "volume": _num(data.get("f47")),
            "amount": _num(data.get("f48")),
            # P2 扩展字段（仅场内品种有效，其余为 None）
            "marketCap": _num(data.get("f116")),
            "floatCap": _num(data.get("f117")),
            "peDyn": _num(data.get("f162")),
            "peTtm": _num(data.get("f164")),
            "pb": _num(data.get("f167")),
            "turnover": _num(data.get("f168")),
            "timestamp": (
                datetime.fromtimestamp(int(ts)).isoformat(timespec="seconds")
                if ts
                else None
            ),
            "source": self.source,
        }

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        if not codes:
            return {}
        if type_ == "fund":
            # 场内（ETF/LOF）有实时行情；场外仅有每日净值
            exchange = [c for c in codes if _is_exchange_traded_fund(c)]
            otc = [c for c in codes if not _is_exchange_traded_fund(c)]
            out: dict[str, dict] = {}
            if exchange:
                out.update(self._em_ulist("fund", exchange))
            if otc:
                out.update(self._fund_nav_quotes(otc))
            return out
        return self._em_ulist(type_, codes)

    def _em_ulist(self, type_: str, codes: list[str]) -> dict[str, dict]:
        """东财 ulist.np：一次请求批量实时行情（股票/场内基金/可转债通用）。"""
        payload = _em_get(
            "/api/qt/ulist.np/get",
            {
                "fltt": 2,
                "invt": 2,
                "fields": "f12,f14,f2,f3,f4,f15,f16,f17,f18",
                "secids": ",".join(_secid(c) for c in codes),
            },
        )
        diff = ((payload.get("data") or {}).get("diff")) or []
        out: dict[str, dict] = {}
        for item in diff:
            code = str(item.get("f12", ""))
            if not code:
                continue
            out[code] = {
                "type": type_,
                "code": code,
                "name": str(item.get("f14", "")),
                "price": _num(item.get("f2")),
                "changePct": _num(item.get("f3")),
                "change": _num(item.get("f4")),
                "high": _num(item.get("f15")),
                "low": _num(item.get("f16")),
                "open": _num(item.get("f17")),
                "prevClose": _num(item.get("f18")),
                "source": self.source,
            }
        return out

    # ---------- 场外基金净值（单请求全市场 + 内存缓存） ----------

    FUND_NAV_TTL = 1800  # 30 分钟；净值每日更新一次，无需高频拉取

    def _fund_nav_table(self):
        now = time.time()
        if self._fund_nav is not None and now - self._fund_nav_ts < self.FUND_NAV_TTL:
            return self._fund_nav
        import akshare as ak

        try:
            self._fund_nav = _ak_request(ak.fund_open_fund_daily_em, 60.0, "ak.fund_open_fund_daily_em")
            self._fund_nav_ts = now
        except Exception as e:  # noqa: BLE001 接口变动/网络
            raise ProviderError(f"fund nav table failed: {e}") from e
        return self._fund_nav

    def _fund_nav_quotes(self, codes: list[str]) -> dict[str, dict]:
        df = self._fund_nav_table()
        if df is None or len(df) == 0:
            return {}
        # 列名含日期前缀（如 "2026-09-10-单位净值"），按后缀定位
        nav_col = next(
            (c for c in df.columns if str(c).endswith("-单位净值")), None
        )
        if nav_col is None or "日增长率" not in df.columns:
            return {}

        want = set(codes)
        out: dict[str, dict] = {}
        for _, r in df.iterrows():
            code = str(r.get("基金代码", "")).strip()
            if code not in want:
                continue
            out[code] = {
                "type": "fund",
                "code": code,
                "name": str(r.get("基金简称", "")),
                "price": _num(r.get(nav_col)),  # 单位净值
                "changePct": _num(r.get("日增长率")),
                "source": f"{self.source}-fund-nav",
            }
        return out

    # ---------- 历史 K 线 ----------

    def get_kline(
        self,
        type_: str,
        code: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
    ) -> dict:
        """按类型路由的日 K / 分时。

        - 场外基金：无交易所 K 线，返回单位净值历史（valueOnly，P2）
        - interval=1m：东财 1 分钟分时（仅当日，实时数据不落库，供 1D 档位）
        - 其余（股票/场内基金/可转债）：东财日 K 直连（多 host 降级）

        日 K 不走 akshare：其 stock_zh_a_hist 硬编码单一 host、无重试、且在
        data 为空时返回空 DataFrame（软失败）——限流时表现为 200 + 0 根。
        """
        if type_ == "fund" and not _is_exchange_traded_fund(code):
            if interval != "1d":
                raise ProviderNotSupported("场外基金无分钟级数据")
            return self._fund_nav_kline(code, start, end)

        if interval == "1m":
            from datetime import date as _date

            today = _date.today().strftime("%Y%m%d")
            klt, beg, end_p = "1", today, today
        else:
            klt, beg, end_p = "101", start or "20200101", end or "20991231"

        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": klt,
            "fqt": "1",  # 前复权
            "secid": _secid(code),
            "beg": beg,
            "end": end_p,
        }
        klines = None
        last_err = None
        for _round in range(2):
            for host in EM_HIST_HOSTS:
                try:

                    def _fetch_kline(h: str = host) -> list:
                        r = requests.get(
                            f"{h}/api/qt/stock/kline/get",
                            params=params,
                            timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"},
                        )
                        # 状态校验与解析必须在限速器闭包内（否则失败被记为成功）
                        r.raise_for_status()
                        data = (r.json() or {}).get("data") or {}
                        return data.get("klines") or []

                    klines = _em_request(_fetch_kline)
                    if klines:
                        break
                    last_err = f"{host} returned empty klines"
                except Exception as e:  # noqa: BLE001 网络/接口抖动，换 host 重试
                    last_err = e
            if klines:
                break
            time.sleep(1)
        if not klines:
            raise ProviderError(f"eastmoney kline failed on all hosts: {last_err}")

        # kline 字符串格式：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
        candles = []
        for item in klines:
            f = item.split(",")
            candles.append(
                {
                    "date": f[0],
                    "open": _num(f[1]),
                    "close": _num(f[2]),
                    "high": _num(f[3]),
                    "low": _num(f[4]),
                    "volume": _num(f[5]),
                    "amount": _num(f[6]),
                }
            )
        return {
            "type": type_,
            "code": code,
            "interval": interval,
            "source": self.source,
            "candles": candles,
        }

    # ---------- 场外基金净值历史（P2 详情页主图） ----------

    def _fund_nav_kline(
        self, code: str, start: str | None = None, end: str | None = None
    ) -> dict:
        import akshare as ak

        try:
            df = _ak_request(lambda: ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势"), 40.0, "ak.fund_open_fund_info_em")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"fund nav history failed: {e}") from e
        if df is None or len(df) == 0:
            raise ProviderError(f"fund nav history empty: {code}")

        date_col = next((c for c in df.columns if "净值日期" in str(c)), df.columns[0])
        nav_col = next((c for c in df.columns if "单位净值" in str(c)), None)
        if nav_col is None:
            raise ProviderError(
                f"fund nav history unexpected columns: {list(df.columns)}"
            )

        s = f"{start[:4]}-{start[4:6]}-{start[6:8]}" if start else None
        e = f"{end[:4]}-{end[4:6]}-{end[6:8]}" if end else None
        candles = []
        for _, r in df.iterrows():
            d = str(r.get(date_col, ""))[:10]
            nav = _num(r.get(nav_col))
            if not d or nav is None:
                continue
            if s and d < s:
                continue
            if e and d > e:
                continue
            candles.append(
                {
                    "date": d,
                    "open": nav,
                    "high": nav,
                    "low": nav,
                    "close": nav,
                    "volume": None,
                }
            )
        if not candles:
            raise ProviderError(f"fund nav history empty after filter: {code}")
        return {
            "type": "fund",
            "code": code,
            "interval": "1d",
            "valueOnly": True,
            "source": f"{self.source}-fund-nav-hist",
            "candles": candles,
        }

    # ---------- 个股新闻（P2 事件标注，R11 轻量归因数据源） ----------

    NEWS_TTL = 600  # 10 分钟
    NEWS_LIMIT = 30

    def get_news(self, code: str) -> list[dict]:
        import akshare as ak

        cached = self._news_cache.get(code)
        if cached and time.time() - cached[0] < self.NEWS_TTL:
            return cached[1]
        try:
            df = _em_ak_request(lambda: ak.stock_news_em(symbol=code), 30.0, "ak.stock_news_em")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"stock news failed: {e}") from e
        items: list[dict] = []
        for _, r in df.head(self.NEWS_LIMIT).iterrows():
            pub = str(r.get("发布时间", "") or "")
            title = str(r.get("新闻标题", "") or "").strip()
            if not title:
                continue
            items.append(
                {
                    "date": pub[:10],
                    "time": pub,
                    "title": title,
                    "source": str(r.get("文章来源", "") or "").strip(),
                    "url": str(r.get("新闻链接", "") or "").strip(),
                }
            )
        self._news_cache[code] = (time.time(), items)
        return items

    # ---------- 基金重仓持股（P2 明细区：场外基金槽位） ----------

    def get_fund_holdings(self, code: str) -> dict:
        import akshare as ak

        from datetime import date as _date

        last_err = None
        for year in (str(_date.today().year), str(_date.today().year - 1)):
            try:
                df = _ak_request(lambda: ak.fund_portfolio_hold_em(symbol=code, date=year), 40.0, "ak.fund_portfolio_hold_em")
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
            if df is None or len(df) == 0:
                continue
            quarters = list(dict.fromkeys(df["季度"].astype(str)))
            latest = quarters[-1]
            sub = df[df["季度"].astype(str) == latest]
            holdings = []
            for _, r in sub.head(10).iterrows():
                holdings.append(
                    {
                        "code": str(r.get("股票代码", "") or ""),
                        "name": str(r.get("股票名称", "") or ""),
                        "weight": _num(r.get("占净值比例")),
                    }
                )
            if holdings:
                return {
                    "code": code,
                    "quarter": latest,
                    "holdings": holdings,
                    "source": f"{self.source}-fund-holdings",
                }
        raise ProviderError(f"fund holdings failed: {code} ({last_err})")

    # ---------- 基金定期报告（P6 技能 fund-report-analysis 数据源） ----------

    FUND_REPORT_TTL = 21600  # 6 小时（定期报告低频变更）
    PERIODIC_KEYWORDS = ("年度报告", "半年度报告", "季度报告", "中期报告")

    def get_fund_report(self, code: str) -> dict:
        """基金定期报告解读数据：报告清单 + 行业配置。

        spike 结论（2026-09-13）：`fund_announcement_report_em` 返回 100 条
        公告（含季度/半年度/年度报告，按日期升序需倒序取最新）；
        `fund_portfolio_industry_allocation_em` 返回行业类别占比。
        两者均走东财域名 → 经源族限速器。
        """
        import akshare as ak

        from datetime import date as _date

        cached = self._fund_report_cache.get(code)
        if cached and time.time() - cached[0] < self.FUND_REPORT_TTL:
            return cached[1]

        reports: list[dict] = []
        try:
            df = _em_ak_request(lambda: ak.fund_announcement_report_em(symbol=code), 40.0, "ak.fund_announcement_report_em")
            if df is not None and len(df) > 0:
                rows = df.copy()
                rows["_d"] = rows["公告日期"].astype(str)
                rows = rows.sort_values("_d", ascending=False)
                periodic = rows[
                    rows["公告标题"].astype(str).str.contains(
                        "|".join(self.PERIODIC_KEYWORDS), na=False
                    )
                ]
                picked = periodic if len(periodic) > 0 else rows
                for _, r in picked.head(8).iterrows():
                    title = str(r.get("公告标题", "") or "").strip()
                    if not title:
                        continue
                    reports.append(
                        {
                            "title": title,
                            "date": str(r.get("公告日期", "") or "")[:10],
                            "id": str(r.get("报告ID", "") or ""),
                        }
                    )
        except Exception:  # noqa: BLE001 —— 报告清单不可用不阻塞行业配置
            reports = []

        industry: dict | None = None
        last_err = None
        for year in (str(_date.today().year), str(_date.today().year - 1)):
            try:
                df2 = _em_ak_request(
                    lambda y=year: ak.fund_portfolio_industry_allocation_em(
                        symbol=code, date=y
                    ),
                    40.0,
                    "ak.fund_portfolio_industry_allocation_em",
                )
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
            if df2 is None or len(df2) == 0:
                continue
            items = []
            for _, r in df2.iterrows():
                name = str(r.get("行业类别", "") or "").strip()
                weight = _num(r.get("占净值比例"))
                if not name or weight is None:
                    continue
                items.append({"name": name, "weight": weight})
            items.sort(key=lambda x: x["weight"], reverse=True)
            if items:
                industry = {
                    "asOf": str(df2.iloc[0].get("截止时间", "") or "")[:10],
                    "items": items[:10],
                }
                break

        if not reports and industry is None:
            raise ProviderError(
                f"fund report failed: {code} ({last_err or 'no data'})"
            )

        result = {
            "code": code,
            "reports": reports,
            "industry": industry,
            "source": f"{self.source}-fund-report",
        }
        self._fund_report_cache[code] = (time.time(), result)
        return result

    # ---------- 国债收益率曲线（P2 明细区：债券槽位） ----------

    YIELD_TTL = 1800  # 30 分钟
    YIELD_TENORS = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]

    def get_yield_curve(self, days: int = 90) -> dict:
        import akshare as ak

        now = time.time()
        if (
            self._yield_curve is not None
            and now - self._yield_curve_ts < self.YIELD_TTL
        ):
            df = self._yield_curve
        else:
            try:
                df = _ak_request(ak.bond_zh_us_rate, 40.0, "ak.bond_zh_us_rate")
            except Exception as e:  # noqa: BLE001
                raise ProviderError(f"yield curve failed: {e}") from e
            self._yield_curve = df
            self._yield_curve_ts = now

        if df is None or len(df) == 0:
            raise ProviderError("yield curve empty")
        curve = []
        for _, r in df.tail(days).iterrows():
            d = str(r.get("日期", ""))[:10]
            values = {}
            for t in self.YIELD_TENORS:
                v = _num(r.get(t))
                if v is not None:
                    values[t] = v
            if d and values:
                curve.append({"date": d, "values": values})
        if not curve:
            raise ProviderError("yield curve no valid rows")
        return {"source": f"{self.source}-bond-zh-us", "curve": curve}

    # ---------- 产品列表（P1 同步） ----------

    def list_products(self, type_: str) -> list[dict]:
        if type_ == "stock":
            return self._list_stocks()
        if type_ == "fund":
            return self._list_funds()
        if type_ == "bond":
            return self._list_convertible_bonds()
        raise ProviderError(f"unsupported list type: {type_}")

    def _list_stocks(self) -> list[dict]:
        """A 股全量列表：优先单次大分页，未拿全则回退分页抓取。"""
        base_params = {
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f12",
            "fs": EM_ALL_A_SHARES,
            "fields": "f12,f14",
        }
        payload = _em_get(
            "/api/qt/clist/get", {**base_params, "pn": 1, "pz": 10000}
        )
        data = payload.get("data") or {}
        diff = data.get("diff") or []
        total = int(data.get("total") or 0)

        if total and len(diff) < total:
            # 服务端忽略大分页参数 → 分页补齐（低频同步任务，加间隔避免限流）
            page_size = len(diff) or 100
            pages = (total + page_size - 1) // page_size
            collected = {str(x.get("f12")): x for x in diff}
            for pn in range(2, min(pages, 100) + 1):
                time.sleep(0.8)
                page = _em_get(
                    "/api/qt/clist/get",
                    {**base_params, "pn": pn, "pz": page_size},
                )
                for x in ((page.get("data") or {}).get("diff")) or []:
                    collected[str(x.get("f12"))] = x
            diff = list(collected.values())

        products = []
        for item in diff:
            code = str(item.get("f12") or "")
            name = str(item.get("f14") or "")
            if not code or not name:
                continue
            full, initials = _pinyin_pair(name)
            products.append(
                {
                    "type": "stock",
                    "code": code,
                    "name": name,
                    "pinyin": full,
                    "pinyinInitials": initials,
                    "exchange": _exchange(code),
                    "tags": [],
                }
            )
        return products

    def _list_funds(self) -> list[dict]:
        """全量公募基金列表（akshare 封装，单次请求）。"""
        import akshare as ak

        try:
            df = _em_ak_request(ak.fund_name_em, 90.0, "ak.fund_name_em")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"akshare fund list failed: {e}") from e

        products = []
        for _, r in df.iterrows():
            code = str(r.get("基金代码", "")).strip()
            name = str(r.get("基金简称", "")).strip()
            if not code or not name:
                continue
            full, initials = _pinyin_pair(name)
            # akshare 自带拼音缩写，优先采用
            ak_initials = str(r.get("拼音缩写", "") or "").strip().upper()
            fund_type = str(r.get("基金类型", "") or "").strip()
            products.append(
                {
                    "type": "fund",
                    "code": code,
                    "name": name,
                    "pinyin": full,
                    "pinyinInitials": ak_initials or initials,
                    "exchange": "",
                    "tags": [fund_type] if fund_type else [],
                }
            )
        return products

    def _list_convertible_bonds(self) -> list[dict]:
        """可转债列表（MVP 债券范围，见 PLAN.md M3）。

        备源（2026-09-13）：东财限流时改用**新浪 cov_spot 快照**（约 320 只在交易标的）。
        覆盖度低于东财全量（1052 只，含未上市/待上市），属降级可用——避免限流期间
        转债列表整体为空、同步任务失败。
        """
        import akshare as ak

        products: list[dict] = []

        def _build(rows) -> list[dict]:
            out: list[dict] = []
            for item in rows:
                code = item.get("code") or ""
                name = item.get("name") or ""
                if not code or not name:
                    continue
                full, initials = _pinyin_pair(name)
                out.append(
                    {
                        "type": "bond",
                        "code": code,
                        "name": name,
                        "pinyin": full,
                        "pinyinInitials": initials,
                        "exchange": _exchange(code),
                        "tags": ["可转债"],
                    }
                )
            return out

        # 主源：东财全量
        try:
            df = _em_ak_request(ak.bond_zh_cov, 90.0, "ak.bond_zh_cov")
            products = _build(
                {"code": str(r.get("债券代码", "")).strip(), "name": str(r.get("债券简称", "")).strip()}
                for _, r in df.iterrows()
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("bond list primary (em) failed: %s", e)

        if products:
            return products

        # 备源：新浪转债实时快照（在交易标的）
        try:
            df2 = _ak_request(ak.bond_zh_hs_cov_spot, 45.0, "ak.bond_zh_hs_cov_spot")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"convertible bond list unavailable: {e}") from e
        products = _build(
            {
                "code": str(r.get("code") or "").strip()
                or str(r.get("symbol") or "").strip()[2:],
                "name": str(r.get("name", "")).strip(),
            }
            for _, r in df2.iterrows()
        )
        if not products:
            raise ProviderError("convertible bond list empty from all sources")
        return products


_akshare = AkshareProvider()
register(["stock", "fund", "bond"], _akshare)  # 行情：场内品种实时，场外基金每日净值
register_list(["stock", "fund", "bond"], _akshare)  # 产品列表：股票/基金/可转债
