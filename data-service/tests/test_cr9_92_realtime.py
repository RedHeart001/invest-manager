"""CR9-92（OPT-3 第一批 1a）离线单测：当日实时行情条的取数侧。

运行方式（无需任何服务在跑，零出网）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr9_92_realtime.py

这个套件的存在理由不是"聚合器算得对不对"（那几处算式都有独立用例），而是**三条红线**：
1. 不得注册成链上的 provider；
2. 一次调用都不许向 `eastmoney` 桶要额度（验收判据 ④ 的离线半边）；
3. 实时路径上不许出现 20s 排队（所以 `FamilyLimiter.acquire` 被换成"一调就抛"的桩，
   整条路还能跑完＝这条红线不是散文承诺）。
所有取数都用替身，域名白名单单独有一枚断言——它比"没打东财"更严，因为它连"以后有人
往这条路上加一条 akshare 腿"也会当场抓住。

⚠️ `LIMITER_STATE_FILE` 在 import 之前就指到临时目录：`observe()` 收尾会节流落盘，
不指走就会把测试计数写进仓库那份 `runtime/limiter-state.json`（与 `test_p2_m8.py:354` 同一条纪律）。
"""

import os
import sys
import tempfile

# 先于 app 的任何 import：观测族一 `observe()` 就可能落盘，落点必须是临时目录。
_STATE = os.path.join(tempfile.mkdtemp(prefix="cr992-limiter-"), "limiter-state.json")
os.environ["LIMITER_STATE_FILE"] = _STATE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from fastapi import HTTPException  # noqa: E402

import requests as REAL_REQUESTS  # noqa: E402  （替身还原用的那一份真模块）

import app.main as m  # noqa: E402
import app.realtime as rt  # noqa: E402
from app.providers import get_provider_chain  # noqa: E402
from app.providers import tencent_provider as tp  # noqa: E402
from app.utils.limiter import get_limiter  # noqa: E402
from app.utils.timeutil import beijing_today  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


TODAY = beijing_today()  # 2026-10-13 这种形状
TODAY_COMPACT = TODAY.replace("-", "")
YESTERDAY_COMPACT = "2026-10-12".replace("-", "")

URLS: list[str] = []


def _em_fields(price: float, prev: float, ts: str = "20261013093100") -> list[str]:
    """腾讯 `qt.gtimg.cn` 的字段数组：只填被映射的那些位，其余留空串（长度必须 >34）。"""
    f = [""] * 40
    f[1], f[2], f[3], f[4], f[5], f[6] = "贵州茅台", "600519", str(price), str(prev), str(prev), "18300"
    f[30], f[31], f[32], f[33], f[34] = ts, str(price - prev), f"{(price - prev) / prev * 100:.2f}", "1260.0", "1240.0"
    return f


def _sina_body(name: str, open_: float, prev: float, price: float, day: str = TODAY, clock: str = "09:31:00") -> str:
    f = [name, str(open_), str(prev), str(price), "1260.0", "1240.0", "1250.0", "1250.01", "1830000", "2287518271.0"]
    f += ["0"] * 20  # 10–29：五档买卖盘，本 schema 不映射
    f += [day, clock, "00"]
    return 'var hq_str_sh600519="' + ",".join(f) + '";'


def _minute_payload(day: str, rows: list[str], sym: str = "sh600519") -> dict:
    return {"data": {sym: {"data": {"date": day, "data": rows}, "qt": {}}}}


class _Resp:
    def __init__(self, text: str = "", content: bytes | None = None, payload: dict | None = None):
        self.text = text
        self.content = content if content is not None else text.encode("gbk", errors="ignore")
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload or {}


