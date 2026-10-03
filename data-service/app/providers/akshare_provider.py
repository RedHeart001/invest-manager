"""东财数据源适配器：A股 quote/kline/list + 基金/可转债列表。

接口约定见 PLAN.md。quote/kline 直连东财接口并做多 host 镜像降级 +
软失败重试（akshare 的在线接口无重试且软失败，不用于在线服务；仅在
产品列表同步时借用其封装）。东财对短时高频请求有反爬限流，同步类
接口应低频调用。
"""

import json
import logging
import re
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
from ..config import load_env
from ..utils.limiter import get_limiter
from ..utils.timeutil import beijing_now, beijing_today

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

# R15/M8：东财为 IP 级滚动窗口限流，全部域名共享一个额度——按"源族"限速。
# CR9-18：桶参数不在这里调，唯一来源是 `utils/limiter.py` 的 `PROFILES["eastmoney"]`
# （此处曾是"首调用获胜"的第二个参数通道，改动会静默失效）。
EM_LIMITER = get_limiter("eastmoney")
# #27：桶外那条路（`_ak_request`）的观测族。**与 EM_LIMITER 必须是不同实例**——共用就等于
# 把"不占东财桶"这件事悄悄改掉（第一步刻意零行为变化）。
AK_OBS_LIMITER = get_limiter("akshare-obs")


def _em_request(fn):
    """东财按需请求统一入口：限速排队 + 成功/失败回报（连续失败触发熔断）。"""
    if not EM_LIMITER.acquire():
        # CR9-26①（2026-09-26）：原文案尾巴是 "; fallback to backup source"，但**本函数不
        # 知道调用方是谁**——列表类（hk/crypto）按设计没有备源，这句话在那些路径上必然说谎
        # （09-26 14:38 那轮同步的 hk error 就是实证）。降级与否由 chain_call 在备源**真的
        # 成功**时如实标注（chain.py:31-35），这里只陈述自己确定的事实。
        raise ProviderError("eastmoney cooling down (rate-limited)")
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
    """非东财域名族的 akshare 调用：仅加看门狗超时（不占东财额度）。

    #27 第一步＝**纯观测**（10-03）：这条路上每一次调用按 `name` 记一笔进
    `get_limiter("akshare-obs")`。之所以只计数不拦截，是因为这条红线破口今天**没有任何
    可读计数面**——想判断"该不该给它补桶、补多大"，先得有真实次数。刻意**不调 `acquire()`**：
    观测不得改变行为（含"到限就拒"）。域名归属由计数与名字自证，不在注释里猜。
    """
    from ..utils.timeout import run_with_timeout

    AK_OBS_LIMITER.observe(name)
    value, err = run_with_timeout(fn, seconds, name)
    if err is not None:
        raise ProviderError(f"{name} failed: {err}") from err
    return value


# B4：_num 下沉到 app/utils/num.py（与 tencent_provider 共用）
from ..utils.num import to_float as _num  # noqa: E402
# CR6-P2-1：进程内缓存需容量上限（与 web lib/lru.ts 语义对齐），防长期运行内存无界增长。
from ..utils.lru import Lru, env_capacity  # noqa: E402


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


def _sina_symbol_exchange(symbol: str) -> str:
    """新浪 symbol（如 sh113050 / sz123285）→ 交易所代码（CR-17）。"""
    s = symbol.lower()
    if s.startswith("sh"):
        return "SH"
    if s.startswith("sz"):
        return "SZ"
    if s.startswith("bj"):
        return "BJ"
    return ""


