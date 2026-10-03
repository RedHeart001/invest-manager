"""CR9-59 离线单测：美股主数据列表（#32 甲＝新浪排行名单的**有界**前 N 页）。

背景（10-03 探针／10-04 落码实测，见 docs/FIX-LEDGER.md 的 #32 与 CR9-59 两行）：
`Product` 里 `us` 长期只有 1 行、`/product/us/AAPL` 404、搜索 0 结果，根因是
**美股从来没有列表 provider**（`register_list` 里根本没有 us）。甲的口径＝先把入口通了：
只取前排 N 页（≈300 只），**绝不打满 913 页**（那是乙的 913 次请求），且这轮**不开美股 tab**。

本套件钉住四类事：
1. **解析按实测字节，不按想象**——jsonp 外层、`count`/`data` 内层、中文名 `cname` 优先、
   `category` 既有 null 也有空串、`market` 原样进 `exchange`（`lib/profile.ts:91` 与
   `tencent_provider.CURRENCY_BY_TYPE` 早已按 `us`/`NASDAQ` 写死）。
2. **额度闸**：`US_LIST_PAGES` 的默认值、非法回落、"合法但手滑"的巨大值被硬上限夹住；
   上游给不满一页就**不再往后发**——"少花钱"必须有断言，不然它只是一句注释。
3. **不替主人判算不算一条美股**（#32 的 (2) 仍待字）：ETF/畸形行照收，只丢**结构不可用**的行
   （无 symbol、或两个名字都缺）。这是一组**反向**断言，防的是"将来有人手一抖加了白名单"。
4. **覆盖面必须自己说话**（CR9-31/R16）：`degraded=True` ＋ note 带盘子总数、行业缺失数、
   交易所分布、中途失败的页数与成因。

零出网：provider 模块里的 `requests` 整个换成假模块（不动全局 `requests`，免得污染同进程
其他套件，也免得"这条路没真出网"变成一句自我声明）。假对象对**没备数据的页号直接抛**——
"多发了一个请求"在本套件里是可见的失败，不是静默的省钱。

⚠️ 备页一律凑满 20 行（`jsonp20`）：新浪的真实页宽就是 20，而"给不满一页即视为到尾部"
是下面要单独断言的行为——测试输入若不凑满，就会把那个早停逻辑意外触发成前置条件。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr9_59_us_list.py
"""

import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含中文，Windows GBK 控制台会 UnicodeEncodeError。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from app.providers import akshare_provider as akp  # noqa: E402
from app.providers.base import get_list_provider, list_products_with_meta  # noqa: E402
from app.utils.limiter import get_limiter  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# ---------- 实测样本（10-04 逐字抓回：第 1 页 NVDA／第 2 页 VISA＋QQQ／第 913 页 ZZZTX） ----------

NVDA = {"name": "NVIDIA Corporation", "cname": "英伟达公司", "category": "半导体",
        "symbol": "NVDA", "price": "233.95", "market": "NASDAQ"}
VISA = {"name": "Visa Inc.", "cname": "维萨公司", "category": "",  # 实测：空串（不是 null）
        "symbol": "V", "price": "360.66", "market": "NYSE"}
QQQ = {"name": "Invesco QQQ Trust", "cname": "", "category": None,  # ETF：按甲不筛
       "symbol": "QQQ", "price": "480.10", "market": "NASDAQ"}
ZZZTX = {"name": "ZZZTX", "cname": "", "category": None,  # 10-03 实测的畸形行：name==symbol
         "symbol": "ZZZTX", "price": "500.00", "market": "NYSE"}

PAGE_SIZE = 20  # 新浪服务端把 num 硬截到 20（10-03 实测 num=100/500 都只回 20 行）


def jsonp(rows, count="18241") -> str:
    """拼出实测到的外层形态：一行注释 + `IO.XSRV2.CallbackList[..]({...});`"""
    body = json.dumps({"count": count, "data": rows}, ensure_ascii=False)
    return "/*<script>location.href='//sina.com';</script>*/\nIO.XSRV2.CallbackList[uslist](" + body + ");"


def jsonp20(rows, tag="a", count="18241") -> str:
    """凑满一页（20 行）；填充行用 `tag` 保唯一，免得跨页去重把 filler 也吃掉。"""
    padded = list(rows)
    i = 0
    while len(padded) < PAGE_SIZE:
        padded.append(dict(NVDA, symbol=f"F{tag}{i}"))
        i += 1
    return jsonp(padded, count)


