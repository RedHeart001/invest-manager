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

from ..utils.num import to_float
from .base import BaseProvider, ProviderError, register, register_list

CG_BASE = "https://api.coingecko.com/api/v3"
REQUEST_TIMEOUT = 20
MARKETS_TTL_SECONDS = 60
TOP_N = 250
MAX_KLINE_DAYS = 365
# CR4（2026-09-15 code review）：失败冷却——CoinGecko 当前网络不可达时，
# 不冷却会导致每个 crypto 请求都完整重试约 41s 占住 uvicorn 线程池 worker。
CG_FAIL_COOLDOWN = 300


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


def _unique_by_symbol(items: list[dict]) -> tuple[list[dict], list[str]]:
    """按 `symbol` 留**首次出现**那一条，返回 (去重后, 被丢掉的 symbol)。

    为什么必须去重（CR10-15，2026-11-08 实测）：CoinGecko 的 `/coins/markets` 按
    `market_cap_desc` 排，前 250 里**出现过同 symbol 的不同币**——实测 `USDF` 两条
    （第 49 位 Falcon USD、第 247 位 Aster USDF）。而 web 侧 `Product` 上有
    `@@unique([type, code])` ⇒ 整张名单**一行都写不进**（`Raw query failed. Code: 2067`），
    crypto 类长期 0 行。CR10-13 的 `dupCodes` 把那两枚点出来了，这里是把"留哪一条"落成代码：
    **留首次出现**＝留市值排名靠前的那一条（列表本身就按市值降序，两种说法同义）。

    为什么留首次而不是留末次：`_market_item()`（单发报价）本来就在 `for` 里
    `return` 第一个匹配 ⇒ 首次出现是**既有语义**。若这里改留末次，名单与报价会各说各话
    （实测 `get_quote` 给 Falcon USD、而当时 `get_quotes` 给 Aster USDF——后者是
    `out[symbol] = ...` 的覆盖副作用，见下面 `get_quotes`）。"同一 code 两处两个解"
    比少一行严重得多。

    空 symbol 一并跳过（上游脏行），与被去重的 symbol 分开记账。
    """
    seen: set[str] = set()
    out: list[dict] = []
    dropped: list[str] = []
    for item in items:
        symbol = str(item.get("symbol", "")).upper()
        if not symbol:
            continue
        if symbol in seen:
            dropped.append(symbol)
            continue
        seen.add(symbol)
        out.append(item)
    return out, dropped


