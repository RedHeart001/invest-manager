"""CR9-59/CR10-40 离线单测：美股完整候选快照事务。

CR10-40 明确替代“失败页/配置截断也可作为有意子集交付”的旧语义。声明建立页义务，
网络/解析/行数异常同页有界恢复，首轮后集中修复；稳定声明、原始代码唯一性和尾页后
空页共同构成可观测的完整性证明。行业筛选只在完整采集后发生。

本套件零出网，假模块对未备页和超额尝试直接抛错；除映射与配额外，重点故障注入：
- 两枚独立失败页首轮未解决、集中修复恢复；
- 真实尾页不重试，持续短尾绝不交付；
- 声明变化、重复/缺失代码、非空穷尽页、配置不足均 fail-closed；
- 看门狗到期不采用被弃响应，所有恢复轮次共享期限。

运行：PYTHONPATH=. .venv/Scripts/python tests/test_cr9_59_us_list.py
"""

import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含中文，Windows GBK 控制台会 UnicodeEncodeError。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# CR9-100（#70）：先于 app 的任何 import 把 limiter 落盘账本指到临时目录——
# 本套件直接 import `akshare_provider`（内建 `akshare-obs`/`eastmoney` 族），
# 退出时 atexit 补落盘，不指走就把测试计数写进仓库那份 `runtime/limiter-state.json`
#（与 `test_p2_m8.py` 同一条纪律）。
os.environ["LIMITER_STATE_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="cr9100-limiter-"), "limiter-state.json")

# CR9-119（10-18 18:1x）：**操作者那份 `data-service/.env` 也不许进离线单测**。
# 今天 16:3x 之前该文件不存在，本套的"默认页数＝15"是绿的；文件一建（`US_LIST_PAGES=50`）
# 它就 73/74 红在那一条＝`with_pages(None)` 只 pop 了进程环境变量，挡不住
# `_us_list_pages()` 里那次**懒加载**（`load_env()` 首次执行才读盘、用 setdefault 灌回 50）。
# 这是上面 `#33 甲` 那句"不许把本机 env 当常数读"的另一半：文件层也属于"本机"。
# 隔离做法＝把 `app.config._ENV_FILES` 指到临时目录里一份**不存在**的文件（`load_env()`
# 对不存在的路径直接跳过）。生产那条路没被弄坏，由 `test_env_file_layer_still_works` 成对证明。
import app.config as _cfg  # noqa: E402
from pathlib import Path  # noqa: E402

_REAL_ENV_FILES = list(_cfg._ENV_FILES)
_cfg._ENV_FILES[:] = [Path(tempfile.mkdtemp(prefix="cr9119-env-")) / "absent.env"]

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
QQQ = {"name": "Invesco QQQ Trust", "cname": "", "category": None,  # ETF：无行业 ⇒ 列表层剔掉
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


def page_of(symbols, count="18241") -> str:
    """一整页由指定代码构成（数量须＝20 才算"满页"）。"""
    return jsonp20([dict(NVDA, symbol=s) for s in symbols], count=count)


CALLS: list[dict] = []
SESSIONS: list[object] = []


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


def install_fake(pages: dict[int, object]) -> None:
    """把 provider 模块里的 `requests` 换掉；list/tuple 表示同页逐次尝试的响应。

    序列耗尽后继续请求会抛错，令多买一次也可见；没备数据的页号同样抛错。
    """
    CALLS.clear()
    SESSIONS.clear()
    attempts: dict[int, int] = {}

    def fake_get(url, params=None, timeout=None, **kw):
        raw_page = str((params or {}).get("page", ""))
        page = int(raw_page) if raw_page.isdigit() else -1
        CALLS.append({"url": url, "params": params or {}, "timeout": timeout})
        spec = pages.get(page)
        if isinstance(spec, (list, tuple)):
            attempt = attempts.get(page, 0)
            if not spec or attempt >= len(spec):
                raise AssertionError(f"第 {page} 页尝试次数超出假数据序列 {len(spec)}")
            spec = spec[attempt]
            attempts[page] = attempt + 1
        if isinstance(spec, Exception):
            raise spec
        if spec is None:
            raise AssertionError(f"越界请求了第 {raw_page} 页（假数据只备了 {sorted(pages)}）")
        return FakeResponse(spec)

    class FakeSession:
        def __init__(self) -> None:
            self.closed = False
            SESSIONS.append(self)

        def get(self, *args, **kwargs):
            return fake_get(*args, **kwargs)

        def close(self) -> None:
            self.closed = True

    # 使用真 Session 生命周期形状，确保集中修复确实换会话且所有会话被关闭。
    akp.requests = types.SimpleNamespace(get=fake_get, Session=FakeSession)  # type: ignore[attr-defined]


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
    fallback = akp._us_product(dict(NVDA, symbol="NAMELESS", name="", cname="", category=None))
    check("11-22 真实空名行以代码作稳定展示名，行业仍由上游 category 决定",
          fallback is not None and fallback["name"] == "NAMELESS" and fallback["tags"] == [], str(fallback))
    false_names = akp._us_product(dict(NVDA, symbol="FALSE_NAME", name=False, cname=False, category=None))
    check("11-22 真实 false 名称同样回退，不整批拒绝",
          false_names is not None and false_names["name"] == "FALSE_NAME", str(false_names))
    check("🔁 缺名称字段属结构漂移，不借代码回退吞掉",
          akp._us_product({"symbol": "MISSING_NAMES", "category": "半导体"}) is None)
    check("🔁 非字符串非 false 名称属结构漂移", akp._us_product({"symbol": "BAD", "name": 1, "cname": ""}) is None)
    check("🔁 布尔 true 不是空名，不得变成展示名",
          akp._us_product({"symbol": "TRUE_BOTH", "name": True, "cname": True}) is None)
    check("🔁 name 单侧 true 仍拒绝",
          akp._us_product({"symbol": "TRUE_NAME", "name": True, "cname": ""}) is None)
    check("🔁 cname 单侧 true 仍拒绝",
          akp._us_product({"symbol": "TRUE_CNAME", "name": "Valid Name", "cname": True}) is None)

    check("🔁 category 为空串 ⇒ tags 为空（不是 ['']）", v["tags"] == [], str(v)[:80])
    check("交易所不被改写（NYSE 原样）", v["exchange"] == "NYSE", str(v)[:80])

    q = akp._us_product(QQQ)
    check("cname 缺失 ⇒ 回落英文全名", q["name"] == "Invesco QQQ Trust", str(q)[:90])
    check("英文名喂 `_pinyin_pair` 是透传（实测钉住，不靠猜）",
          q["pinyin"] == "Invesco QQQ Trust" and q["pinyinInitials"] == "Invesco QQQ Trust", str(q)[:110])
    check("🔁 category 为 null ⇒ tags 为空（null 与空串同处）", q["tags"] == [], str(q)[:90])
    check("行级映射不看品种：QQQ 照样出行（筛不筛是列表层那道闸的事，见第 4 节）",
          q["code"] == "QQQ", str(q)[:90])

    outs = [
        akp._us_product({"symbol": "", "name": "No Symbol Inc.", "cname": "无代码"}),
        akp._us_product({"symbol": "ABC", "name": "", "cname": ""}),
        akp._us_product({"symbol": "   ", "name": "Blank Symbol", "cname": ""}),
    ]
    check("🔁 无 symbol ⇒ 丢（建不出 (type,code) 主键）", outs[0] is None, str(outs[0])[:80])
    check("两个名称值为空但有合法代码 ⇒ 回退代码名", outs[1] is not None and outs[1]["name"] == "ABC", str(outs[1])[:80])
    check("🔁 只有空白的 symbol ⇒ 丢（strip 后判空）", outs[2] is None, str(outs[2])[:80])

    z = akp._us_product(ZZZTX)
    check("畸形行（name==symbol、category null）在映射层仍出行——它被剔是因为**没有行业**，"
          "不是因为名字长得像代码（两道闸各有各的字面）",
          z["code"] == "ZZZTX" and z["name"] == "ZZZTX" and z["tags"] == [], str(z)[:90])


# ---------- 3. 额度闸：默认 / 非法回落 / 硬上限 ----------


def test_page_env() -> None:
    check("CR9-119 隔离自证：文件层已不在仓库真路径上（操作者的 .env 进不了本套）",
          all(str(p) not in {str(x) for x in _REAL_ENV_FILES} for p in _cfg._ENV_FILES),
          str(_cfg._ENV_FILES)[:120])
    with with_pages(None):
        check("默认页数＝950（乙给到硬上限、早停按实盘买；代码默认即乙，.env 丢了也不缩回甲）",
              akp._us_list_pages() == 950, str(akp._us_list_pages()))
    with with_pages(3):
        check("env US_LIST_PAGES=3 生效", akp._us_list_pages() == 3, str(akp._us_list_pages()))
    for bad in ("abc", "0", "-5", ""):
        with with_pages(bad):
            check(f"非法值 {bad!r} 回落默认而不是抛", akp._us_list_pages() == 950, str(akp._us_list_pages()))
    with with_pages(5000):
        check("🔁 合法但巨大的值被硬上限夹住（1 页＝1 次真请求）",
              akp._us_list_pages() == akp.US_LIST_PAGE_CEILING, str(akp._us_list_pages()))
    check("默认值不许超过硬上限（两个常数不许互相矛盾）",
          akp.US_LIST_DEFAULT_PAGES <= akp.US_LIST_PAGE_CEILING)
    check("乙的默认＝给到硬上限（页数由早停按上游实盘定，不许钉死一个会过期的页数）",
          akp.US_LIST_DEFAULT_PAGES == akp.US_LIST_PAGE_CEILING,
          f"default={akp.US_LIST_DEFAULT_PAGES} ceiling={akp.US_LIST_PAGE_CEILING}")
    # CR10-2（10-20 补牙）＋乙（11-12）：真硬闸仍是看门狗，但预算口径换了——
    # 最坏网络（20.5s/页）下它仍夹页数；名义速度（≈1s/页）下必须装得下**整个硬上限**。
    # 符号式断言＝改任一枚常数自动适配，不用手改"7"那种魔数。
    _per_page_s = akp.US_LIST_REQUEST_TIMEOUT_S + akp.US_LIST_PAGE_INTERVAL_S
    _pages_the_watchdog_allows = int(akp.US_LIST_WHOLE_TIMEOUT_S // _per_page_s)
    check("最坏网络下看门狗仍是真硬闸：夹出的有效页数 < 硬上限（符号式）",
          _pages_the_watchdog_allows < akp.US_LIST_PAGE_CEILING,
          f"whole={akp.US_LIST_WHOLE_TIMEOUT_S} ⇒ {_pages_the_watchdog_allows} 页 vs ceiling={akp.US_LIST_PAGE_CEILING}")
    check("乙用例①：名义速度（1s/页）看门狗装得下整个硬上限（BACKLOG 底稿的 WHOLE=900 会当场红）",
          akp.US_LIST_WHOLE_TIMEOUT_S >= akp.US_LIST_PAGE_CEILING * 1.0,
          f"whole={akp.US_LIST_WHOLE_TIMEOUT_S} vs ceiling×1.0={akp.US_LIST_PAGE_CEILING * 1.0}")
    check("🔁 整条预算至少够走完一页（否则名单腿在任何网络条件下都必然空手而归）",
          akp.US_LIST_WHOLE_TIMEOUT_S >= _per_page_s, str(akp.US_LIST_WHOLE_TIMEOUT_S))
    check("跑完不污染环境", "US_LIST_PAGES" not in os.environ)


def test_env_file_layer_still_works() -> None:
    """C34 成对的另一半：本套把文件层隔离掉了 ⇒ 必须当场证明**生产那条路照旧通**。

    演法＝临时造一份写着 `US_LIST_PAGES=7` 的假 env 文件、把 `_LOADED` 一次性守卫解冻，
    让 `_us_list_pages()` 走一次真加载；跑完把守卫与 `_ENV_FILES` 原样恢复（不许留下
    "测试进程从此读不到盘上配置"这种副作用）。判别力＝若哪天有人把 `load_env()` 从
    `_us_list_pages()` 里摘掉、或把守卫改成每次重读，这一条与上面那枚隔离自证会分别红。
    """
    d = tempfile.mkdtemp(prefix="cr9119-layer-")
    f = os.path.join(d, ".env")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("US_LIST_PAGES=7\n")
    saved_files = list(_cfg._ENV_FILES)
    saved_loaded = _cfg._LOADED
    os.environ.pop("US_LIST_PAGES", None)
    try:
        _cfg._ENV_FILES[:] = [Path(f)]
        _cfg._LOADED = False
        got = akp._us_list_pages()
        check("🔁 生产路径没被本套的隔离弄坏：盘上那份 .env 照样被读（7 页）", got == 7, str(got))
    finally:
        _cfg._LOADED = saved_loaded
        _cfg._ENV_FILES[:] = saved_files
        os.environ.pop("US_LIST_PAGES", None)
    check("🔁 跑完恢复隔离态（守卫冻回原值、文件层指回临时不存在的那份）",
          _cfg._LOADED == saved_loaded
          and all(str(p) not in {str(x) for x in _REAL_ENV_FILES} for p in _cfg._ENV_FILES)
          and "US_LIST_PAGES" not in os.environ,
          str(_cfg._ENV_FILES)[:120])


# ---------- 4. 整条列表：声明 / 翻页 / 早停 / 部分失败 ----------


def test_list_us_stocks_declaration() -> None:
    em_before = get_limiter("eastmoney").state()
    obs_before = get_limiter("akshare-obs").state()
    rows, meta = listed({
        1: jsonp20([NVDA, VISA, QQQ, ZZZTX], "d", count="20"),
        2: jsonp([], count="20"),
    }, 1)
    check("完整 20 行采集后按行业口径留 17", len(rows) == 17, str(len(rows)))
    check("source 声明＝新浪美股名单", meta["source"] == "sina-us-category-list", str(meta)[:90])
    check("采集完整与产品口径子集分账",
          meta.get("acquisitionComplete") is True and meta.get("productPolicySubset") is True
          and meta.get("intentionalSubset") is True, str(meta)[:150])
    check("原始声明与实收分别记账", meta.get("declaredCount") == 20 and meta.get("acquiredCount") == 20)
    check("note 带声明数、原始去重和穷尽页证明",
          all(x in meta["note"] for x in ("声明 20", "原始代码去重 20", "穷尽页 p2 为空")), meta["note"][:220])
    check("note 报剔掉 3 行及交易所分布", "剔掉 3 行" in meta["note"] and "NASDAQ×17" in meta["note"])
    check("行业口径出处和 ETF 限制仍可见", "#32" in meta["note"] and "ETF" in meta["note"])
    check("成功/失败路径均关闭 Session", len(SESSIONS) == 1 and all(s.closed for s in SESSIONS))
    em_after = get_limiter("eastmoney").state()
    check("美股列表不占东财桶",
          (em_after["granted"], em_after["denied"], em_after["seenTotal"])
          == (em_before["granted"], em_before["denied"], em_before["seenTotal"]))
    obs_after = get_limiter("akshare-obs").state()
    check("整条逻辑请求只记一笔观测，不是每页一笔",
          obs_after["seenTotal"] - obs_before["seenTotal"] == 1 and "sina.us-list" in obs_after["seen"])


def test_list_us_stocks_paging() -> None:
    pages = {
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="80"),
        2: page_of([f"B{i}" for i in range(PAGE_SIZE)], count="80"),
        3: page_of([f"C{i}" for i in range(PAGE_SIZE)], count="80"),
        4: page_of([f"D{i}" for i in range(PAGE_SIZE)], count="80"),
        5: jsonp([], count="80"),
    }
    rows, meta = listed(pages, 4)
    check("声明 80 ⇒ 4 页义务＋1 页穷尽，恰好 5 次请求", len(CALLS) == 5, str(len(CALLS)))
    check("每页 num=20，页序列连续并有穷尽页",
          all(c["params"].get("num") == "20" for c in CALLS)
          and [c["params"]["page"] for c in CALLS] == ["1", "2", "3", "4", "5"])
    check("80 个唯一代码全量交付，不提前按配置页数早停",
          len(rows) == 80 and len({r["code"] for r in rows}) == 80)
    check("完整且没有行业剔除 ⇒ 两类子集声明均为 False",
          meta["acquisitionComplete"] is True and meta["productPolicySubset"] is False
          and meta["intentionalSubset"] is False and meta["degraded"] is False)


def test_list_us_stocks_early_stop() -> None:
    rows, meta = listed({
        1: [jsonp([NVDA], count="21"), page_of([f"A{i}" for i in range(PAGE_SIZE)], count="21")],
        2: jsonp([dict(NVDA, symbol="TAIL")], count="21"),
        3: jsonp([], count="21"),
    }, 6)
    check("首页异常短页也走同一页义务恢复，不多一次也不少一次",
          len(rows) == 21 and [c["params"]["page"] for c in CALLS] == ["1", "1", "2", "3"])

    rows, meta = listed({
        1: [RuntimeError("first disconnected"), "not json",
            page_of([f"A{i}" for i in range(PAGE_SIZE)], count="20")],
        2: jsonp([], count="20"),
    }, 2)
    check("首页网络与解析失败同页最多三次恢复，第三次成功仍建完整候选",
          len(rows) == 20 and [c["params"]["page"] for c in CALLS] == ["1", "1", "1", "2"])

    rows, meta = listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="21"),
        2: jsonp([dict(NVDA, symbol="TAIL")], count="21"),
        3: jsonp([], count="21"),
    }, 6)
    check("真实尾页按页位应有 1 行，恢复 21 行", len(rows) == 21, str(len(rows)))
    check("真实尾页只请求一次，再加一枚空页证明穷尽",
          [c["params"]["page"] for c in CALLS] == ["1", "2", "3"])
    check("完整采集元数据真实声明", meta["acquisitionComplete"] is True and meta["acquiredCount"] == 21)

    rows, _ = listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="21"),
        2: jsonp([dict(NVDA, symbol="TAIL")], count="21"),
        3: [RuntimeError("probe disconnected"), jsonp([], count="21")],
    }, 6)
    check("穷尽探测断连同页恢复，不把无证明的候选交付",
          len(rows) == 21 and [c["params"]["page"] for c in CALLS] == ["1", "2", "3", "3"])

    msg = _raises(lambda: listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="21"),
        2: jsonp([dict(NVDA, symbol="TAIL")], count="21"),
        3: [RuntimeError("probe down")] * 3,
    }, 6))
    check("穷尽探测持续失败 ⇒ 即使声明页齐全也拒绝候选", "exhaustion probe p3 unresolved" in msg, msg[:180])


