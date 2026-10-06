"""CR9-67（丙）离线单测：**逐批**问「这一批打不打东财」，而不是按类型名猜。

背景（10-06 10:2x 直读 `web/prisma/dev.db`，`mode=ro`、零出网）＝`fund` 28,013 行按
`code asc` 切 100 一批＝**281 批**，其中**只有 31 批**含场内代码（`_is_exchange_traded_fund`
的前缀集 `15/16/18/50/51/52/53/56/58`，共 2,829 只），而 web 的刷新腿此前问的是
「**这一类**属不属于东财族」（`market-snapshot.ts` 的 `EM_SNAPSHOT_TYPES`）⇒ 每轮为 fund
睡 280 个 5 秒，其中 **249 个（1,245s）付给的是只走场外净值的批次**——那条路走
`_fund_nav_table`（30 分钟全市场缓存）、按 CR9-54 挂在**只观测不限流**的 `akshare-obs` 上，
不占 `eastmoney` 桶，所以那 5 秒保护的是空气。

修法（主人的字＝丙）＝**判据住在路由它的那个人嘴里**：
- `BaseProvider.touches_eastmoney()` 默认 `False`（腾讯／新浪／新浪转债／yfinance／CoinGecko
  都不打东财）；
- `AkshareProvider` 覆写＝`fund` 时看前缀、其余类型 `True`（它的 `get_quotes` 除 fund 之外
  一律 `_em_ulist`）——判据与路由住在**同一个类**，两张表分开放迟早各说各话；
- `HkProvider` 覆写 `True`（`get_quotes` 自己打 `HK_SPOT_HOSTS` 上的 `/api/qt/ulist.np/get`，
  与 A 股共用同一个 `eastmoney` 令牌桶）；
- `/quotes` 响应加 `usesEastmoney` 布尔键，按**主源**路由算（降级到哪家不改变"这一批
  向桶要过令牌"，而批间隔保护的是**桶**不是结果）。

⚠️ 本刀**不改**任何秒数：`EM_BATCH_DELAY_MS = 5000` 等于桶自己的放行速率（CR9-9 的对照
实验钉着），批次大小与 2,400s 预算也原样。

运行方式（无需任何服务在跑，零出网）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr9_67_em_batch_marker.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import app.main as m  # noqa: E402
from app.providers import get_provider_chain  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# 场外／场内的样本代码：`110022`（易方达消费行业）与 `000001`（华夏成长）都是场外净值，
# `510300`（沪深 300ETF）是场内——这一对就是丙的那道分水岭。
OTC_ONLY = ["000001", "110022", "007882"]
MIXED = ["000001", "510300"]
EXCHANGE_ONLY = ["510300", "159915"]


def test_fund_is_decided_per_batch() -> None:
    """fund 的标记必须是**逐批**算的：整类一律 `True` 就是丙之前那个错。"""
    ak = get_provider_chain("fund")[0]
    check("①：一批全是场外净值 ⇒ `False`（这条路不占东财桶，睡 5 秒保护的是空气）",
          ak.touches_eastmoney("fund", OTC_ONLY) is False,
          str(ak.touches_eastmoney("fund", OTC_ONLY)))
    check("🔁 ①：同类型换一批、掺一只 510300 ⇒ `True`（判据是「这批有没有」，不是「这类算不算」）",
          ak.touches_eastmoney("fund", MIXED) is True,
          str(ak.touches_eastmoney("fund", MIXED)))
    check("①：全是场内 ⇒ `True`", ak.touches_eastmoney("fund", EXCHANGE_ONLY) is True)
    check("①：`codes` 为空 ⇒ `False`（「没东西可打」不许读成「要打」）",
          ak.touches_eastmoney("fund", []) is False,
          str(ak.touches_eastmoney("fund", [])))


def test_other_types_declare_their_own_channel() -> None:
    """其余类型的答复必须与各家 `get_quotes` 的真实出网通道一致。"""
    ak = get_provider_chain("stock")[0]
    check("①：stock／bond 一批 ⇒ `True`（akshare 的 `get_quotes` 除 fund 之外一律 `_em_ulist`）",
          ak.touches_eastmoney("stock", ["600519"]) is True
          and ak.touches_eastmoney("bond", ["113050"]) is True)
    hk = get_provider_chain("hk")[0]
    check("①：hk 的主源自己打 `/api/qt/ulist.np/get` ⇒ `True`（与 A 股同一个 `eastmoney` 桶）",
          hk.touches_eastmoney("hk", ["00700"]) is True, hk.source)
    check("🔁 ①：非东财族的主源（coingecko／yfinance）⇒ `False`（基类默认就是答复，不是漏写）",
          get_provider_chain("crypto")[0].touches_eastmoney("crypto", ["BTC"]) is False
          and get_provider_chain("us")[0].touches_eastmoney("us", ["AAPL"]) is False)
    backups = {p.source: p.touches_eastmoney("fund", EXCHANGE_ONLY) for p in get_provider_chain("fund")}
    check("①：fund 链上的备源位（腾讯／新浪）也报 `False`——降级那一家的批次不值得按东财节奏睡",
          all(v is False for k, v in backups.items() if k != "akshare"), str(backups))


def test_quotes_endpoint_carries_the_flag() -> None:
    """`/quotes` 把这个事实**说给调用方**——否则 web 只能继续自己猜一张表。

    `_chain_call` 在这里被换掉：本用例要验的是端点的**响应契约**，取数那一跳早已由
    上面两组用例覆盖，再跑一次就是拿断言去烧上游额度（R16 之外的另一条纪律）。
    """
    orig = m._chain_call
    m._chain_call = lambda type_, fn: {"quotes": {}, "note": None}
    try:
        otc = m.quotes(type="fund", codes=",".join(OTC_ONLY))
        em = m.quotes(type="fund", codes=",".join(MIXED))
        stock = m.quotes(type="stock", codes="600519")
        check("②：响应里有布尔键 `usesEastmoney`（全场外那一批 ⇒ `False`）",
              otc.get("usesEastmoney") is False, str(otc))
        check("🔁 ②：同类型、含场内的那一批 ⇒ `True`（这个键是逐批算的，不是逐类的常数）",
              em.get("usesEastmoney") is True, str(em))
        check("②：stock ⇒ `True`（丙之后 web 侧那张表只剩回落用途）",
              stock.get("usesEastmoney") is True, str(stock))
        check("②：既有的三键（`type`／`quotes`／`note`）一个都不少——加键不是换契约",
              set(otc) >= {"type", "quotes", "note", "usesEastmoney"} and otc["type"] == "fund",
              str(sorted(otc)))
    finally:
        m._chain_call = orig


if __name__ == "__main__":
    test_fund_is_decided_per_batch()
    test_other_types_declare_their_own_channel()
    test_quotes_endpoint_carries_the_flag()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
