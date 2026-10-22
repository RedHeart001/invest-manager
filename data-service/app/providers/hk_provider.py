"""港股 provider（G6 / 批次 D + 备源补强）。

背景：`hk`（港股）此前只在 schema 类型注释、路由白名单与前端类型标签里出现，
data-service **没有任何 provider 注册 hk** → 对 type=hk 调 /quote、/kline 一律 400/502，
属"声明了但没做"的半成品类型。

实现方式：**直连东财接口**（`secid=116.<code>`），不套用 akshare 的 `stock_hk_*` 封装——
理由（2026-09-20 实测）：akshare 的 `stock_hk_spot_em` **硬编码单一 CDN 节点 `72.push2`**，
在该网络下被 `RemoteDisconnected` 拒绝，而同族其它节点（`push2delay`、`7.push2`）返回 200
真实数据。复用 akshare 封装会绕过本项目已有的**多 host 降级**能力。

**接口分工（2026-09-20 实测修正，不得混淆）**：
- 单股行情 → `/api/qt/stock/get`（1 次请求，快）
- 批量行情 → `/api/qt/ulist.np/get`（1 次请求，快）
- 产品列表 → `/api/qt/clist/get` **必须分页**（服务端忽略大分页，固定 100 条/页，
  港股约 4700 只 → 约 48 页；**仅在每日同步时调用**，绝不可用在行情路径上，
  否则单次查询耗时数分钟）

**为什么必须分开**：早期版本让 `get_quote` 复用列表快照，导致查询单个港股
需拉取全量 4700 条（约 4 分钟）——属设计缺陷，已修正。

对齐既有约定：
- 走源族限速器 `_em_request` + 看门狗（R15 / C7，与 A 股同一条东财额度）
- 多 host 按序降级
- 字段映射到与 A 股相同的内部 schema（复用 `to_float`）
- 失败抛 `ProviderError` → 上层显式降级（R10），不静默返回空

**列表这一支自 CR10-5 起有第二腿**（主人 10-22 的选型字＝「把 PLAN.md 选型字补上」）：东财
`clist/get` 全部 host 失败／首页为空／映射后 0 行 ⇒ 换新浪 `getHKStockData`（`node=qbgg_hk`），
按 CR9-31 以 `(items, {"source": "sina-hk-spot", "degraded": True, ...})` 显式声明出网源。
**它仍不走 akshare 的 `stock_hk_spot`**——那个封装打的确实是新浪域名，但它本体的
`for page in range(1, 100)` 会把翻页预算交到第三方手里；本文件自己翻、自己停在调用侧预算内
（见 `HK_SINA_SOFT_BUDGET_S`）。行情/K 线两支撑照旧只有东财一条腿，**降级只发生在列表**。
"""

from __future__ import annotations

import json
import logging
import time

import requests

from ..utils.num import to_float as _num
from .base import BaseProvider, ProviderError, ProviderNotSupported, register, register_list

log = logging.getLogger("hk")

REQUEST_TIMEOUT = 15

# 港股行情/列表 CDN 节点：按序降级
# 实测（2026-09-20）：72.push2（akshare 硬编码节点）不可达；push2delay / 7.push2 可用
HK_SPOT_HOSTS = [
    "https://push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
    "https://7.push2.eastmoney.com",
    "https://72.push2.eastmoney.com",
]

# 港股 K 线 CDN 节点
HK_HIST_HOSTS = [
    "https://push2his.eastmoney.com",
    "https://33.push2his.eastmoney.com",
    "https://63.push2his.eastmoney.com",
]

# 港股全市场过滤（东财 quote 首页口径，与 akshare stock_hk_spot_em 一致）
HK_MARKET_FILTER = "m:128 t:3,m:128 t:4,m:128 t:1,m:128 t:2"
# 列表字段：f12=代码 f14=名称 f2=最新价 f3=涨跌幅 f4=涨跌额 f15=最高 f16=最低 f17=今开 f18=昨收 f5=成交量 f6=成交额
HK_LIST_FIELDS = "f12,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
# 单股行情字段（与 akshare_provider.EM_QUOTE_FIELDS 同口径）
HK_QUOTE_FIELDS = "f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f117,f162,f164,f167,f168,f169,f170,f86"