def test_list_us_stocks_premature_short_page() -> None:
    short = [dict(NVDA, symbol=f"SHORT{i}") for i in range(18)]
    full = page_of([f"B{i}" for i in range(PAGE_SIZE)], count="41")
    rows, meta = listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="41"),
        2: [jsonp(short, count="41"), full],
        3: jsonp([dict(NVDA, symbol="TAIL")], count="41"),
        4: jsonp([], count="41"),
    }, 6)
    codes = [row["code"] for row in rows]
    check("异常短页同页立即恢复，最终完整 41 行", len(rows) == 41 and meta["acquisitionComplete"] is True)
    check("恢复序列 1,2,2,3,4；被弃 18 行不进入结果",
          [c["params"]["page"] for c in CALLS] == ["1", "2", "2", "3", "4"]
          and not any(c.startswith("SHORT") for c in codes))

    rows, _ = listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="41"),
        2: [jsonp(short, count="41"), jsonp(short, count="41"), full],
        3: jsonp([dict(NVDA, symbol="TAIL")], count="41"),
        4: jsonp([], count="41"),
    }, 6)
    check("第二次重试才恢复也有效，最多三次总尝试",
          len(rows) == 41 and [c["params"]["page"] for c in CALLS] == ["1", "2", "2", "2", "3", "4"])

    raised, msg = "", ""
    try:
        listed({
            1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="40"),
            2: [jsonp([NVDA], count="40")] * 9,
        }, 6)
    except Exception as e:  # noqa: BLE001
        raised, msg = type(e).__name__, str(e)
    check("持续短尾在首轮＋两轮修复共 9 次后仍整份拒绝",
          raised == "ProviderError" and "incomplete snapshot" in msg and "1/2 pages resolved" in msg,
          f"{raised}｜{msg[:180]}")
    check("持续短尾请求有界且不读穷尽页冒充成功",
          len(CALLS) == 10 and CALLS[-1]["params"]["page"] == "2")
    check("重试常数与集中修复轮数有界", akp.US_LIST_SHORT_PAGE_RETRIES == 2 and akp.US_LIST_REPAIR_ROUNDS == 2)

    install_fake({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="41"),
        2: [jsonp(short, count="41"), full],
    })
    saved_sleep, saved_monotonic = akp.time.sleep, akp.time.monotonic
    saved_timeout, saved_request = akp.US_LIST_WHOLE_TIMEOUT_S, akp._ak_request
    clock, sleeps = [0.0], [0]

    def fake_sleep(_seconds):
        sleeps[0] += 1
        if sleeps[0] == 2:
            clock[0] += 2000.0

    try:
        akp.time.sleep, akp.time.monotonic = fake_sleep, lambda: clock[0]
        akp.US_LIST_WHOLE_TIMEOUT_S = 1500.0
        akp._ak_request = lambda fn, seconds, name: fn()
        raised, msg = "", ""
        try:
            with with_pages(6):
                akp.AkshareProvider()._list_us_stocks()
        except Exception as e:  # noqa: BLE001
            raised, msg = type(e).__name__, str(e)
    finally:
        akp.time.sleep, akp.time.monotonic = saved_sleep, saved_monotonic
        akp.US_LIST_WHOLE_TIMEOUT_S, akp._ak_request = saved_timeout, saved_request
    check("重试节流跨过看门狗后拒绝，不采用被弃短页",
          raised == "ProviderError" and "incomplete snapshot" in msg, f"{raised}｜{msg[:160]}")
    check("看门狗到期后不再发请求，Session 仍关闭",
          [c["params"]["page"] for c in CALLS] == ["1", "2"] and all(s.closed for s in SESSIONS))