class CoinGeckoProvider(BaseProvider):
    source = "coingecko"

    def __init__(self):
        self._markets: list[dict] | None = None
        self._markets_ts = 0.0
        self._markets_fail_ts = 0.0
        # CR10-15：上一轮去重丢掉了哪些 symbol（供 `list_products` 的 `note` 转述）。
        # 空表＝没丢过；每次 `_fetch_markets` 成功都整体覆写，不会累积陈旧读数。
        self._dropped: list[str] = []

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
        now = time.time()
        if self._markets is not None and now - self._markets_ts < MARKETS_TTL_SECONDS:
            return self._markets
        # CR4 失败负缓存：上次失败后的冷却期内直接抛降级错误，
        # 不再逐请求重试全程（不可达时每次约 41s，占住线程池 worker）。
        if now - self._markets_fail_ts < CG_FAIL_COOLDOWN:
            remain = int(CG_FAIL_COOLDOWN - (now - self._markets_fail_ts))
            raise ProviderError(f"coingecko cooling down after recent failure; retry in ~{remain}s")
        # CR5-1（2026-09-17 review）：失败路径此前**从不写入** `_markets_fail_ts`
        # （仅在 __init__ 与成功路径置 0），Unix 时间下守卫恒假 → 负缓存是死代码，
        # 不可达时每个 crypto 请求仍完整重试约 41s。此处与成功路径对称记账。
        try:
            markets = self._request(
                "/coins/markets",
                {
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": TOP_N,
                    "page": 1,
                    "price_change_percentage": "24h",
                },
            )
        except Exception:
            self._markets_fail_ts = time.time()
            raise
        # CR10-15：**去重放在缓存这一层**，而不是放在 `list_products` 里。
        # 三个消费方（`_market_item` 单发／`get_quotes` 批量／`list_products` 名单）
        # 读的都是这一份缓存 ⇒ 只在名单上去重会让"名单留 Falcon USD、批量报价给
        # Aster USDF"各行其是（那正是 2026-11-08 实测到的既有缺陷：`get_quotes`
        # 原先用 `out[symbol] = …` 逐条覆盖，同一个 symbol 后者赢）。一处去重＝三处同解。
        markets, self._dropped = _unique_by_symbol(markets or [])
        self._markets = markets
        self._markets_ts = time.time()
        self._markets_fail_ts = 0.0
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
            # C21/CR4：数值统一 to_float，过滤非有限值直出
            "price": to_float(item.get("current_price")),
            "change": None,
            "changePct": to_float(item.get("price_change_percentage_24h")),
            "high": to_float(item.get("high_24h")),
            "low": to_float(item.get("low_24h")),
            "marketCap": to_float(item.get("market_cap")),
            "marketCapRank": to_float(item.get("market_cap_rank")),
            "volume": to_float(item.get("total_volume")),
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
            # C21/CR4：防御式转换——非有限值（NaN/Inf 字面量可被 Python json 解析）视为缺失跳过
            p = to_float(price)
            if p is None:
                continue
            date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            candles.append(
                {
                    "date": date,
                    "open": p,
                    "high": p,
                    "low": p,
                    "close": p,
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
            # CR10-15：`symbol not in out` ＝**首次出现优先**，与 `_market_item`（单发报价）
            # 和 `list_products`（名单）三处同解。缓存层已经去过重，这里再判一次是有意的
            # 冗余：万一哪天有人把那层去重摘掉，批量报价也不会悄悄换成另一枚币
            # （2026-11-08 实测过的既有缺陷：这里原先是裸覆盖，USDF 交出 Aster USDF，
            # 而同一时刻 `/quote` 交出 Falcon USD）。
            if symbol in want and symbol not in out:
                out[symbol] = {
                    "type": "crypto",
                    "code": symbol,
                    "name": str(item.get("name", "")),
                    "price": to_float(item.get("current_price")),
                    "changePct": to_float(item.get("price_change_percentage_24h")),
                    "source": self.source,
                }
        return out

    def list_products(self, type_: str) -> list[dict] | tuple[list[dict], dict]:
        """CR10-15：去重后可能是裸 list（没丢过）或 `(items, meta)`（丢过 ⇒ 带 note）。

        两种形状 `list_products_with_meta` 都认（`base.py:115` 按 tuple 分派），
        与 `akshare_provider.list_products`／`hk_provider.list_products` 同一写法。

        为什么要带 meta：去重不是零信息量的动作。上游 250 条里有一对同 symbol 的币，
        我们只留了前一条 ⇒ **送去落库的是 249 条**。这份差异必须说得出是"我们丢了一条"
        而不是"上游只给了 249 条"，否则下一次看到 `count=249` 只能靠猜。

        ⚠️ 刻意**不**声明 `degraded`：那个键在账上的语义是"这批不是主源那批／上游劣化"
        （R16、CR9-31），而 CoinGecko 完全正常、一条都没少给——丢的那条是 web 侧
        `Product.@@unique([type,code])` 强制的。挂 `degraded` 会让 `sync.ts:321` 每晚
        拼一句"list degraded source=coingecko"上屏，那是**撒谎**（把我们的唯一键
        说成上游降级）。代价：`sync.ts` 只在 degraded 时才转述 note ⇒ 这句 note 的
        读者是直接看 `/products` 的人与 MCP 的 `list_products`（`**meta` 原样透传），
        同步回执里读不到它；同步侧能读到的是 `count=249 < 250` 这个事实本身。
        """
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
        if not self._dropped:
            return products
        uniq = sorted(set(self._dropped))
        return products, {
            "note": (
                f"上游 {TOP_N} 条里 {len(uniq)} 个 symbol 重复（{', '.join(uniq)}）"
                f"⇒ 按首次出现（市值靠前）留一条、丢 {len(self._dropped)} 条，"
                f"本次 {len(products)} 条。丢的那几条不是上游缺数据，是本侧 "
                f"Product 的 (type,code) 唯一键装不下两个同码币种"
            ),
        }


_crypto = CoinGeckoProvider()
register(["crypto"], _crypto)  # P2：行情/K线注册（此前仅列表）
register_list(["crypto"], _crypto)