def page_of(symbols) -> str:
    """一整页由指定代码构成（数量须＝20 才算"满页"）。"""
    return jsonp20([dict(NVDA, symbol=s) for s in symbols])


CALLS: list[dict] = []


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


def install_fake(pages: dict[int, object]) -> None:
    """把 provider 模块里的 `requests` 换掉；`pages` 没给的页号一律抛（＝越界可见）。"""
    CALLS.clear()

    def fake_get(url, params=None, timeout=None, **kw):
        raw_page = str((params or {}).get("page", ""))
        CALLS.append({"url": url, "params": params or {}, "timeout": timeout})
        spec = pages.get(int(raw_page) if raw_page.isdigit() else -1)
        if isinstance(spec, Exception):
            raise spec
        if spec is None:
            raise AssertionError(f"越界请求了第 {raw_page} 页（假数据只备了 {sorted(pages)}）")
        return FakeResponse(spec)

    akp.requests = types.SimpleNamespace(get=fake_get)  # type: ignore[attr-defined]


def with_pages(value):
    """临时设 `US_LIST_PAGES`。CR9-51 同族教训：**不许把本机 env 当常数读**，
    用例自己 pop／恢复，跑完不污染别的用例。"""

    class _Ctx:
        def __enter__(self):
            self.prev = os.environ.get("US_LIST_PAGES")
            if value is None:
                os.environ.pop("US_LIST_PAGES", None)
            else:
                os.environ["US_LIST_PAGES"] = str(value)
            return self

        def __exit__(self, *exc):
            if self.prev is None:
                os.environ.pop("US_LIST_PAGES", None)
            else:
                os.environ["US_LIST_PAGES"] = self.prev
            return False

    return _Ctx()


def listed(pages: dict[int, object], n: int):
    """跑一次 `_list_us_stocks`（页数钉成 n）。"""
    install_fake(pages)
    with with_pages(n):
        return akp.AkshareProvider()._list_us_stocks()


# ---------- 1. jsonp 解析 ----------


def test_jsonp_payload() -> None:
    obj = akp._jsonp_payload(jsonp([NVDA, VISA]))
    check("外层脱壳后拿到 count", obj.get("count") == "18241", str(obj)[:120])
    check("内层 data 是列表且行数对", isinstance(obj.get("data"), list) and len(obj["data"]) == 2)

    raised = ""
    try:
        akp._jsonp_payload("not json at all")
    except Exception as e:  # noqa: BLE001
        raised = type(e).__name__
    check("坏载荷抛错，不静默当成没有名单", bool(raised), raised)

    raised2 = ""
    try:
        akp._jsonp_payload("IO.XSRV2.CallbackList[uslist]([1,2]);")
    except Exception as e:  # noqa: BLE001
        raised2 = type(e).__name__
    check("🔁 顶层不是对象也抛（上游改形态要能发现）", bool(raised2), raised2)


# ---------- 2. 行映射：中文名优先、只有结构不可用才丢 ----------


def test_us_product_mapping() -> None:
    row = akp._us_product(NVDA)
    check("type 恒为 us", row is not None and row["type"] == "us", str(row)[:80])
    check("code 取 symbol 原样", row["code"] == "NVDA", str(row)[:80])
    check("cname 在 ⇒ name 用中文名（与 A股/港股同一套展示与检索）", row["name"] == "英伟达公司", str(row))
    check("中文名全拼照旧可得", row["pinyin"] == "yingweidagongsi", row["pinyin"])
    check("中文名首字母照旧可得", row["pinyinInitials"] == "ywdgs", row["pinyinInitials"])
    check("market 原样进 exchange（profile.ts 已按 NASDAQ 写死）", row["exchange"] == "NASDAQ", str(row)[:80])
    check("category 进 tags ⇒ 板块检索有词", row["tags"] == ["半导体"], str(row)[:80])

    v = akp._us_product(VISA)
    check("🔁 category 为空串 ⇒ tags 为空（不是 ['']）", v["tags"] == [], str(v)[:80])
    check("交易所不被改写（NYSE 原样）", v["exchange"] == "NYSE", str(v)[:80])

    q = akp._us_product(QQQ)
    check("cname 缺失 ⇒ 回落英文全名", q["name"] == "Invesco QQQ Trust", str(q)[:90])
    check("英文名喂 `_pinyin_pair` 是透传（实测钉住，不靠猜）",
          q["pinyin"] == "Invesco QQQ Trust" and q["pinyinInitials"] == "Invesco QQQ Trust", str(q)[:110])
    check("🔁 category 为 null ⇒ tags 为空（null 与空串同处）", q["tags"] == [], str(q)[:90])
    check("ETF 不被筛掉：算不算一条美股归主人（#32 (2) 待字）", q["code"] == "QQQ", str(q)[:90])

    outs = [
        akp._us_product({"symbol": "", "name": "No Symbol Inc.", "cname": "无代码"}),
        akp._us_product({"symbol": "ABC", "name": "", "cname": ""}),
        akp._us_product({"symbol": "   ", "name": "Blank Symbol", "cname": ""}),
    ]
    check("🔁 无 symbol ⇒ 丢（建不出 (type,code) 主键）", outs[0] is None, str(outs[0])[:80])
    check("🔁 两个名字都缺 ⇒ 丢（无法展示）", outs[1] is None, str(outs[1])[:80])
    check("🔁 只有空白的 symbol ⇒ 丢（strip 后判空）", outs[2] is None, str(outs[2])[:80])

    z = akp._us_product(ZZZTX)
    check("畸形行（name==symbol、category null）照收——它该进 note 的盘子而不是被隐身",
          z["code"] == "ZZZTX" and z["name"] == "ZZZTX" and z["tags"] == [], str(z)[:90])