def test_list_us_stocks_partial_and_total_failure() -> None:
    # 两枚不同故障页在集中修复中恢复；第二页首轮三次失败，第三页首轮短页三次失败。
    short = jsonp([NVDA], count="61")
    rows, meta = listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="61"),
        2: [RuntimeError("RemoteDisconnected")] * 3 + [page_of([f"B{i}" for i in range(PAGE_SIZE)], count="61")],
        3: [short] * 3 + [page_of([f"C{i}" for i in range(PAGE_SIZE)], count="61")],
        4: jsonp([dict(NVDA, symbol="TAIL")], count="61"),
        5: jsonp([], count="61"),
    }, 6)
    check("CR10-40：两枚失败页首轮不丢弃，集中修复后完整交付 61 行",
          len(rows) == 61 and meta["acquisitionComplete"] is True, str(meta)[:180])
    check("集中修复换新 Session 且全部关闭", len(SESSIONS) == 2 and all(s.closed for s in SESSIONS))
    seq = [c["params"]["page"] for c in CALLS]
    check("修复只点未解决页，不重买已成功页", seq == ["1", "2", "2", "2", "3", "3", "3", "4", "2", "3", "5"], str(seq))

    # 一页永久失败不能阻止另一页恢复，但最终仍无候选。
    raised = ""
    try:
        listed({
            1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="61"),
            2: [RuntimeError("down")] * 9,
            3: [short] * 3 + [page_of([f"C{i}" for i in range(PAGE_SIZE)], count="61")],
            4: jsonp([dict(NVDA, symbol="TAIL")], count="61"),
            5: jsonp([], count="61"),
        }, 6)
    except Exception as e:  # noqa: BLE001
        raised = str(e)
    check("一页持续失败时仍独立修复其他页，最终 3/4 页而拒绝",
          "incomplete snapshot" in raised and "3/4 pages resolved" in raised, raised[:180])

    raised = ""
    try:
        listed({1: [RuntimeError("conn aborted")] * 3}, 2)
    except Exception as e:  # noqa: BLE001
        raised = type(e).__name__
    check("首页全失败 ⇒ ProviderError，不伪造声明或空名单",
          raised == "ProviderError" and len(CALLS) == 3, f"{raised} / {len(CALLS)}")