def make_fake_get(price: float = 1250.0, sina_price: float | None = None, minute_day: str = TODAY_COMPACT,
                  minute_rows: list[str] | None = None, sina_body: str | None = None) -> None:
    """装一个**按 URL 分派**的替身到两枚模块的 `requests` 名上，并记录每一条被请求的 URL。"""
    URLS.clear()
    rows = minute_rows if minute_rows is not None else [
        "0930 1250.01 183 22875182.71",
        "0931 1251.00 400 50000000.00",
        "0932 1252.50 900 90000000.00",
    ]

    def _get(url, params=None, **kw):
        # 替身必须按**请求里的那个符号**造响应：写死 sh600519 会让 fund/hk/us 三条腿读成
        # "缺数据"，于是 `degraded` 与 us 串号守卫两枚判据都被伪装成失败（10-13 首跑 3 枚红）。
        URLS.append(str(url))
        if "qt.gtimg.cn" in url:
            out = []
            for sym in str(url).split("q=")[-1].split(","):
                f = _em_fields(price, 1240.0)
                f[0] = "1"
                out.append('v_' + sym + '="' + "~".join(f) + '";')
            return _Resp(content="".join(out).encode("gbk", errors="ignore"))
        if "ifzq.gtimg.cn" in url:
            sym = str((params or {}).get("code") or "sh600519")
            return _Resp(payload=_minute_payload(minute_day, rows, sym))
        if "hq.sinajs.cn" in url:
            sym = str(url).split("list=")[-1]
            p = sina_price if sina_price is not None else price
            body = sina_body if sina_body is not None else _sina_body("贵州茅台", 1245.0, 1240.0, p)
            body = body.replace("hq_str_sh600519", "hq_str_" + sym, 1)
            return _Resp(content=body.encode("gbk", errors="ignore"))
        raise AssertionError(f"实时区请求了白名单外的域名：{url}")

    tp.requests = sys.modules["app.realtime"].requests = _RequestsShim(_get)


class _RequestsShim:
    def __init__(self, get):
        self.get = get


def cleanup() -> None:
    """把桩摘掉。每个用例都往这两枚模块的 `requests` 名上装替身，不还原就会留给后面的套件。"""
    tp.requests = REAL_REQUESTS
    rt.requests = REAL_REQUESTS


# ---------- ① 三条红线 ----------

def test_red_lines() -> None:
    """红线不靠注释守：注册面、桶增量、acquire 桩三处各一枚。"""
    realtime_in_chain = [
        p.source
        for t in rt.SOURCE_LEGS
        for p in get_provider_chain(t)
        if "realtime" in p.source
    ]
    check("①红线A：实时聚合件没有出现在任何类型的备源链注册面里", realtime_in_chain == [], str(realtime_in_chain))
    check("①红线A′：本模块根本不导 `register_chain`（想注册也注册不了）",
          not hasattr(rt, "register_chain"))

    make_fake_get()
    em = get_limiter("eastmoney")
    before = em.state()
    rt.aggregate("stock", "600519")
    after = em.state()
    check("①红线B：跑完一整条实时链，`eastmoney` 桶的 granted/denied 一个都没动（判据 ④ 的离线半边）",
          (before["granted"], before["denied"]) == (after["granted"], after["denied"]),
          f"{before['granted']}/{before['denied']} → {after['granted']}/{after['denied']}")

    observed_hosts = {u.split("/")[2] for u in URLS if "//" in u}
    check("①红线B′：请求面只允许腾讯与新浪三个域名（以后谁往这条路上加一条东财/akshare 腿就当场抓住）",
          observed_hosts <= {"qt.gtimg.cn", "ifzq.gtimg.cn", "hq.sinajs.cn"}, str(sorted(observed_hosts)))

    from app.utils import limiter as lm

    orig = lm.FamilyLimiter.acquire

    def _boom(self, timeout: float = 20.0) -> bool:
        raise AssertionError(f"实时路径上调了 acquire（族={self.name}）＝那条 20s 排队又回来了")

    lm.FamilyLimiter.acquire = _boom
    try:
        out = rt.aggregate("stock", "600519")
        boom = None
    except AssertionError as e:
        boom, out = str(e), None
    finally:
        lm.FamilyLimiter.acquire = orig
    check("①红线C：把 `acquire` 换成「一调就抛」的桩，整条实时链照样跑完（不是靠 timeout 参数蒙过去）",
          boom is None and out is not None, boom or "")

    obs = get_limiter(rt.OBS_FAMILY).state()
    check("①红线D：观测族只计数、不改行为（`granted/denied` 恒 0，`seenTotal` 在涨）",
          obs["granted"] == 0 and obs["denied"] == 0 and obs["seenTotal"] >= 3, str(obs["seenTotal"]))


# ---------- ② 响应 schema：`sources` 全公开 ----------