# ---------- 3. 额度闸：默认 / 非法回落 / 硬上限 ----------


def test_page_env() -> None:
    with with_pages(None):
        check("默认页数＝15（≈300 只，甲的盘子）", akp._us_list_pages() == 15, str(akp._us_list_pages()))
    with with_pages(3):
        check("env US_LIST_PAGES=3 生效", akp._us_list_pages() == 3, str(akp._us_list_pages()))
    for bad in ("abc", "0", "-5", ""):
        with with_pages(bad):
            check(f"非法值 {bad!r} 回落默认而不是抛", akp._us_list_pages() == 15, str(akp._us_list_pages()))
    with with_pages(5000):
        check("🔁 合法但巨大的值被硬上限夹住（1 页＝1 次真请求）",
              akp._us_list_pages() == akp.US_LIST_PAGE_CEILING, str(akp._us_list_pages()))
    check("默认值不许超过硬上限（两个常数不许互相矛盾）",
          akp.US_LIST_DEFAULT_PAGES <= akp.US_LIST_PAGE_CEILING)
    check("跑完不污染环境", "US_LIST_PAGES" not in os.environ)


# ---------- 4. 整条列表：声明 / 翻页 / 早停 / 部分失败 ----------


def test_list_us_stocks_declaration() -> None:
    em_before = get_limiter("eastmoney").state()
    obs_before = get_limiter("akshare-obs").state()
    rows, meta = listed({1: jsonp20([NVDA, VISA, QQQ, ZZZTX], "d")}, 1)
    check("一页 20 行", len(rows) == 20, str(len(rows)))
    check("source 声明＝新浪美股名单（不是 akshare 主源）", meta["source"] == "sina-us-category-list", str(meta)[:90])
    check("覆盖面按设计缩水 ⇒ 恒带 degraded 声明", meta.get("degraded") is True, str(meta)[:90])
    check("note 带上游自己声明的盘子数", "18241" in meta["note"], meta["note"][:160])
    check("note 带行业缺失计数（VISA 空串／QQQ／ZZZTX 为 null）", "行业缺失 3 行" in meta["note"], meta["note"][:160])
    check("note 带交易所分布（16 个填充行也是 NASDAQ）",
          "NASDAQ×18" in meta["note"] and "NYSE×2" in meta["note"], meta["note"][:160])
    check("note 明写不替主人判可投资性", "#32" in meta["note"], meta["note"][:160])
    check("note 说清只取前排 N 页＝子集", "只取前排 1 页" in meta["note"], meta["note"][:160])

    em_after = get_limiter("eastmoney").state()
    check("整条美股列表一次都不占东财桶（granted/denied/seenTotal 逐项未变）",
          (em_after["granted"], em_after["denied"], em_after["seenTotal"])
          == (em_before["granted"], em_before["denied"], em_before["seenTotal"]),
          f"granted {em_before['granted']}→{em_after['granted']}")
    obs_after = get_limiter("akshare-obs").state()
    check("但记进观测面一笔（#27 的计数覆盖到这条路）",
          obs_after["seenTotal"] - obs_before["seenTotal"] == 1,
          str(obs_after["seenTotal"] - obs_before["seenTotal"]))
    check("观测口径＝一次调用一笔，不是 N 页 N 笔（1 笔观测 ≠ 1 个 HTTP 请求，CR9-3 同族陷阱）",
          "sina.us-list" in obs_after["seen"], str(obs_after["seen"])[:120])