# ---------- 4b. 行业闸（#32 的 (2) 定案＝10-04 03:1x 主人的字"剔除没行业的"） ----------


def test_category_gate() -> None:
    blank = dict(NVDA, symbol="BLANK", category="   ")
    rows, meta = listed({
        1: jsonp20([NVDA, VISA, QQQ, {"symbol": "NO_KEY", "name": "No Key", "cname": "无键"}, blank], "g", count="20"),
        2: jsonp([], count="20"),
    }, 1)
    codes = [r["code"] for r in rows]
    check("空串／null／全空白行业都由同一产品口径剔除",
          len(rows) == 16 and "剔掉 4 行" in meta["note"], f"{len(rows)}｜{meta['note'][:160]}")
    check("带行业的行没有误剔，原始 acquiredCount 仍是 20",
          len(codes) == 16 and meta["acquiredCount"] == 20 and meta["declaredCount"] == 20)

    raised, msg = "", ""
    try:
        listed({
            1: jsonp([VISA, QQQ, ZZZTX], count="3"),
            2: jsonp([], count="3"),
        }, 1)
    except Exception as e:  # noqa: BLE001
        raised, msg = type(e).__name__, str(e)
    check("完整采集但行业筛选后为空 ⇒ ProviderError，不交空载荷",
          raised == "ProviderError" and "mapped to empty" in msg, f"{raised}｜{msg[:140]}")

    raised, msg = "", ""
    try:
        listed({
            1: jsonp20([{"name": "No Symbol", "cname": "无代码"}], "bad", count="20"),
            2: jsonp([], count="20"),
        }, 1)
    except Exception as e:  # noqa: BLE001
        raised, msg = type(e).__name__, str(e)
    check("原始行缺 symbol 属完整性失败，不算产品口径剔除",
          raised == "ProviderError" and "raw row/symbol count" in msg, f"{raised}｜{msg[:140]}")

    rows, meta = listed({
        1: jsonp20([dict(NVDA, symbol="NO_NAME", name="", cname="", category=None)], "nameless", count="20"),
        2: jsonp([], count="20"),
    }, 1)
    check("有代码但名称为空且行业为空 ⇒ 完整采集后按既有行业口径剔除",
          len(rows) == 19 and meta["acquiredCount"] == 20 and meta["declaredCount"] == 20, str(meta))
    rows, _ = listed({
        1: jsonp20([dict(NVDA, symbol="NO_NAME", name="", cname="", category="半导体")], "nameless", count="20"),
        2: jsonp([], count="20"),
    }, 1)
    check("有代码、空名但有行业 ⇒ 回退代码名并保留该行",
          any(row["code"] == "NO_NAME" and row["name"] == "NO_NAME" for row in rows), str(rows)[-220:])
    raised, msg = "", ""
    try:
        listed({
            1: jsonp20([{"symbol": "MISSING_NAMES", "category": None}], "bad", count="20"),
            2: jsonp([], count="20"),
        }, 1)
    except Exception as e:  # noqa: BLE001
        raised, msg = type(e).__name__, str(e)
    check("名称字段缺失仍是结构失败，不借 intentionalSubset 放行",
          raised == "ProviderError" and "unmappable product" in msg, f"{raised}｜{msg[:140]}")