def test_schema_and_sources() -> None:
    make_fake_get()
    r = rt.aggregate("stock", "600519")
    top = {"type", "code", "observedAt", "price", "intraday", "crossChecked", "verifyVerdict",
           "consensus", "hasTodayData", "intradayDateIsToday", "wired", "sources", "degraded", "note"}
    check("②顶层键面齐（闸2 登记的 requiredTop 与这里同源）", top <= set(r), str(sorted(top - set(r))))
    check("②`sources` 逐条公开「点了谁、成没成、多久」：3 条腿（腾讯现价＋新浪现价＋腾讯分时）",
          len(r["sources"]) == 3 and all({"kind", "source", "ok", "latencyMs", "detail"} <= set(s) for s in r["sources"]),
          str(r["sources"]))
    check("②失败的腿也在案：摘掉新浪 ⇒ `sources` 里那条 `ok:false` 带着 detail",
          all(s["ok"] for s in r["sources"]))
    pts = r["intraday"]["points"]
    check("②分时的行键面＝t/price/volume（响应尺寸受 11–14KB 预算约束，所以不整段透传 candle）",
          pts and all({"t", "price", "volume"} <= set(p) for p in pts), str(pts[:1]))
    check("②`consensus` 带 `provisional`＋`basis`：阈值是预设值这件事必须是机器可读的，不靠屏上文案",
          r["consensus"]["provisional"] is True and len(r["consensus"]["basis"]) > 10, str(r["consensus"]))
    check("②场外净值那一类在实时区没有腿：`fund` 的 110022 两条腿都不成 ⇒ 判据②的「整块不出现」由此成立",
          (lambda f: f["price"] is None and f["intraday"] is None and f["hasTodayData"] is False)(
              rt.aggregate("fund", "110022")))
    make_fake_get()


# ---------- ③ 共识维（#64 甲：读的是这一条链自己的源集） ----------

def test_consensus() -> None:
    make_fake_get(price=1250.0, sina_price=1250.05)
    r = rt.aggregate("stock", "600519")
    check("③两源一致 ⇒ `agree`＋`crossChecked:true`＋偏差值（算式与 `chain.py:96-99` 同形）",
          r["verifyVerdict"] == "agree" and r["crossChecked"] is True and r["consensus"]["diffPct"] is not None,
          str(r["consensus"]))

    make_fake_get(price=1250.0, sina_price=1258.0)  # 偏差 0.64%（8/1250，1256 只有 0.48%，压不过 0.5% 阈值）
    r = rt.aggregate("stock", "600519")
    note = r["note"] or ""
    warn = next((s for s in note.split("；") if s.startswith("⚠")), "")
    check("③偏差 > 0.5% ⇒ `diverged`，屏上那一句点名两家的来源名",
          r["verifyVerdict"] == "diverged" and "tencent" in warn and "sina" in warn, note)
    # 这一枚是 10-13 下午复核补的：`note` 在 diverged 分支被屏上直接显示（`RealtimeStrip.tsx:109`），
    # 而此前那句里带着「阈值 0.5%，暂定值」＋偏差百分比＝三样面向开发者的数上了用户屏。
    check("③比率／阈值／暂定值只住机器可读位 ⇒ 屏上这一句里一个数字都不许出现",
          warn != "" and "阈值" not in warn and "暂定" not in warn and "%" not in warn
          and not any(c.isdigit() for c in warn), warn)
    check("③同一轮的数在机器可读位仍读得到（阈值 0.5／provisional true／偏差 0.64）",
          r["consensus"]["thresholdPct"] == 0.5 and r["consensus"]["provisional"] is True
          and r["consensus"]["diffPct"] == 0.64, str(r["consensus"]))

    make_fake_get()
    r = rt.aggregate("fund", "510300")  # 只有腾讯一条腿
    check("③结构性单源 ⇒ `no_second_source`＋note 说「仅一家可得」，但 `degraded` 必须仍为 false",
          r["verifyVerdict"] == "no_second_source" and "仅一家可得" in (r["note"] or "")
          and r["degraded"] is False, f"{r['verifyVerdict']} / degraded={r['degraded']}")

    make_fake_get(sina_body='var hq_str_sh600519="贵州茅台,1245.00,1240.00,1250.00";')
    r = rt.aggregate("stock", "600519")
    check("③新浪形状不对（字段数 <32）⇒ 这一腿响亮地失败、腾讯那腿照交付、共识降级为单源",
          r["price"]["source"] == "tencent" and r["verifyVerdict"] == "no_second_source"
          and r["degraded"] is True and "字段数" in str(r["sources"]), str(r["sources"]))

    # 🔁 成对：把新浪那条摘掉，verdict 必须从 agree 翻回 no_second_source（判据真的在数这一条）
    make_fake_get(price=1250.0, sina_price=1250.05)
    a = rt.aggregate("stock", "600519")["verifyVerdict"]
    r = rt.aggregate("us", "AAPL")
    b = rt.aggregate("hk", "00700")["verifyVerdict"]
    check("③🔁 反向：两源→agree，单源→no_second_source（同一枚判据两半都会翻）",
          a == "agree" and b == "no_second_source", f"{a} / {b}")
    check("③us 的现价串号守卫仍生效（`_us_fields_match` 对不匹配就拒绝冒领）",
          r["price"] is None and "mismatch" in str(r["sources"]), str(r["sources"]))