# ---------- 港股列表的降级腿（CR10-5，主人 10-22 的选型字＝「把 PLAN.md 选型字补上」） ----------
# 上游＝新浪 `Market_Center.getHKStockData`（`node=qbgg_hk`）。10-21 23:5x 探针实测（3 发）：
# HTTP 200·**每页硬顶 60 行**（`num=100` 与 `num=1000` 返回字节数逐字相同 ⇒ 服务端无视 `num`）·
# `page=2` 能翻（00073–00139，与 page=1 不同批）⇒ 全量 ≈4,700÷60 ≈ **79 页**。
# 响应里**没有 total 字段**，4,700 是东财那一侧的读数（外推），所以下面那枚上限按"页"而不是按"条"定。
HK_SINA_LIST_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHKStockData"
)
HK_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn/stock/hkstock/",  # 缺 Referer 那一形按新浪惯例易被拒
}
HK_SINA_PAGE_ROWS = 60  # 服务端上限；写大无用（实测无视 num），只是别让请求里出现假承诺
HK_SINA_PAGE_CEILING = 90  # ≈4,700÷60 的算术上限＋余量；D3／CR7-13 同形：不许无上限捶源
HK_SINA_PAGE_INTERVAL_S = 0.5  # 页间自睡（`sina-us-category-list` 同形；整趟只 1 枚逻辑令牌）
# **调用侧预算（10-22 现查更正）**：web 夜间同步那条路打 `/products` 的真实预算是 **600s**
# （`web/lib/sync.ts` 里 `dsGet("/products", { type }, 600_000)`；此前账上写成"`sync.ts:283`
# 的 120s"是指错了对象——那里是 Prisma `$transaction` 的 timeout，不是 HTTP 预算）。
# 另有两枚 120s 不在这条路上：`MCP_LIST_TIMEOUT_S` 只管 MCP 工具 `list_products`，
# ds 的 `/products` HTTP 路由不走它；它已随本次一并抬到 450s，避免"外层 120s 先放弃、
# 内层线程仍在翻页"那一形（`utils/timeout.py` 的 `run_with_timeout` 杀不掉线程）。
# 探针实测新浪单页 ≈1.3s ⇒ 79 页 ≈ 142–182s：soft budget 300s 足够跑到 `exhausted`，
# 看门狗 420s 兜底，两者都 < 客户端 600s，也 < MCP 那枚 450s。
HK_SINA_SOFT_BUDGET_S = 300.0
HK_SINA_WHOLE_TIMEOUT_S = 420.0