# ---------- 4c. CR10-40：候选完整性反向证明 ----------


def _raises(fn) -> str:
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        return str(e)
    return ""


def test_us_yi_full_coverage() -> None:
    saved = akp.US_LIST_WHOLE_TIMEOUT_S
    try:
        akp.US_LIST_WHOLE_TIMEOUT_S = 150.0
        check("看门狗反向钻仍有判别力", not (akp.US_LIST_WHOLE_TIMEOUT_S >= akp.US_LIST_PAGE_CEILING * 1.0))
    finally:
        akp.US_LIST_WHOLE_TIMEOUT_S = saved

    msg = _raises(lambda: listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="61"),
    }, 2))
    check("配置页数不足以覆盖声明 ⇒ 立即失败，只买首页，不交截断名单",
          "page budget 2 < required 4" in msg and len(CALLS) == 1, msg[:180])

    msg = _raises(lambda: listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="21"),
        2: jsonp([dict(NVDA, symbol="TAIL")], count="22"),
    }, 6))
    check("抓取期间声明变化 ⇒ 整份候选失败，不重采拼接",
          "declaration changed" in msg
          and [c["params"]["page"] for c in CALLS] == ["1", "2"], msg[:180])

    msg = _raises(lambda: listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="40"),
        2: jsonp([dict(NVDA, symbol=f"B{i}") for i in range(PAGE_SIZE)], count="41"),
    }, 6))
    check("后续页声明漂移立即失败，不能吞进失败页账本继续翻页",
          "declaration changed" in msg and [c["params"]["page"] for c in CALLS] == ["1", "2"], msg[:180])

    p1 = [dict(NVDA, symbol="DUP")] + [dict(NVDA, symbol=f"A{i}") for i in range(19)]
    p2 = [dict(NVDA, symbol="DUP")]
    msg = _raises(lambda: listed({
        1: jsonp(p1, count="21"), 2: jsonp(p2, count="21"), 3: jsonp([], count="21"),
    }, 6))
    check("页数与行数齐全但原始代码重复 ⇒ 完整性失败", "duplicate symbols" in msg, msg[:180])

    msg = _raises(lambda: listed({
        1: page_of([f"A{i}" for i in range(PAGE_SIZE)], count="20"),
        2: jsonp([dict(NVDA, symbol="EXTRA")], count="20"),
    }, 6))
    check("穷尽页非空 ⇒ 声明与页序矛盾，拒绝候选", "exhaustion probe" in msg, msg[:180])

    check("页义务算术按声明，不看累计失败缺口",
          akp._us_page_count(18424) == 922
          and akp._us_expected_rows(921, 18424) == 20
          and akp._us_expected_rows(922, 18424) == 4)
    check("声明非正数拒绝建立页义务", bool(_raises(lambda: akp._us_page_count(0))))


# ---------- 5. 注册与派发 ----------


def test_registration_and_dispatch() -> None:
    check("us 真的进了列表注册表", get_list_provider("us") is akp._akshare, "not registered")
    install_fake({
        1: jsonp20([NVDA], "r", count="20"),
        2: jsonp([], count="20"),
    })
    with with_pages(1):
        items, meta = list_products_with_meta(akp._akshare, "us")
    check("env 在调用时生效；一页义务之外仍需一枚穷尽页", len(CALLS) == 2, str(len(CALLS)))
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
    test_env_file_layer_still_works()
    test_list_us_stocks_declaration()
    test_list_us_stocks_paging()
    test_list_us_stocks_early_stop()
    test_list_us_stocks_premature_short_page()
    test_list_us_stocks_partial_and_total_failure()
    test_category_gate()
    test_us_yi_full_coverage()
    test_registration_and_dispatch()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
