"""OPT-3 第一批 1a（CR9-92）：「当日实时行情条」的取数侧＝多源实时行情聚合器。

需求与定案见 `docs/PLAN.md:166-179`（M3）。这个文件只做取数侧的四件事：
点名的腿 → 每源独立短超时 → 共识取值＋空壳门 → `sources` 全公开。

三条红线写在这里，因为它们决定了**为什么不能复用现成的那三条路**：

1. **不得注册成链上的一个 provider**（定案 (b) 的红线）。所以本文件不调 `register_chain`，
   响应也不经 `get_provider_chain` 产生；闸2 与离线套件都各有一枚断言盯着这一条形。
2. **实时轮询不打东财**（`PLAN.md:172`，验收判据 ④＝东财令牌消耗不因该区域而上升）。
   所以这里点名的腿只有腾讯与新浪。
3. **实时路径上不许出现 20s 排队**（10-12 三条改判的第 (三) 条）。`chain_call`/`verify_metric`
   都会先向链上主源要额度，而桶是**先睡后拒**（`utils/limiter.py:136` 的 `acquire(timeout=20)`），
   最坏 20+3≈23s ⇒ "现价 10s 一跳"会先被自家排队打破。所以本文件**只 `observe()` 不 `acquire()`**，
   超时全部由 `LEG_TIMEOUT_S` 给，一张表里读得出最坏耗时。

1a 与 1b 的分工（`PLAN.md:176`）：本文件里**没有任何"测出来的数"**——
TTL、并发 N、共识阈值三样都属于 1b，欠的是前置实测 ②③④（10-13 A 窗）。
⇒ 本端点**不缓存**：浏览器每 10s 一跳就是每 10s 真出网一次，这正是格三要靠独立观测族攒计数的原因。
"""

from __future__ import annotations

import re
import time

import requests

from .providers.base import ProviderError, ProviderNotSupported
from .providers.tencent_provider import (
    _quote_symbol,
    _symbol as _cn_prefix_symbol,
    _symbol_for,
    _us_fields_match,
    fields_to_quote,
    fetch_minute_payload,
    fetch_quote_fields,
    minute_rows_to_candles,
)
from .utils.limiter import get_limiter
from .utils.num import to_float
from .utils.timeutil import beijing_now, beijing_today

# 每源独立超时（PLAN.md:172「每源独立 3s 超时」）。一条响应最坏＝腿数 × 本值，
# 串行发起 ⇒ stock 三发＝9s；web 侧 BFF 预算必须 ≥ 这个数（CR9-88 那条 §B 契约）。
LEG_TIMEOUT_S = 3.0

# 空壳门：一根都不给＝没数据；只给一根＝上游空壳（CR9-44 实测的转债分时形状是
# 今开 0.000／成交量 0／bars=1，能返回 200，但不是一个交易日）。
MINUTE_MIN_BARS = 2

# 共识阈值＝沿用 `/quote/verified` 既有的 0.5%（**不是**新造一个数）。它是 1b 要定的三样之一：
# #64 甲 之后主链共识参考值还没测到，"取比主链实测更宽的一档"这句话因此**落不了地**，
# 所以这里显式标 `provisional: true`，由读数面而不是屏上文案说话（10-05 那条纪律）。
CONSENSUS_THRESHOLD_PCT = 0.5

# 独立观测族（10-12 三条改判的第 (二) 条）：腾讯侧在 `PROFILES` 里没有族闸，
# 格三那句 `N×(60/TTL)≤12` 算的是错对象 ⇒ N 只能靠这一族攒真计数。只 observe 不 acquire。
OBS_FAMILY = "realtime-obs"

# 两条节奏（`PLAN.md:172`＝现价 10s、分时 60s）落到请求面上就是这一位：一次调用可以只跑现价。
PARTS: tuple[str, ...] = ("price", "intraday")

SINA_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}

# 点名的腿（10-12 定档＝乙：给 stock 补一条新浪现价腿；扣掉东财后 A股／场内基金／hk 的现价
# 本来只剩腾讯一家，"共识取值"对这三类结构性不成立）。
SOURCE_LEGS: dict[str, dict[str, tuple[str, ...]]] = {
    "stock": {"price": ("tencent", "sina"), "intraday": ("tencent",)},
    # fund 只有**场内**有腿：场外净值全在 `fund.eastmoney`（＝红线），而腾讯的 `_symbol_for`
    # 按场内判据强制拒绝场外码（CR9-1 的串号守卫）。场外 ⇒ 一条腿都不成 ⇒ 整块不渲染（判据②）。
    "fund": {"price": ("tencent",), "intraday": ("tencent",)},
    "hk": {"price": ("tencent",), "intraday": ("tencent",)},
    "us": {"price": ("tencent",), "intraday": ()},
    "bond": {"price": (), "intraday": ()},
    "crypto": {"price": (), "intraday": ()},
}

