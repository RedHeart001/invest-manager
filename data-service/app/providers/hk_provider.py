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
"""

from __future__ import annotations

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

    def list_products(self, type_: str) -> list[dict]:
        """全量港股列表。

        **性能警示**：东财港股 `clist/get` 服务端忽略大分页参数，固定 100 条/页，
        港股约 4700 只 → 约 48 次请求（受源族限速，实测约 4 分钟）。
        故本方法**只应在每日同步任务中调用**，不得用于行情路径。
        """
        if type_ != "hk":
            raise ProviderError(f"unsupported list type: {type_}")
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
        return products


def _register() -> None:
    provider = HkProvider()
    register(["hk"], provider)
    register_list(["hk"], provider)


_register()