# ---------- 美股主数据列表（CR9-59／#32 甲，2026-10-04 主人拍板"甲＋先不开美股 tab"） ----------
#
# 上游＝新浪 `US_CategoryService.getList`（`ak.stock_us_spot` 内部用的同一个接口，10-04 实测
# 抓到的是同一条 URL）。刻意**不借 akshare 那个函数**：它按 `num=20` 把 913 页全翻完
# ＝一次调用打满盘子（18,241 只、串行 11–20 分钟，比 A 股那条 56 页的备源贵 16 倍），
# 而甲要的是"前排常见标的先通入口"。翻页在这里自己做 ⇒ 请求数＝页数，可被 `US_LIST_PAGES` 限住。
US_LIST_URL = (
    "http://stock.finance.sina.com.cn/usstock/api/jsonp.php/"
    "IO.XSRV2.CallbackList[uslist]/US_CategoryService.getList"
)
US_LIST_PAGE_SIZE = 20  # 服务端把 `num` 硬截到 20（实测 num=100/500 都只回 20 行）⇒ 页数＝请求数
US_LIST_DEFAULT_PAGES = 15  # ≈300 只：第 1 页 NVDA/AAPL/GOOGL/GOOG/MSFT/AMZN、第 2 页 V/XOM/INTC/JNJ
US_LIST_PAGE_CEILING = 50  # 硬上限：防"合法但手滑多打两个 0"的 env 值变成几千次上游请求
US_LIST_PAGE_INTERVAL_S = 0.5  # 翻页之间的节流（新浪侧无声明，按对上游礼貌的常规间隔）
US_LIST_REQUEST_TIMEOUT_S = 20.0  # 单页超时（实测 0.19–6.31s，最慢那一档留 3 倍余量）
US_LIST_WHOLE_TIMEOUT_S = 150.0  # 整条列表的看门狗预算（夹到上限 50 页时够用）


def _us_list_pages() -> int:
    """取几页＝发几次请求（env `US_LIST_PAGES`）。两头的错都要防：非法值回落默认，
    合法但过大的值再夹一道硬上限（这条路上每一次翻页都是真金白银的上游请求）。"""
    load_env()
    return min(
        env_capacity("US_LIST_PAGES", US_LIST_DEFAULT_PAGES),
        US_LIST_PAGE_CEILING,
    )


def _jsonp_payload(text: str) -> dict:
    """新浪 jsonp ⇒ 内层 JSON。载荷实测形态（10-04 逐字）＝
    `/*<script>location.href='//sina.com';</script>*/` 换行后跟
    `IO.XSRV2.CallbackList[uslist]({"count":"18241","data":[{...}]});`
    纯函数，便于离线断言；解析不动就抛，不静默给空表（空表会被上游当"没有名单"）。"""
    m = re.search(r"\((.*)\)\s*;?\s*\Z", text.strip(), re.S)
    body = m.group(1) if m else text.strip()
    obj = json.loads(body)
    if not isinstance(obj, dict):
        raise ValueError(f"unexpected jsonp payload type: {type(obj).__name__}")
    return obj


def _us_product(row: dict) -> dict | None:
    """一行新浪美股记录 ⇒ 主数据 schema；**结构不可用**时返回 None。

    这里只管结构（无 `symbol` 或两个名字都缺 ⇒ 建不出 (type,code) 主键、展示不出名字），
    **不看品种、也不看行业**：行业那道闸在 `_list_us_stocks` 的循环里（主人的口径是
    "名单层面筛"，见 #32 的 (2)＝10-04 03:1x 定案），映射函数保持纯净，才能分别报出
    "结构丢弃"与"按口径剔除"是两个数。中文名优先（与 A股/港股同一套展示与拼音检索），
    `category`（行业，实测有 null 与空串）进 tags 与板块检索，`market` 原样进 `exchange`
    （`lib/profile.ts:91` 与 `tencent_provider.CURRENCY_BY_TYPE` 早已按 `us`/`NASDAQ` 写死）。
    """
    code = str(row.get("symbol") or "").strip()
    cn = str(row.get("cname") or "").strip()
    en = str(row.get("name") or "").strip()
    name = cn or en
    if not code or not name:
        return None
    full, initials = _pinyin_pair(name)
    category = str(row.get("category") or "").strip()
    return {
        "type": "us",
        "code": code,
        "name": name,
        "pinyin": full,
        "pinyinInitials": initials,
        "exchange": str(row.get("market") or "").strip(),
        "tags": [category] if category else [],
    }