# 没腿的那些必须**自己说为什么**（R16：不许让消费侧猜）。三条理由来路不同：
# 前两条是 09-27 定案 (d) 的裁剪，第三条是 10-13 现查码面证伪了定案 (e) 的一个前提。
UNWIRED_REASON: dict[str, str] = {
    "bond": "转债不入首轮（09-27 定案 (d)）；且分时只有东财一家＝正撞"
    "「实时轮询不打东财」，腾讯那条对 bond 是空壳（CR9-44）",
    "crypto": "加密不入首轮（09-27 定案 (d)）：现价只有 CoinGecko 一家且 10s 即限流、币安 451 地区封锁",
    "us.intraday": "美股分时在现实现下**没有任何腿可点名**：`openbb_provider.py:178` 对 us 只给 "
    "`interval==\"1d\"`，腾讯/新浪的分钟路径对 us 直接抛 NotSupported ⇒ 定案 (e) 那句「美股分时＝Yahoo 单源」"
    "从来没有对应实现（现查证伪，登记为待拍板 #67）",
}


def _observe(kind: str, source: str, type_: str) -> None:
    """纯计数一条（**不改任何行为**，包括"到限就拒"）。名字基数有界：2 类腿 × 2 家源 × 6 类型。"""
    get_limiter(OBS_FAMILY).observe(f"realtime.{kind}.{source}.{type_}")


def _sina_fields(text: str) -> list[str]:
    body = text.split('="', 1)[-1].rstrip('";\r\n ')
    return body.split(",")


def sina_fields_to_quote(code: str, f: list[str]) -> dict:
    """新浪现价字段位 → 统一行情 dict（与腾讯那份**同形**，共识比对才成立）。

    形状判据来自 09-27 的实网探针（`test-script/realtime_probe.py` 的 `p_sina_quote`：
    `ok=12/12 gap=5s p50=356ms bytes=288`，取的是 0 名称／3 现价／30 日期三枚位）。
    这里多要一位 31（时间），并钉住"字段数 ≥32 且日期时间是可解析的两串"——
    形状一变就响亮地报错，不悄悄交出一个 0 价（空壳门）。
    """
    if len(f) < 32:
        raise ProviderError(f"sina quote 字段数 {len(f)} < 32（上游形状变了）")
    day, clock = f[30].strip(), f[31].strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not re.fullmatch(r"\d{2}:\d{2}:\d{2}", clock):
        raise ProviderError(f"sina quote 日期/时间形状不可解析：{day!r} {clock!r}")
    price = to_float(f[3])
    if price is None or price <= 0:
        raise ProviderError(f"sina quote 无有效现价（{code}: {f[3]!r}）＝空壳门")
    prev = to_float(f[2])
    volume = to_float(f[8])
    return {
        "type": "stock",
        "code": code,
        "name": f[0],
        "price": price,
        "prevClose": prev,
        "open": to_float(f[1]),
        # 新浪 f[8] 单位是**股**，腾讯 f[6] 是**手** ⇒ 归一到既有 schema 的"手"，
        # 否则同一屏换个源就小两个量级（这份 schema 是消费侧唯一的单位口径）。
        "volume": None if volume is None else volume / 100.0,
        "timestamp": f"{day}T{clock}",
        "change": None if price is None or prev is None else price - prev,
        "changePct": None if price is None or not prev else (price - prev) / prev * 100.0,
        "high": to_float(f[4]),
        "low": to_float(f[5]),
        "currency": "CNY",
        "source": "sina",
    }


def _price_leg(source: str, type_: str, code: str) -> dict:
    if source == "tencent":
        sym = _quote_symbol(type_, code)
        if sym is None:
            raise ProviderNotSupported(f"tencent does not support code: {code}")
        f = fetch_quote_fields([sym], LEG_TIMEOUT_S).get(sym)
        if not f:
            raise ProviderError(f"tencent quote missing: {code}")
        if type_ == "us" and not _us_fields_match(code, f):
            # 串号守卫必须在实时区同样生效：CR9-1 那一形（别家品种的价格被当成这只交付）
            # 与"走哪条链路"无关，摘掉守卫就等于实时区独享一个冒领风险。
            raise ProviderError(f"tencent us symbol mismatch: 请求 {code} 返回 {f[2]}")
        return fields_to_quote("tencent", type_, code, f)
    if source == "sina":
        if type_ != "stock":
            raise ProviderNotSupported(f"sina 现价腿本轮只做 A股（{type_} 的新浪现价从未实测）")
        sym = _cn_prefix_symbol(code)
        if sym is None:
            raise ProviderNotSupported(f"sina unsupported code: {code}")
        r = requests.get(
            f"https://hq.sinajs.cn/list={sym}",
            timeout=LEG_TIMEOUT_S,
            headers=SINA_HEADERS,
        )
        r.raise_for_status()
        return sina_fields_to_quote(code, _sina_fields(r.content.decode("gbk", errors="ignore")))
    raise ProviderNotSupported(f"没有这条腿：{source}")