# ---------- ④ "当日"判据与空壳门 ----------

def test_today_gate_and_empty_shell() -> None:
    make_fake_get(minute_day=TODAY_COMPACT)
    r = rt.aggregate("stock", "600519")
    check("④分时归属日 == 北京今日 ⇒ `hasTodayData:true`（判据①唯一的那个真值）",
          r["hasTodayData"] is True and r["intradayDateIsToday"] is True, str(r["intraday"]["date"]))

    make_fake_get(minute_day=YESTERDAY_COMPACT)
    r = rt.aggregate("stock", "600519")
    check("④上游返回上一交易日整段序列 ⇒ `hasTodayData:false`，而 note 必须说清归属日（R16）",
          r["hasTodayData"] is False and r["intradayDateIsToday"] is False
          and "上一交易日" in (r["note"] or "") and TODAY_COMPACT[:4] in str(r["intraday"]["date"]),
          str(r["note"]))
    # 🔁 成对：把日期换回今日，同一份数据就翻回 True ⇒ 判别力住在日期上，不住在"有没有蜡烛"
    make_fake_get(minute_day=TODAY_COMPACT)
    back = rt.aggregate("stock", "600519")["hasTodayData"]
    check("④🔁 反向：只把分时归属日换回今日 ⇒ `hasTodayData` 翻回 true（「有没有返回蜡烛」确实不是判据）",
          back is True, str(back))

    make_fake_get(minute_rows=["0930 1250.01 183 22875182.71"])
    r = rt.aggregate("stock", "600519")
    check("④空壳门：只给一根（CR9-44 实测的转债分时形状）当没数据，不交出「一根的当日曲线」",
          r["intraday"] is None and r["hasTodayData"] is False and r["degraded"] is True
          and "空壳门" in str(r["sources"]), str(r["sources"]))

    make_fake_get(price=1250.0, sina_price=0.0)
    r = rt.aggregate("stock", "600519")
    check("④现价的空壳门：0 价不是价格（新浪休市/无数据那一形），这一腿失败而不是交付 0.0",
          all(s["source"] != "sina" or not s["ok"] for s in r["sources"])
          and any("空壳门" in str(s["detail"]) for s in r["sources"]), str(r["sources"]))


# ---------- ⑤ 两个节奏：只问现价时，那条贵的腿不能跟着跑 ----------