# 交易状态前缀（#25 乙口径②，10-03 主人拍板）：XD/DR/XR＝当日除权除息，
# N＝上市首日，C＝上市后前几日无涨跌幅限制。**它们是"今天发生了什么交易"的快照，
# 不是名字的一部分**——明天就消失，而 `Product.name` 是整表覆盖写入的，于是同一个
# 代码的库内权威名会随"这一批由哪家上游供数"来回抖（东财 f14 在除息日同样带 XD，
# 新浪 hs_a 带得更频繁），搜索命中、拼音索引与 CR8-8 的"库内权威名"判据都跟着抖。
# 刻意**不剥** `ST`/`*ST`：CR8-8 的既有口径是"只滤退市，ST/*ST 与北交所保留"
# （主人 09-30 的字，`web/lib/hotspots.ts:159`）。
_STATUS_PREFIXES = ("XD", "DR", "XR", "N", "C")


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def strip_status_prefix(name: str) -> str:
    """剥掉交易状态前缀，返回可用于入库的名字；已是干净名时原样返回（幂等）。

    要求前缀后紧跟一个汉字才剥——避免把真名里以拉丁字母开头的部分啃掉
    （`TCL科技`／`CICC` 这类），也避免 `"XD"` 这种整条就是前缀的畸形行被清成空名。
    """
    s = name.strip()
    for prefix in _STATUS_PREFIXES:
        if s.startswith(prefix) and len(s) > len(prefix) and _is_cjk(s[len(prefix)]):
            return s[len(prefix) :].strip()
    return s


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

    注意（CR4 / 2026-09-15 review 重构）：多 host 循环必须包在**单个**
    `_em_request` 闭包内，以"逻辑请求"为单位只 acquire/回报一次——
    此前每次 host 尝试独立计次，`failure_threshold=2` 下前两个 host 抖动
    即触发全源族熔断 180s+（第 3 个 host 几乎永远轮不到）。同时
    **状态码校验与 JSON 解析必须在闭包内完成**，5xx/非 JSON 不得清零
    熔断计数（C6）。
    """

    def _multi_host_fetch() -> dict:
        last_err = None
        for _round in range(2):
            for host in EM_HOSTS:
                try:
                    r = requests.get(
                        f"{host}{path}",
                        params=params,
                        timeout=REQUEST_TIMEOUT,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    r.raise_for_status()  # 校验放在限速器成功回报之前（C6）
                    return r.json()
                except Exception as e:  # noqa: BLE001 网络/接口抖动，换 host 重试
                    last_err = e
        raise ProviderError(f"eastmoney request failed on all hosts: {last_err}")

    return _em_request(_multi_host_fetch)


class AkshareProvider(BaseProvider):
    source = "akshare"

    def __init__(self):
        self._fund_nav = None
        self._fund_nav_ts = 0.0
        # CR-19：净值表单失败负缓存时间戳（0 = 无失败）
        self._fund_nav_fail_ts = 0.0
        # CR6-P2-1：原为无界 dict（热点 pipeline 会命中大量不同 code → 持续累积）。
        # 上限可经 env 覆盖：AK_NEWS_CACHE_MAX / AK_FUND_REPORT_CACHE_MAX。
        self._news_cache: Lru[str, tuple[float, list[dict]]] = Lru(
            env_capacity("AK_NEWS_CACHE_MAX", 512)
        )
        self._fund_report_cache: Lru[str, tuple[float, dict]] = Lru(
            env_capacity("AK_FUND_REPORT_CACHE_MAX", 256)
        )
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
    # CR-19（本轮 code review）：失败负缓存——场外基金净值表单是全市场单请求，
    # 失败（限流/接口变动）时此前无冷却，导致限流期每个场外基金请求都整表重拉
    # （60s 看门狗），反复捶打天天基金。对齐 crypto_provider 的失败冷却模式。
    FUND_NAV_FAIL_COOLDOWN = 300  # 5 分钟

    def _fund_nav_table(self):
        now = time.time()
        if self._fund_nav is not None and now - self._fund_nav_ts < self.FUND_NAV_TTL:
            return self._fund_nav
        # 失败冷却期内直接降级（不重复整表重拉）
        if now - self._fund_nav_fail_ts < self.FUND_NAV_FAIL_COOLDOWN:
            raise ProviderError(
                f"fund nav table cooling down after recent failure; retry in ~"
                f"{int(self.FUND_NAV_FAIL_COOLDOWN - (now - self._fund_nav_fail_ts))}s"
            )
        import akshare as ak

        try:
            df = _ak_request(ak.fund_open_fund_daily_em, 60.0, "ak.fund_open_fund_daily_em")
            # C2（CR7-8，2026-09-25）：空表视同失败——此前"不抛异常就写缓存"，
            # 上游返回空 df 会把"成功但空"缓存 30min，让**所有**场外基金静默失去净值
            # （与 C11 kline 空响应口径一致：空 = 上游契约破坏，必须显式降级）。
            if df is None or len(df) == 0:
                self._fund_nav_fail_ts = time.time()
                raise ProviderError("fund nav table empty (upstream contract broken)")
            self._fund_nav = df
            self._fund_nav_ts = now
            self._fund_nav_fail_ts = 0.0
        except ProviderError:
            # C2：空表路径已在上面记了 fail_ts，这里原样上抛（不重复记账）
            raise
        except Exception as e:  # noqa: BLE001 接口变动/网络
            # CR-19：失败路径必须与成功路径对称记账（否则守卫恒假 = 死代码）
            self._fund_nav_fail_ts = time.time()
            raise ProviderError(f"fund nav table failed: {e}") from e
        return self._fund_nav

    def _fund_nav_quotes(self, codes: list[str]) -> dict[str, dict]:
        df = self._fund_nav_table()
        # C2：空表已在 _fund_nav_table 内抛 ProviderError，此处 df 必非空——
        # 但列缺失（上游改列名）同样是契约破坏，必须显式降级而非 return {}
        # （此前静默返回 {} 会让全部场外基金无 note 地失去净值）。
        nav_col = next(
            (c for c in df.columns if str(c).endswith("-单位净值")), None
        )
        if nav_col is None or "日增长率" not in df.columns:
            raise ProviderError(
                f"fund nav table columns missing (upstream renamed?): "
                f"has 单位净值-suffix={nav_col is not None}, has 日增长率={'日增长率' in df.columns}"
            )

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
            # CR9-16（§B 北京时间口径）：此处原为本地 date.today()，主机时区非 +08 时
            # 会在跨日窗口取到错误日期（分钟线只有"当日"这一种取法，取错即整段空）。
            today = beijing_today().replace("-", "")
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

        # CR4：多 host 循环包在单个 `_em_request` 闭包内（单逻辑请求只计次一次），
        # 空数组视为"成功但无数据"（交给调用方/上位缓存判断），非 5xx。
        def _fetch_kline_all() -> list:
            last_err = None
            for _round in range(2):
                for host in EM_HIST_HOSTS:
                    try:
                        r = requests.get(
                            f"{host}/api/qt/stock/kline/get",
                            params=params,
                            timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"},
                        )
                        # 状态校验与解析必须在限速器闭包内（否则失败被记为成功，C6）
                        r.raise_for_status()
                        data = (r.json() or {}).get("data") or {}
                        kl = data.get("klines") or []
                        if kl:
                            return kl
                        last_err = f"{host} returned empty klines"
                    except Exception as e:  # noqa: BLE001 网络/接口抖动，换 host 重试
                        last_err = e
                time.sleep(1)
            raise ProviderError(f"eastmoney kline failed on all hosts: {last_err}")

        klines = _em_request(_fetch_kline_all)
        if not klines:
            raise ProviderError(f"eastmoney kline empty on all hosts: {code}")

        # kline 字符串格式：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
        candles = []
        for item in klines:
            f = item.split(",")
            # CR4（2026-09-15 review）：上游截断/异常行时 len<7 会 IndexError 逃逸
            # （非 ProviderError，chain_call 不捕获）→ 端点 500。提前跳过。
            if len(f) < 7:
                continue
            # CR6-P1-3：KlineDaily.open/high/low/close 为 NOT NULL，单行 null
            # 会让 web 侧整批 upsert 失败、该标的 K 线持续不可用。与 sina 对齐，
            # 任一 OHLC 缺失即跳过该行。
            o, c, h, low_ = _num(f[1]), _num(f[2]), _num(f[3]), _num(f[4])
            if None in (o, c, h, low_):
                continue
            candles.append(
                {
                    "date": f[0],
                    "open": o,
                    "close": c,
                    "high": h,
                    "low": low_,
                    "volume": _num(f[5]),
                    "amount": _num(f[6]),
                }
            )
        if not candles:
            raise ProviderError(f"eastmoney kline unparsable: {code}")
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

        # CR9-16（§B 北京时间口径）：年份按北京时间取——本地时区在 12-31/01-01 窗口会枚举错年份
        bj_year = beijing_now().year
        last_err = None
        for year in (str(bj_year), str(bj_year - 1)):
            try:
                df = _ak_request(lambda: ak.fund_portfolio_hold_em(symbol=code, date=year), 40.0, "ak.fund_portfolio_hold_em")
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
            if df is None or len(df) == 0:
                continue
            # CR9-17（C2 显式降级）：列名由上游决定。此前 `df["季度"]` 落在 try 之外，
            # 上游改列名会以裸 KeyError 冒到 HTTP 层变成 500，而不是"该源不可用"的降级。
            if "季度" not in df.columns:
                last_err = f"缺列「季度」（上游表结构变更），实际列={list(df.columns)[:8]}"
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

        # CR9-16（§B 北京时间口径）：年份走北京时间，与本文件其余日期口径一致
        bj_year = beijing_now().year

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
        for year in (str(bj_year), str(bj_year - 1)):
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

    def list_products(self, type_: str) -> list[dict] | tuple[list[dict], dict]:
        """产品列表。stock/bond 两条自带主备切换 ⇒ 按 CR9-31 以 `(items, meta)` 声明出网源，
        fund 单一上游 ⇒ 仍是裸 `list[dict]`（两种形态由 `list_products_with_meta` 归一）。
        """
        if type_ == "stock":
            return self._list_stocks()
        if type_ == "fund":
            return self._list_funds()
        if type_ == "bond":
            return self._list_convertible_bonds()
        if type_ == "us":
            return self._list_us_stocks()
        raise ProviderError(f"unsupported list type: {type_}")

    def _list_stocks(self) -> tuple[list[dict], dict]:
        """A 股主数据列表：东财 `clist/get` 为主源，失败时降级到新浪 `hs_a` 快照（#25 乙，10-03 立项）。

        为什么现在必须有备源（10-03 实测）：东财 `clist/get` 对三个 host、`pz=200` 与
        `pz=10000` 一律 `RemoteDisconnected`＝列表链路**硬不可用**（行情/K 线仍正常，与
        CR9-40 记的形态同款），`Product.stock` 因此停在 09-12 已经 21 天；此前这条链路只有
        单家上游，失败即整轮 `partial_failed`，陈旧只能靠 `staleNotes` 说一句（#25 甲）。

        覆盖面差异已按两份全量实测归因（10-03）：东财 5913 vs 新浪 5571，重叠 5570——
        **库里多出、新浪没有的 343 只全是已摘牌/退市类代码**（其中名字含「退市」61 只、
        `ST`/`*ST` 开头 112 只），新浪独有的只有 1 只（`920202` 北交所）；新浪侧含北交所
        348 只，与 `_exchange()` 对 920 段的判定逐项一致 ⇒ 降级不是"少一块市场"（口径①）。
        代价在名字列（写进 note，别让消费侧自己发现）：换源那夜 101/5570（1.81%）行的名字会被
        改写，按互斥分类实测＝**44 行整批丢掉 `-U`/`-W`/`-UW` 后缀**、10 行只是全角名里的空格数
        不同、5 行的 `ST` 标记一边有一边无（4 无 1 有，那 1 行是 21 天的日期差不是源差），其余是
        状态前缀归属不同（新浪今日 28 行带 XD/N、库内 17 行带）。⚠️ **两边都会在打前缀时把名字
        截到 5 字符**（`XD万华化` ⇔ `万华化学`）⇒ `strip_status_prefix` 去掉的是前缀，**补不回
        被截掉的字**，那是上游短名字段的形态，不是我们能洗回来的。
        """
        em_err = ""
        try:
            products = self._list_stocks_em()
        except Exception as e:  # noqa: BLE001 主备切换的判据是"有没有拿到行"，异常一律收下转述
            em_err = f"{type(e).__name__}: {e}"
            logger.warning("stock list primary (em clist) failed: %s", e)
            products = []

        if products:
            return products, {"source": "akshare"}

        import akshare as ak

        try:
            df = _ak_request(ak.stock_zh_a_spot, 120.0, "ak.stock_zh_a_spot")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"stock list unavailable: {e}") from e

        out: list[dict] = []
        for _, row in df.iterrows():
            # 本机 akshare 的 stock_zh_a_spot 列名是中文（代码=带交易所前缀的 symbol），
            # 与同版本 bond_zh_hs_cov_spot 的英文列名不一致 ⇒ 两种键名都读一次，不猜版本。
            symbol = str(row.get("代码") or row.get("symbol") or "").strip().lower()
            name = strip_status_prefix(str(row.get("名称") or row.get("name") or ""))
            code = symbol[2:] if symbol[:2].isalpha() else symbol
            if not code or not name:
                continue
            full, initials = _pinyin_pair(name)
            out.append(
                {
                    "type": "stock",
                    "code": code,
                    "name": name,
                    "pinyin": full,
                    "pinyinInitials": initials,
                    # CR-17 同口径：新浪 symbol 显式带 sh/sz/bj 前缀，不再靠数字前缀推断
                    "exchange": _sina_symbol_exchange(symbol) or _exchange(code),
                    "tags": [],
                }
            )
        if not out:
            raise ProviderError("stock list empty from all sources")
        return out, {
            "source": "sina-a-share-spot",
            "degraded": True,
            "note": (
                f"东财 A 股列表不可用（{em_err or '未知原因'}），已降级至新浪 hs_a 快照："
                f"本次 {len(out)} 只、天然仅含在交易标的（库里留存的已摘牌代码这次不会带来），"
                "且新浪的名称列是短名（实测最长 6 字、带 XD/DR 状态前缀时只剩 3 个字），"
                "并整批不带 -U/-W 后缀"
            ),
        }

    def _list_stocks_em(self) -> list[dict]:
        """A 股全量列表（东财主源）：优先单次大分页，未拿全则回退分页抓取。"""
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
            # #25 乙第 1 步：东财 f14 在除息日也带 XD/DR 前缀 ⇒ 入库前先洗成权威名，
            # 并且**拼音要用洗完的名字生成**（否则 `XD` 会被读成拉丁字母进拼音串）。
            name = strip_status_prefix(str(item.get("f14") or ""))
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

    def _list_convertible_bonds(self) -> tuple[list[dict], dict]:
        """可转债列表（MVP 债券范围，见 PLAN.md M3）。

        备源（2026-09-13）：东财限流时改用**新浪 cov_spot 快照**（约 320 只在交易标的）。
        覆盖度低于东财全量（1052 只，含未上市/待上市），属降级可用——避免限流期间
        转债列表整体为空、同步任务失败。

        CR9-31（2026-09-27）：走备源时**必须把这件事说出来**。此前响应里只有
        `type/count/products`，09-27 实测降级态 `count=327` 与"上游把转债砍到 327 只"
        长得一模一样 ⇒ 降级对消费侧完全不可见（违 R16），BFF 的缩水保护也只能写"疑似"。
        现在两条路径各自带回真实出网源，备源另带 `degraded`/`note`（与行情链路
        `chain_call` 的标注口径一致）。
        """
        import akshare as ak

        def _build(rows) -> list[dict]:
            out: list[dict] = []
            for item in rows:
                code = item.get("code") or ""
                name = item.get("name") or ""
                if not code or not name:
                    continue
                full, initials = _pinyin_pair(name)
                # CR-17（本轮 code review）：优先用调用方显式给出的交易所（新浪备源的
                # symbol 带 sh/sz 前缀）；缺失时才回退到数字前缀推断，不再依赖隐含约定。
                exchange = item.get("exchange") or _exchange(code)
                out.append(
                    {
                        "type": "bond",
                        "code": code,
                        "name": name,
                        "pinyin": full,
                        "pinyinInitials": initials,
                        "exchange": exchange,
                        "tags": ["可转债"],
                    }
                )
            return out

        # 主源：东财全量
        em_err = ""
        try:
            df = _em_ak_request(ak.bond_zh_cov, 90.0, "ak.bond_zh_cov")
            products = _build(
                {"code": str(r.get("债券代码", "")).strip(), "name": str(r.get("债券简称", "")).strip()}
                for _, r in df.iterrows()
            )
        except Exception as e:  # noqa: BLE001
            em_err = f"{type(e).__name__}: {e}"
            logger.warning("bond list primary (em) failed: %s", e)
            products = []

        if products:
            return products, {"source": "akshare"}

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
                # CR-17：从新浪 symbol 前缀（sh/sz）显式带出交易所，不再依赖数字前缀推断
                "exchange": _sina_symbol_exchange(str(r.get("symbol") or "").strip()),
            }
            for _, r in df2.iterrows()
        )
        if not products:
            raise ProviderError("convertible bond list empty from all sources")
        return products, {
            "source": "sina-bond-cov-spot",
            "degraded": True,
            "note": (
                f"东财转债全量列表不可用（{em_err or '未知原因'}），已降级至新浪 cov_spot 快照："
                f"本次 {len(products)} 只、天然仅含在交易标的（东财全量约 1052 只，含未上市/待上市）"
            ),
        }

    def _list_us_stocks(self) -> tuple[list[dict], dict]:
        """美股主数据＝新浪排行名单的**有界前 N 页**（CR9-59／#32 甲，主人 2026-10-04 定案）。

        为什么不一次拉全（10-03/10-04 实测，不是推断）：`num` 被服务端硬截到 20 ⇒ 全量
        18,241 只＝**913 次请求**、串行 ≈11–20 分钟，比 A 股那条 56 页的备源贵 16 倍；
        而 `market` 参数不生效（传 NASDAQ 照样混返回），想按交易所缩盘子只能全量再自筛。
        该接口按热度/市值排序 ⇒ "前 N 页"就是最常见那一批（第 1 页 NVDA/AAPL/GOOGL/GOOG/
        MSFT/AMZN），甲要买的"详情页不再 404、代码搜得通"由它就够了，长尾留给乙。

        刻意声明 `degraded`：覆盖面**按设计**小于上游自己报的总数（不是上游挂了），
        按 CR9-31 的口径这必须让消费侧读得到，否则"300 只"与"全量"长得一模一样。
        10-04 03:1x 主人的字（#32 的 (2)）在此再加一道**行业闸**＝`category` 为 null 或空串
        的行不进库；闸在解析之后、翻页之前 ⇒ **请求数不受它影响**（15 页仍是 15 次），
        它只缩名单不缩额度。
        """
        pages = _us_list_pages()

        def _fetch() -> tuple[list[dict], str, list[str], int]:
            rows: list[dict] = []
            seen: set[str] = set()
            declared = ""
            failures: list[str] = []
            dropped = 0  # #32 的 (2) 定案：按"没有行业标签"剔掉的行数（要能在 note 里看见）
            for page in range(1, pages + 1):
                if page > 1:
                    time.sleep(US_LIST_PAGE_INTERVAL_S)
                try:
                    res = requests.get(
                        US_LIST_URL,
                        params={
                            "page": str(page),
                            "num": str(US_LIST_PAGE_SIZE),
                            "sort": "",
                            "asc": "0",
                            "market": "",
                            "id": "",
                        },
                        timeout=US_LIST_REQUEST_TIMEOUT_S,
                    )
                    res.raise_for_status()
                    payload = _jsonp_payload(res.text)
                except Exception as e:  # noqa: BLE001 中途失败要能带着已拿到的行继续，成因要能转述
                    # 记 **类型＋原话**（CR9-30 同族：只有类名的错误说明归不了因——
                    # `RemoteDisconnected` 与 `Timeout` 都叫 `ConnectionError`）。截 60 字防
                    # requests 把整条 URL 塞进 message。
                    failures.append(f"p{page}:{type(e).__name__}: {str(e)[:60]}")
                    logger.warning("us list page %s failed: %s", page, e)
                    continue
                if not declared:
                    declared = str(payload.get("count") or "")
                data = payload.get("data") or []
                for row in data:
                    product = _us_product(row)
                    if product is None or product["code"] in seen:
                        continue
                    # 行业闸排在**去重登记之前**：被这道闸剔掉的代码不进 `seen`，所以同一
                    # 代码在后一页带上行业时还能被救回来——口径闸不许冒充去重闸。
                    if not product["tags"]:
                        dropped += 1
                        continue
                    seen.add(product["code"])
                    rows.append(product)
                if len(data) < US_LIST_PAGE_SIZE:
                    break  # 上游给不满一页＝已到尾部（10-03 实测第 913 页只回 1 行）
            return rows, declared, failures, dropped

        rows, declared, failures, dropped = _ak_request(
            _fetch, US_LIST_WHOLE_TIMEOUT_S, "sina.us-list"
        )
        if not rows:
            raise ProviderError(
                "us list empty from all pages"
                f"（{pages} 页{'，失败：' + '、'.join(failures[:5]) if failures else '全无载荷'}"
                f"，剔无行业 {dropped} 行）"
            )

        markets: dict[str, int] = {}
        for r in rows:
            key = r["exchange"] or "?"
            markets[key] = markets.get(key, 0) + 1
        spread = "/".join(f"{k}×{v}" for k, v in sorted(markets.items()))
        note = (
            f"美股主数据按甲方案只取前排 {pages} 页"
            + (f"（上游声明盘子 {declared} 只 ⇒ 本次留 {len(rows)} 只）" if declared else "")
            + f"；按「没有行业标签即剔除」的口径剔掉 {dropped} 行、交易所分布 {spread}。"
            "⚠️ 这条筛法不等于「只留普通股」：新浪的行业字段缺失与品种无关"
            "（实测 Visa/Meta 这一档常为空），所以带行业的 ETF 照样进来、"
            "不带行业的普通股被砍（#32 的 (2)＝主人 10-04 定案，代价已知）"
            + (
                f"；本次 {len(failures)} 页失败（{'、'.join(failures[:3])}）"
                "⇒ 行数可能低于前排应有规模"
                if failures
                else ""
            )
        )
        return rows, {"source": "sina-us-category-list", "degraded": True, "note": note}


_akshare = AkshareProvider()
register(["stock", "fund", "bond"], _akshare)  # 行情：场内品种实时，场外基金每日净值
register_list(["stock", "fund", "bond", "us"], _akshare)  # 产品列表：股票/基金/可转债/美股（CR9-59）
# 注意这里**只注册列表**：美股的行情/K 线仍由 `openbb_provider`（yfinance）与腾讯 us 现价
# （CR9-52）承担，上面那行 `register(["stock","fund","bond"])` 刻意不加 us。