def _intraday_leg(source: str, type_: str, code: str) -> tuple[str, list[dict]]:
    if source != "tencent":
        raise ProviderNotSupported(f"没有这条腿：{source}")
    sym = _symbol_for(type_, code)
    if sym is None:
        raise ProviderNotSupported(f"tencent does not support code: {code}")
    day, rows = fetch_minute_payload(sym, LEG_TIMEOUT_S)
    if not rows or len(day) != 8:
        raise ProviderError(f"tencent minute empty: {code}")
    candles = minute_rows_to_candles(day, rows)
    if len(candles) < MINUTE_MIN_BARS:
        raise ProviderError(f"空壳门：分时只返回 {len(candles)} 根（< {MINUTE_MIN_BARS}）")
    return f"{day[:4]}-{day[4:6]}-{day[6:8]}", candles


def _run_leg(kind: str, source: str, type_: str, code: str) -> tuple[dict, object | None]:
    """跑一条腿并把"跑了谁、成没成、多久"记进 `sources`（全公开＝失败的那几条也要在案）。"""
    _observe(kind, source, type_)
    t0 = time.perf_counter()
    detail: str | None = None
    value: object | None = None
    try:
        value = (
            _price_leg(source, type_, code)
            if kind == "price"
            else _intraday_leg(source, type_, code)
        )
        ok = True
    except (ProviderError, ProviderNotSupported) as e:
        detail = str(e)
        ok = False
    except Exception as e:  # noqa: BLE001 实时路径上任何一条腿都不许把整个端点带崩（R10）
        detail = f"{type(e).__name__}: {str(e)[:120]}"
        ok = False
    entry = {
        "kind": kind,
        "source": source,
        "ok": ok,
        "latencyMs": round((time.perf_counter() - t0) * 1000),
        "detail": detail,
    }
    return entry, value if ok else None


def _diff_pct(primary: float, other: float) -> float:
    """与 `chain.py:96-99` 同一条算式（相对主源的偏差 %）——分歧率的分子必须两边同形。"""
    base = abs(primary) or 1.0
    return abs(primary - other) / base * 100.0


