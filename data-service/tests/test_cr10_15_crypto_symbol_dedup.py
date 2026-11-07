"""CR10-15 离线单测：CoinGecko 名单里同 symbol 的多枚币——**留首次出现**（市值靠前）。

背景（2026-11-08 实测，零推测）：
    给 `data-service/.env` 补上 `HTTPS_PROXY` 之后 CoinGecko 立刻可达
    （`/products?type=crypto` → `count=250 source=coingecko`，3.1s），
    但同步腿当场撞唯一键：

        {"type":"crypto",
         "error":"Raw query failed. Code: `2067`. Message: `UNIQUE constraint failed: Product.type, Product.code`",
         "dupCodes":["crypto:USDF"],"tookMs":67}

    上游前 250 里 `USDF` 出现两次：第 49 位 `Falcon USD`、第 247 位 `Aster USDF`。
    web 的 `Product` 有 `@@unique([type, code])` ⇒ 整张名单**一行都写不进**，
    crypto 类长期 0 行。CR10-13 的 `dupCodes` 只**点名**（那一枚已经兑现，正是它交出
    `crypto:USDF`），"同一 (type,code) 该留哪一条"这句字 11-08 由主人拍定＝**留首次出现**。

判据形状（C34 的成对＋牙齿）：
  ① 正向＝同 symbol 两条只留前一条，且**丢的是后一条**（不是随手留下哪条）；
  ② 🔁 反向＝全唯一时一条都不许丢（否则"去重"会变成静默缩小）；
  ③ 🔁 会红的样本＝把 `_unique_by_symbol` 换成"留末次"的实现，本套必须红——
     这一枚才是判别"首次"与"末次"的那把尺；
  ④ **三条消费路径同解**（本轮最值钱的一条）：`_market_item`／`get_quotes`／
     `list_products` 对同一个 USDF 必须指向**同一个 name**。实测过它们的旧分歧：
     `get_quote` 给 Falcon USD 而 `get_quotes` 给 Aster USDF（`out[symbol]=…` 覆盖）；
  ⑤ 名单带 `note` 说清"丢了几条、为什么"，但**不许**带 `degraded`
     （那键在账上的语义是上游劣化，挂它等于把我们的唯一键说成上游的锅）；
  ⑥ 空 symbol 的脏行被跳过，且与"被去重的 symbol"分开记账。

运行方式（无需任何服务在跑，零出网）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr10_15_crypto_symbol_dedup.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import app.providers.crypto_provider as cp  # noqa: E402
from app.providers.base import list_products_with_meta  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# 现网形状的最小复刻（顺序即 `market_cap_desc` 的返回序：Falcon USD 先、Aster USDF 后）
MARKETS = [
    {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": 100.0, "market_cap_rank": 1},
    {"id": "falcon-usd", "symbol": "usdf", "name": "Falcon USD", "current_price": 0.9945, "market_cap_rank": 49},
    {"id": "tether", "symbol": "usdt", "name": "Tether", "current_price": 1.0, "market_cap_rank": 3},
    {"id": "aster-usdf", "symbol": "usdf", "name": "Aster USDF", "current_price": 0.9974, "market_cap_rank": 247},
    # 脏行：上游偶发 symbol 为空（不计入"被去重"，也不许让整张名单崩）
    {"id": "no-symbol", "symbol": "", "name": "Broken Row", "current_price": 1.0},
]


def _provider(markets: list[dict] | None = None) -> cp.CoinGeckoProvider:
    """把出网那一跳换成给定载荷（零出网），其余逻辑一字不动。"""
    p = cp.CoinGeckoProvider()
    rows = MARKETS if markets is None else markets
    p._request = lambda path, params: [dict(r) for r in rows]  # type: ignore[assignment]
    return p


# ---------- ① 纯函数：留首次出现 ----------


def test_unique_by_symbol_keeps_first() -> None:
    uniq, dropped = cp._unique_by_symbol([dict(r) for r in MARKETS])
    symbols = [r["symbol"] for r in uniq]
    check("① 同 symbol 只留一条", symbols.count("usdf") == 1, str(symbols))
    check("① 留下的是**首次出现**那条（Falcon USD），不是末次（Aster USDF）",
          [r["name"] for r in uniq if r["symbol"] == "usdf"] == ["Falcon USD"],
          str([r["name"] for r in uniq if r["symbol"] == "usdf"]))
    check("① 被丢的 symbol 如实记账", dropped == ["USDF"], str(dropped))
    check("① 顺序不变（去重不许重排——名单的序就是市值序）",
          symbols == ["btc", "usdf", "usdt"], str(symbols))
    check("⑥ 空 symbol 的脏行被跳过、且不计入 dropped",
          "no-symbol" not in [r["id"] for r in uniq] and "USDF" in dropped and "" not in dropped,
          f"uniq_ids={[r['id'] for r in uniq]} dropped={dropped}")


def test_unique_by_symbol_no_rows_dropped_when_unique() -> None:
    rows = [{"symbol": "btc", "name": "Bitcoin"}, {"symbol": "eth", "name": "Ethereum"}]
    uniq, dropped = cp._unique_by_symbol(rows)
    check("② 🔁 全唯一 ⇒ 一条都不丢、dropped 为空（去重不许变成静默缩小）",
          len(uniq) == 2 and dropped == [], f"n={len(uniq)} dropped={dropped}")


def test_teeth_last_wins_implementation_is_red() -> None:
    """③ 尺自己的牙齿：把口径换成"留末次"，下面两条断言必须同时翻假。

    不这么写的话，本套件对"首次 vs 末次"没有判别力——留哪条都能凑出一个只含一条的名单。
    """

    def _last_wins(items: list[dict]) -> tuple[list[dict], list[str]]:
        kept: dict[str, dict] = {}
        order: list[str] = []
        for item in items:
            s = str(item.get("symbol", "")).upper()
            if not s:
                continue
            if s not in kept:
                order.append(s)
            kept[s] = item  # ← 只有这一行的差别：后来者覆盖
        return [kept[s] for s in order], []

    uniq, _ = _last_wins([dict(r) for r in MARKETS])
    got = [r["name"] for r in uniq if str(r.get("symbol", "")).upper() == "USDF"]
    check("③ 🔁 牙齿：留末次的实现会交出 Aster USDF（证明上面那条断言不是白给的）",
          got == ["Aster USDF"], str(got))


# ---------- ④ 三条消费路径同解 ----------


def test_three_paths_agree() -> None:
    p = _provider()
    single = p.get_quote("crypto", "USDF")
    batch = p.get_quotes("crypto", ["USDF"]).get("USDF") or {}
    items, _meta = p.list_products("crypto")
    listed = [x for x in items if x["code"] == "USDF"]
    check("④ 单发报价 → Falcon USD", single.get("name") == "Falcon USD", str(single.get("name")))
    check("④ 批量报价 → Falcon USD（旧实现这里给 Aster USDF：`out[symbol]=…` 覆盖）",
          batch.get("name") == "Falcon USD", str(batch.get("name")))
    check("④ 名单 → 恰好一条 USDF 且是 Falcon USD",
          len(listed) == 1 and listed[0]["name"] == "Falcon USD", str(listed))
    check("④ 三条路径的 name 完全一致（同一 code 两处两个解比少一行严重得多）",
          single.get("name") == batch.get("name") == listed[0]["name"],
          f"{single.get('name')} / {batch.get('name')} / {listed[0]['name']}")
    check("④ 单发与批量的价格也一致（同一个币的两条腿不许各报一个价）",
          single.get("price") == batch.get("price") == 0.9945,
          f"{single.get('price')} / {batch.get('price')}")


def test_batch_is_first_wins_even_without_cache_dedup() -> None:
    """`get_quotes` 里的 `symbol not in out` 是**有意的冗余**：缓存层若被摘掉也要留首次。"""
    p = cp.CoinGeckoProvider()
    p._request = lambda path, params: [dict(r) for r in MARKETS]  # type: ignore[assignment]
    raw = p._request("/coins/markets", {})  # 绕过缓存层去重，直接喂重复行
    p._markets = raw
    p._markets_ts = 9e18  # 远未来 ⇒ TTL 判据恒真，不再回 `_fetch_markets`
    got = p.get_quotes("crypto", ["USDF"]).get("USDF") or {}
    check("④ 🔁 缓存层去重被摘掉时，批量报价仍留首次出现（冗余是故意的）",
          got.get("name") == "Falcon USD", str(got.get("name")))


# ---------- ⑤ 名单的 meta ----------


def test_list_meta_note_without_degraded() -> None:
    p = _provider()
    items, meta = list_products_with_meta(p, "crypto")
    check("⑤ 名单条数＝去重后的条数（250 → 少掉被丢的那条）",
          len(items) == 3, f"n={len(items)}")
    check("⑤ 丢过 ⇒ 带 note 说清丢了几条、为什么",
          "USDF" in (meta.get("note") or "") and "丢 1 条" in (meta.get("note") or ""),
          str(meta.get("note")))
    check("⑤ 出网源仍是 coingecko（去重不改来源声明）", meta.get("source") == "coingecko", str(meta.get("source")))
    check("⑤ **不许**带 degraded——那键的语义是上游劣化，我们的唯一键不是上游的锅",
          "degraded" not in meta, str(sorted(meta.keys())))
    check("⑤ 也不许借道 intentionalSubset（那是 #35/CR9-63 给「有意子集」留的键，用途不同）",
          "intentionalSubset" not in meta, str(sorted(meta.keys())))


def test_list_no_meta_when_nothing_dropped() -> None:
    p = _provider([
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": 1.0},
        {"id": "ethereum", "symbol": "eth", "name": "Ethereum", "current_price": 2.0},
    ])
    items, meta = list_products_with_meta(p, "crypto")
    check("⑤ 🔁 没丢过 ⇒ 返回裸 list 的旧形状（meta 里只有 source，不编一条 note）",
          len(items) == 2 and "note" not in meta, str(meta))


def test_cache_dedup_is_single_source_of_truth() -> None:
    """去重住在 `_fetch_markets`（缓存层）——三个消费方读同一份，不各去各的。"""
    p = _provider()
    check("去重后缓存里 USDF 只有一条",
          [str(r.get("symbol", "")).upper() for r in p._fetch_markets()].count("USDF") == 1,
          str([r.get("symbol") for r in p._fetch_markets()]))
    first = p._fetch_markets()
    first.append({"id": "x", "symbol": "NEW", "name": "外部篡改"})
    check("🔁 缓存命中时不再重新去重（TTL 内同一份对象；否则每发都白跑一遍）",
          p._fetch_markets() is first, "not same object")


if __name__ == "__main__":
    test_unique_by_symbol_keeps_first()
    test_unique_by_symbol_no_rows_dropped_when_unique()
    test_teeth_last_wins_implementation_is_red()
    test_three_paths_agree()
    test_batch_is_first_wins_even_without_cache_dedup()
    test_list_meta_note_without_degraded()
    test_list_no_meta_when_nothing_dropped()
    test_cache_dedup_is_single_source_of_truth()

    fails = [x for x in results if not x[1]]
    # 汇总行必须落在 gate.mjs 认得的两种形态之一（`===== N/M 通过 =====`
    # 或 `== 标题：N/M 通过 ==`）；写成别的形会让闸1 判「解析不出」＝红（10-22 踩过）。
    print(f"\n== CR10-15 crypto 同 symbol 去重：{len(results) - len(fails)}/{len(results)} 通过 ==")
    if fails:
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:200]}")
    sys.exit(1 if fails else 0)