class HkProvider(BaseProvider):
    """港股 provider（东财直连 + 多 host 降级）。"""

    source = "akshare-hk"

    # ---------- 多 host 请求（限速器内只计一次，C29 口径） ----------

    def _em_json(self, hosts: list[str], path: str, params: dict) -> dict:
        from .akshare_provider import _em_request

        def _fetch() -> dict:
            last_err: object = None
            for _round in range(2):
                for host in hosts:
                    try:
                        r = requests.get(
                            f"{host}{path}",
                            params=params,
                            timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"},
                        )
                        r.raise_for_status()
                        return r.json()
                    except Exception as e:  # noqa: BLE001 换 host 重试
                        last_err = e
            raise ProviderError(f"hk eastmoney request failed on all hosts: {last_err}")

        return _em_request(_fetch)

    # ---------- 单股 / 批量行情（快路径，1 次请求） ----------

    @staticmethod
    def _secid(code: str) -> str:
        return f"116.{code.strip()}"

    @staticmethod
    def _quote_from_item(item: dict, code: str) -> dict:
        """东财行情字段 → 统一 schema（f 字段与 A 股同口径）。"""
        return {
            "type": "hk",
            "code": str(item.get("f57") or code),
            "name": str(item.get("f58", "")).strip(),
            "price": _num(item.get("f43")),
            "change": _num(item.get("f169")),
            "changePct": _num(item.get("f170")),
            "open": _num(item.get("f46")),
            "high": _num(item.get("f44")),
            "low": _num(item.get("f45")),
            "prevClose": _num(item.get("f60")),
            "volume": _num(item.get("f47")),
            "amount": _num(item.get("f48")),
            "marketCap": _num(item.get("f116")),
            "floatCap": _num(item.get("f117")),
            "peTtm": _num(item.get("f164")),
            "pb": _num(item.get("f167")),
            "turnover": _num(item.get("f168")),
            "currency": "HKD",
            "source": "akshare-hk",
        }

    def get_quote(self, type_: str, code: str) -> dict:
        if type_ != "hk":
            raise ProviderNotSupported(f"hk provider serves hk only, got {type_}")
        payload = self._em_json(
            HK_SPOT_HOSTS,
            "/api/qt/stock/get",
            {
                "fltt": "2",
                "invt": "2",
                "fields": HK_QUOTE_FIELDS,
                "secid": self._secid(code),
            },
        )
        data = payload.get("data")
        if not data:
            raise ProviderError(f"hk code not found: {code}")
        q = self._quote_from_item(data, code)
        if q["price"] is None:
            raise ProviderError(f"hk quote has no price: {code}")
        return q

    def touches_eastmoney(self, type_: str, codes: list[str]) -> bool:
        """港股批量行情自己打 `HK_SPOT_HOSTS` 上的 `/api/qt/ulist.np/get`＝东财族
        （下面 `get_quotes` 就是那次请求），所以这里恒 `True`（丙／CR9-67）。
        与 A 股共用同一个 `eastmoney` 令牌桶正是批间隔必须按"真打东财"来睡的依据。"""
        return bool(codes)

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        if type_ != "hk":
            raise ProviderNotSupported(f"hk provider serves hk only, got {type_}")
        want = [c.strip() for c in codes if c and c.strip()]
        if not want:
            return {}
        payload = self._em_json(
            HK_SPOT_HOSTS,
            "/api/qt/ulist.np/get",
            {
                "fltt": "2",
                "invt": "2",
                "fields": "f12,f14,f2,f3,f4,f15,f16,f17,f18",
                "secids": ",".join(self._secid(c) for c in want),
            },
        )
        diff = ((payload.get("data") or {}).get("diff")) or []
        out: dict[str, dict] = {}
        for item in diff:
            code = str(item.get("f12", "")).strip()
            if not code:
                continue
            out[code] = {
                "type": "hk",
                "code": code,
                "name": str(item.get("f14", "")).strip(),
                "price": _num(item.get("f2")),
                "changePct": _num(item.get("f3")),
                "change": _num(item.get("f4")),
                "high": _num(item.get("f15")),
                "low": _num(item.get("f16")),
                "open": _num(item.get("f17")),
                "prevClose": _num(item.get("f18")),
                "currency": "HKD",
                "source": "akshare-hk",
            }
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
        if type_ != "hk":
            raise ProviderNotSupported(f"hk provider serves hk only, got {type_}")
        if interval != "1d":
            raise ProviderNotSupported("hk minute kline not implemented")

        payload = self._em_json(
            HK_HIST_HOSTS,
            "/api/qt/stock/kline/get",
            {
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "klt": "101",
                "fqt": "1",  # 前复权（与 A 股同口径）
                "secid": self._secid(code),
                "beg": start or "19700101",
                "end": end or "22220101",
            },
        )
        klines = ((payload.get("data") or {}).get("klines")) or []
        if not klines:
            raise ProviderError(
                f"hk kline empty: {code}（可能代码不存在/已退市，或该 CDN 节点返回空）"
            )

        # 行格式：日期,开,收,高,低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
        candles = []
        for item in klines:
            f = str(item).split(",")
            if len(f) < 7:
                continue
            o, c, h, low_ = _num(f[1]), _num(f[2]), _num(f[3]), _num(f[4])
            # 与其它 provider 同契约：任一 OHLC 缺失即跳过（KlineDaily 列为 NOT NULL）
            if None in (o, c, h, low_):
                continue
            candles.append(
                {
                    "date": f[0],
                    "open": o,
                    "high": h,
                    "low": low_,
                    "close": c,
                    "volume": _num(f[5]),
                }
            )
        if not candles:
            raise ProviderError(f"hk kline unparsable: {code}")
        return {
            "type": "hk",
            "code": code,
            "interval": "1d",
            "source": self.source,
            "candles": candles,
        }

    # ---------- 产品列表（慢路径：分页；**仅供每日同步**） ----------

    def list_products(self, type_: str) -> list[dict] | tuple[list[dict], dict]:
        """全量港股列表：东财 `clist/get` 为主源，**只在它整条不可用之后**降级到新浪。

        **性能警示**：东财港股 `clist/get` 服务端忽略大分页参数，固定 100 条/页，
        港股约 4700 只 → 约 48 次请求（受源族限速，实测约 4 分钟）。
        故本方法**只应在每日同步任务中调用**，不得用于行情路径。

        降级那一支（CR10-5）＝返回 `(items, meta)` 按 CR9-31 显式声明出网源；主源成功时
        **仍返回裸 `list[dict]`**（`test_g6_hk` 那三枚断言钉的就是这个形状，不改既有取舍）。
        """
        if type_ != "hk":
            raise ProviderError(f"unsupported list type: {type_}")
        try:
            return self._list_products_em()
        except ProviderError as em_err:
            # 只在这一枚出口上换源：`_em_json` 的"全部 host 失败"与"首页 diff 为空"都归到这里，
            # 两条都是"东财这一夜答不出"，不是"港股没有 4700 只"。
            log.warning("hk list primary (em clist) failed: %s ⇒ 降级至新浪全量列表", em_err)
            return self._list_products_sina(f"{type(em_err).__name__}: {em_err}")

    def _list_products_em(self) -> list[dict]:
        """东财主源那一支（原 `list_products` 本体，一字未改语义）。"""
        from .akshare_provider import _pinyin_pair

        base_params = {
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f12",
            "fs": HK_MARKET_FILTER,
            "fields": "f12,f14",  # 列表只需代码+名称
        }
        payload = self._em_json(
            HK_SPOT_HOSTS, "/api/qt/clist/get", {**base_params, "pn": "1", "pz": "10000"}
        )
        data = payload.get("data") or {}
        diff = data.get("diff") or []
        total = int(data.get("total") or 0)
        if not diff:
            raise ProviderError("hk list empty (all hosts)")

        if total and len(diff) < total:
            page_size = len(diff) or 100
            pages = (total + page_size - 1) // page_size
            # D3（CR7-13，2026-09-25）：分页上限——对照 akshare_provider 的
            # min(pages, 100)。上游 total 异常（被刷/接口变更）时若无上限，
            # range(2, pages+1) 会以每页一发东财请求长时间捶打源族（R15）。
            if pages > 100:
                log.warning("hk list pages=%d exceeds cap, truncating to 100", pages)
                pages = 100
            collected = {str(x.get("f12")): x for x in diff}
            for pn in range(2, pages + 1):
                page = self._em_json(
                    HK_SPOT_HOSTS,
                    "/api/qt/clist/get",
                    {**base_params, "pn": str(pn), "pz": str(page_size)},
                )
                for x in ((page.get("data") or {}).get("diff")) or []:
                    collected[str(x.get("f12"))] = x
            diff = list(collected.values())

        products: list[dict] = []
        for item in diff:
            code = str(item.get("f12", "")).strip()
            name = str(item.get("f14", "")).strip()
            if not code or not name:
                continue
            full, initials = _pinyin_pair(name)
            products.append(
                {
                    "type": "hk",
                    "code": code,
                    "name": name,
                    "pinyin": full,
                    "pinyinInitials": initials,
                    "exchange": "HK",
                    "tags": [],
                }
            )
        if not products:
            # 有行但一行都映射不出来＝上游换了字段名，与"整条不可用"同判：交给下一支，
            # 不许静默回 []（那会把"没到货"读成"港股到货 0 只"）。
            raise ProviderError(f"hk list parsed to 0 rows from {len(diff)} em rows")
        return products

    # ---------- 列表降级腿：新浪 `getHKStockData`（CR10-5） ----------

    def _sina_hk_page(self, page: int) -> list[dict]:
        """一发新浪港股列表页。**只在 `_ak_request` 的族闸与看门狗之内**被调用。"""
        r = requests.get(
            HK_SINA_LIST_URL,
            params={
                "page": str(page),
                "num": str(HK_SINA_PAGE_ROWS),
                "sort": "symbol",
                "asc": "1",
                "node": "qbgg_hk",
                "_s_r_a": "init",
            },
            headers=HK_SINA_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        rows = json.loads(r.text)  # 探针实测：顶层就是数组，不套 data/result/list
        return rows if isinstance(rows, list) else []

    def _list_products_sina(self, em_reason: str) -> tuple[list[dict], dict]:
        """东财答不出时的第二腿。整趟翻页包在**一枚** `_ak_request` 里＝
        `sina-us-category-list` 同形（CR9-97 口径：令牌按逻辑请求计 1 次，页间自己睡）⇒
        **`granted` 只 +1，不等于只发了 1 发 HTTP**（页码数见返回的 note）。
        记账仍打 `akshare-obs` 族（`observe("sina.hk-list")`），**不占东财桶**。
        """
        from .akshare_provider import _ak_request, _pinyin_pair

        collected: dict[str, str] = {}
        t0 = time.monotonic()

        def _sweep() -> tuple[str, int]:
            """翻页，返回（停止原因, 实际页数）。"""
            stalled = 0
            for page in range(1, HK_SINA_PAGE_CEILING + 1):
                rows = self._sina_hk_page(page)
                if not rows:
                    return "exhausted", page
                before = len(collected)
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    code = str(item.get("symbol", "")).strip()
                    name = str(item.get("name", "")).strip()
                    if code and name:
                        collected.setdefault(code, name)
                if len(collected) == before:
                    # 拿回一批行却一个新代码都没有＝它在重复同一页；再睡再打就是白花钱
                    stalled += 1
                    if stalled >= 2:
                        return "stalled", page
                else:
                    stalled = 0
                if time.monotonic() - t0 >= HK_SINA_SOFT_BUDGET_S:
                    return "budget", page  # **主动停在调用侧 120s 预算之内**，别让客户端掐掉
                time.sleep(HK_SINA_PAGE_INTERVAL_S)
            return "ceiling", HK_SINA_PAGE_CEILING

        try:
            stop, pages = _ak_request(_sweep, HK_SINA_WHOLE_TIMEOUT_S, "sina.hk-list")
        except Exception as sina_err:  # noqa: BLE001 两支都失败＝显式降级，不静默返回空
            raise ProviderError(
                f"hk list unavailable from both sources: eastmoney（{em_reason}）；"
                f"sina（{type(sina_err).__name__}: {sina_err}）"
            ) from sina_err

        products: list[dict] = []
        for code, name in collected.items():
            full, initials = _pinyin_pair(name)
            products.append(
                {
                    "type": "hk",
                    "code": code,
                    "name": name,
                    "pinyin": full,
                    "pinyinInitials": initials,
                    "exchange": "HK",
                    "tags": [],
                }
            )
        if not products:
            raise ProviderError(
                f"hk list empty from both sources: eastmoney（{em_reason}）；"
                f"sina 翻页 {pages} 页后停止（{stop}）、0 行"
            )
        elapsed = round(time.monotonic() - t0, 1)
        complete = stop == "exhausted"
        log.info("hk list degraded to sina: %d rows, %d pages, stop=%s, %.1fs", len(products), pages, stop, elapsed)
        return products, {
            "source": "sina-hk-spot",
            "degraded": True,
            # #35／CR9-63 那两件事分开：`degraded`＝"这批不是东财那批"，`intentionalSubset`＝
            # "缺口是我们自己的预算造成的、不是上游又劣化了一档"⇒ web 的降级缩水闸据此放行。
            # 翻页取尽（`exhausted`）时**不许**声明子集。
            "intentionalSubset": not complete,
            "note": (
                f"东财港股列表不可用（{em_reason}），已降级至新浪 getHKStockData（node=qbgg_hk）："
                f"本次 {len(products)} 只、翻页 {pages} 页后{'取尽' if complete else f'主动停（{stop}）'}、"
                f"耗时 {elapsed}s（每页硬顶 {HK_SINA_PAGE_ROWS} 行——服务端无视 `num`；soft budget "
                f"{HK_SINA_SOFT_BUDGET_S}s ⇔ 调用侧 120s）；新浪的名称列是短名（实测 00001＝「长和」）、"
                "与东财 `f14` 不同形 ⇒ 换源那夜会有整批名字被改写；响应里没有 total ⇒ 覆盖面无法与上游盘子对账"
            ),
        }


def _register() -> None:
    provider = HkProvider()
    register(["hk"], provider)
    register_list(["hk"], provider)


_register()