def aggregate(type_: str, code: str, parts: tuple[str, ...] = PARTS) -> dict:
    """一条响应：现价（含共识）＋当日分时（含归属日判据）＋这一轮点名了谁。

    `parts`＝这一轮要跑哪几条腿（`PLAN.md:172` 定的是**两个节奏**：现价 10s、分时 60s）。
    浏览器每 10s 只问现价时，那条 11–14KB 的分时腿就不该被放大 6 倍，所以分开跑；
    代价是"这一轮没跑分时"必须能说出口 ⇒ `hasTodayData`／`intradayDateIsToday` 在这种响应里是
    **`null`（不知道）**，不是 `false`（没有当日数据）——与 `usesEastmoney` 那枚三态同一条纪律
    （CR9-67 丙：把"不知道"读成"没有"就是假结论的来源）。

    抛 `KeyError`＝这个类型码根本没在实时区登记过（调用方转 400）；
    有登记但一条腿都不成＝**200 ＋ degraded**（R10：详情页不该因为实时条拿不到而整页报错）。
    """
    legs = SOURCE_LEGS[type_]  # KeyError 由调用方映射成 400
    wanted = [p for p in PARTS if p in parts]
    today = beijing_today()
    sources: list[dict] = []
    notes: list[str] = []

    prices: list[dict] = []
    if "price" in wanted:
        for src in legs["price"]:
            entry, value = _run_leg("price", src, type_, code)
            sources.append(entry)
            if isinstance(value, dict):
                prices.append(value)
            elif entry["detail"]:
                notes.append(f"{src} 现价腿不可用（{entry['detail']}）")

    intraday_date: str | None = None
    candles: list[dict] = []
    if "intraday" in wanted:
        for src in legs["intraday"]:
            entry, value = _run_leg("intraday", src, type_, code)
            sources.append(entry)
            if isinstance(value, tuple):
                intraday_date, candles = value[0], value[1]
            elif entry["detail"]:
                notes.append(f"{src} 分时腿不可用（{entry['detail']}）")

    # 共识维（定案 (a)＋(e)：做不到两源的类别必须显式说"未交叉核对"，不许显示成"已核对"）
    diff_pct: float | None = None
    if len(prices) >= 2:
        diff_pct = _diff_pct(float(prices[0]["price"]), float(prices[1]["price"]))
        verdict = "diverged" if diff_pct > CONSENSUS_THRESHOLD_PCT else "agree"
        cross_checked = True
        if verdict == "diverged":
            # 这一句会**原样上屏**（`RealtimeStrip.tsx:109` 的 diverged 分支显示 `note`），所以它只说"谁和谁"：
            # 偏差百分比／阈值／"暂定值"三样都住在 `consensus.{diffPct,thresholdPct,provisional}`——
            # 面向开发者的比率不进用户可见文案（10-05 那条纪律；:52-54 的注释此前只说了没说）。
            notes.append(f"⚠ 双源价格不一致（{prices[0]['source']} vs {prices[1]['source']}）")
    else:
        verdict = "no_second_source"
        cross_checked = False
        # 这条是**结构性**说明（首轮源集天然如此），不是"这一次没连上"⇒ 不参与 degraded 判定，
        # 否则 fund/hk/us 三类会永远带着 degraded，那个键就再也没人说得出"这一轮真出问题了"。
        if prices:
            notes.append("现价仅一家可得、未交叉核对（实时区首轮源集天然如此，不是这一次没连上）")

    # "当日有没有数据"的**唯一**判据＝分时序列归属日期 == 北京今日（PLAN.md:172）。
    # 上游在休市/隔夜会返回上一交易日的**完整**序列，"有没有返回蜡烛"不能当判据（09-27 周日实测）。
    date_is_today: bool | None = (
        None if "intraday" not in wanted else bool(intraday_date) and intraday_date == today
    )
    if intraday_date and date_is_today is False:
        notes.append(
            f"分时序列归属日 {intraday_date} ≠ 北京今日 {today}：上游返回的是上一交易日整段序列，"
            "按判据①本区域不显示（R16：上一交易日数据必须显式标注）"
        )
    for kind, label in (("price", "现价"), ("intraday", "分时")):
        if kind in wanted and not legs[kind]:
            key = type_ if kind == "price" else f"{type_}.{kind}"
            notes.append(f"本轮未接入{label}：{UNWIRED_REASON.get(key, UNWIRED_REASON.get(type_, ''))}")

    price = prices[0] if prices else None
    has_today_data: bool | None = (
        None
        if date_is_today is None
        else price is not None and bool(candles) and date_is_today
    )
    # degraded＝**这一轮**真有问题（有腿失败／这一轮要的东西没拿到）。结构性缺口（某类未接入、
    # 现价只有一家）只写进 note，不进这一位——否则它永远为真，就等于没有。
    failed = [s for s in sources if not s["ok"]]
    degraded = bool(failed) or ("price" in wanted and price is None) or ("intraday" in wanted and not candles)
    points = [
        {
            "t": c["date"][11:],
            "price": c["close"],
            "volume": c["volume"],
        }
        for c in candles
    ]

    return {
        "type": type_,
        "code": code,
        "observedAt": beijing_now().strftime("%Y-%m-%dT%H:%M:%S"),
        "price": price,
        "intraday": (
            None
            if not candles
            else {
                "interval": "1m",
                "date": intraday_date,
                "bars": len(candles),
                "lastAt": candles[-1]["date"],
                "source": next((s["source"] for s in sources if s["kind"] == "intraday" and s["ok"]), None),
                "points": points,
            }
        ),
        "crossChecked": cross_checked,
        "verifyVerdict": verdict,
        "consensus": {
            "verdict": verdict,
            "diffPct": None if diff_pct is None else round(diff_pct, 3),
            "thresholdPct": CONSENSUS_THRESHOLD_PCT,
            "provisional": True,
            "basis": "阈值＝沿用 `/quote/verified` 的 0.5% 预设；1b 欠的三样之一（#64 甲 之后"
            "主链共识参考值仍未测到，"
            "「取比实测更宽的一档」落不了地）",
        },
        # 判据①的机器可读位：屏上不该为此多一句话，但"为什么这一整块不见了"必须读得出
        "parts": list(wanted),
        "hasTodayData": has_today_data,
        "intradayDateIsToday": date_is_today,
        "wired": bool(legs["price"]) or bool(legs["intraday"]),
        "sources": sources,
        "degraded": degraded,
        "note": "；".join(notes) if notes else None,
    }