def test_parts_cadence() -> None:
    """`parts=price` 是"现价 10s／分时 60s"落到请求面上的形状（PLAN.md:172）。

    这一枚判据盯两件事：贵的分时腿**真的没跑**（域名面上看不到 `ifzq`），
    以及"这一轮没取分时"必须读成 `null`（不知道）而不是 `false`（没有当日数据）——
    后者与 `usesEastmoney` 的三态同一条纪律（CR9-67 丙），把不知道读成没有就是假结论。
    """
    make_fake_get()
    r = rt.aggregate("stock", "600519", ("price",))
    check("⑤只问现价 ⇒ `parts=[price]`、分时腿一条都没跑（域名面为证）",
          r["parts"] == ["price"] and all("ifzq" not in u for u in URLS)
          and [s["kind"] for s in r["sources"]] == ["price", "price"],
          f'{r["parts"]} / {sorted(set(u.split("/")[2] for u in URLS))}')
    check("⑤这一轮没取分时 ⇒ `hasTodayData`／`intradayDateIsToday` 是 null（不知道），不是 false（没有）",
          r["hasTodayData"] is None and r["intradayDateIsToday"] is None and r["intraday"] is None,
          str(r["hasTodayData"]))
    check("⑤只问现价、两腿都成 ⇒ `degraded:false`（没跑分时不算这一轮坏了）",
          r["degraded"] is False and r["verifyVerdict"] == "agree", str(r["degraded"]))

    make_fake_get()
    for bad in (("nope",), ("price", "nope")):
        try:
            m.quote_realtime(type="stock", code="600519", parts=",".join(bad))
            got = None
        except HTTPException as e:
            got = e.status_code
        check(f"⑤`parts` 写了不存在的一条腿＝400（不许静默按默认跑掉这一发）", got == 400, str(got))
    make_fake_get()
    full = m.quote_realtime(type="stock", code="600519", parts="price,intraday")
    check("⑤默认节奏确实是两条腿都跑（断言打在接线面＝端点签名上那个 `Query` 的默认值，"
          "这样 10-13 A 窗那类「一次取全」的调用方不必改写法）",
          full["parts"] == ["price", "intraday"] and full["intraday"] is not None
          and __import__("inspect").signature(m.quote_realtime).parameters["parts"].default.default
          == "price,intraday", str(full["parts"]))


# ---------- ⑥ 未接入的类型必须自己说为什么 ----------

def test_unwired_types_are_declared() -> None:
    for t, needle in (("bond", "转债不入首轮"), ("crypto", "加密不入首轮")):
        out = rt.aggregate(t, "x")
        check(f"⑥{t}：`wired:false` ＋ note 带着**来路**的理由（不是「这次没连上」）",
              out["wired"] is False and out["price"] is None and needle in (out["note"] or ""),
              str(out["note"]))

    make_fake_get()
    us = rt.aggregate("us", "AAPL")
    check("⑥us 的分时：现查证伪——全链对 us 只给 1d，所以定案 (e) 那句「分时 Yahoo 单源」没有实现，"
          "本轮按「没有腿可点名」记账（登记 #67）",
          us["intraday"] is None and "没有任何腿可点名" in (us["note"] or "") and us["wired"] is True,
          str(us["note"]))
    make_fake_get(price=1250.0, sina_price=1250.0)
    sina = rt.sina_fields_to_quote("600519", rt._sina_fields(_sina_body("贵州茅台", 1245.0, 1240.0, 1250.0)))
    check("⑥新浪腿的 volume 单位＝手（1830000 股 → 18300 手），timestamp 是 ISO",
          sina["volume"] == 18300.0 and sina["timestamp"] == f"{TODAY}T09:31:00" and sina["currency"] == "CNY",
          str(sina["volume"]))


# ---------- ⑦ HTTP 映射 ----------

def test_http_mapping() -> None:
    make_fake_get()
    try:
        m.quote_realtime(type="nope", code="1", parts="price,intraday")
        code = None
    except HTTPException as e:
        code = e.status_code
    check("⑦没登记过腿的类型＝400（与 `/quote` 的 unsupported type 同一口径）", code == 400, str(code))
    body = m.quote_realtime(type="stock", code="600519", parts="price,intraday")
    check("⑦取不到数不是 502：端点交 200 ＋ `degraded`（R10：一条实时条不许把详情页带崩）",
          body["type"] == "stock" and "degraded" in body)


if __name__ == "__main__":
    try:
        test_red_lines()
        test_schema_and_sources()
        test_consensus()
        test_today_gate_and_empty_shell()
        test_parts_cadence()
        test_unwired_types_are_declared()
        test_http_mapping()
    finally:
        cleanup()
    ng = [n for n, ok, _ in results if not ok]
    for n, ok, d in results:
        if not ok:
            print(f"NG  {n} — {d}")
    print(f"\n===== {len(results) - len(ng)}/{len(results)} 通过 =====")
    sys.exit(1 if ng else 0)