def test_list_us_stocks_paging() -> None:
    p1 = ["NVDA"] + [f"A{i}" for i in range(PAGE_SIZE - 1)]
    p4 = ["NVDA"] + [f"D{i}" for i in range(PAGE_SIZE - 1)]
    pages = {
        1: page_of(p1),
        2: page_of([f"B{i}" for i in range(PAGE_SIZE)]),
        3: page_of([f"C{i}" for i in range(PAGE_SIZE)]),
        4: page_of(p4),
    }
    rows, meta = listed(pages, 4)
    check("env=4 ⇒ 恰好 4 次请求", len(CALLS) == 4, str(len(CALLS)))
    check("每页都按 num=20 要（服务端本来就截到 20）",
          all(c["params"].get("num") == "20" for c in CALLS))
    check("page 参数逐页递增", [c["params"].get("page") for c in CALLS] == ["1", "2", "3", "4"],
          str([c["params"].get("page") for c in CALLS]))
    codes = [r["code"] for r in rows]
    check("跨页重复代码去重（80 行里 NVDA 两次 ⇒ 79）", len(codes) == 79, str(len(codes)))
    check("去重后不出现重复主键", len(set(codes)) == len(codes))
    check("去重留前排那次（第 1 页优先，不被后面的页覆盖）", codes[0] == "NVDA", str(codes[:3]))
    check("四页都满 ⇒ note 不提失败页数", "页失败" not in meta["note"], meta["note"][:160])


def test_list_us_stocks_early_stop() -> None:
    rows, meta = listed({1: page_of([f"A{i}" for i in range(PAGE_SIZE)]), 2: jsonp([NVDA])}, 6)
    check("上游给不满一页 ⇒ 判定已到尾部", len(rows) == 21, str(len(rows)))
    check("停＝不再往后发请求（6 页的额度只用了 2 次）", len(CALLS) == 2, str(len(CALLS)))
    check("🔁 尾部不是失败：note 不提失败页数", "页失败" not in meta["note"], meta["note"][:160])


def test_list_us_stocks_partial_and_total_failure() -> None:
    rows, meta = listed(
        {1: jsonp20([NVDA, VISA], "x"), 2: RuntimeError("RemoteDisconnected"), 3: jsonp20([QQQ], "y")},
        3,
    )
    check("中途一页失败 ⇒ 已拿到的行照常返回（不整轮作废）", len(rows) == 40, str(len(rows)))
    check("失败的页数必须自己说话", "1 页失败" in meta["note"], meta["note"][:160])
    check("失败成因带在 note 里（不看日志也能归因）", "RemoteDisconnected" in meta["note"], meta["note"][:200])
    check("部分到货仍算一次成功（degraded 只有一份语义，不新增失败态）",
          meta.get("degraded") is True, str(meta)[:90])

    raised = ""
    try:
        listed({1: RuntimeError("conn aborted"), 2: RuntimeError("conn aborted")}, 2)
    except Exception as e:  # noqa: BLE001
        raised = type(e).__name__
    check("全页皆失败 ⇒ ProviderError（空列表不许冒充成功）", raised == "ProviderError", raised)


# ---------- 5. 注册与派发 ----------


def test_registration_and_dispatch() -> None:
    check("us 真的进了列表注册表", get_list_provider("us") is akp._akshare, "not registered")
    install_fake({1: jsonp20([NVDA], "r")})
    with with_pages(1):
        items, meta = list_products_with_meta(akp._akshare, "us")
    check("env 读的是**调用时**的值（1 页 ⇒ 恰好 1 次请求）", len(CALLS) == 1, str(len(CALLS)))
    check("list_products 派发到 us 分支", len(items) == 20 and items[0]["type"] == "us", str(items)[:90])
    check("(items, meta) 归一化后 source 仍是声明值（CR9-31 形态不被包装吃掉）",
          meta["source"] == "sina-us-category-list", str(meta)[:90])
    raised = ""
    try:
        akp._akshare.list_products("not-a-type")
    except Exception as e:  # noqa: BLE001
        raised = type(e).__name__
    check("未支持的列表类型仍拒（加 us 没把白名单打开）", raised == "ProviderError", raised)


if __name__ == "__main__":
    test_jsonp_payload()
    test_us_product_mapping()
    test_page_env()
    test_list_us_stocks_declaration()
    test_list_us_stocks_paging()
    test_list_us_stocks_early_stop()
    test_list_us_stocks_partial_and_total_failure()
    test_registration_and_dispatch()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
