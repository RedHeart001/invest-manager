"""CR10-48 离线单测：港股实时档 `r_hk` 的符号分派边界（零出网）。

缺陷：港股详情页价格恒定滞后 15 分钟——`tencent_provider.py` 的 `_hk_symbol` 返回腾讯
**延迟档** `hk{code}`，实时档是 `r_hk{code}`。2026-11-25 盘中 120 样本实测延迟中位
15.1 分钟 → 0.0 分钟。

本套件锁的不是"改对了"，而是**边界不许被"统一"掉**——这是本次修复最容易复发的一形：

  - 现价端点：`r_hk` 与 `hk` 完全同构（78 字段、回显键带 `r_`、批量 60 只保序）⇒ 可换。
  - 分时端点：`r_` **不被识别**，返回空 `data{}` 且 **HTTP 仍是 200**（静默空）
    ⇒ 实测 0 根，而 `hk{code}` 同刻给 332 根。
  - 日K 端点：同上，0 根 vs 1200 根。

所以只要有人把 `_hk_symbol` 也改成 `r_`（"统一一下更干净"），港股分时与日K 会**静默归零**：
不报错、不 5xx，只是图表空掉。第 3、4 组用例就是对这一形的反向锁。

运行方式（无需服务，零出网）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr10_48_hk_realtime_symbol.py
"""

import os
import sys
import tempfile

# 先于 app 任何 import：观测族 `observe()` 收尾会节流落盘，落点必须是临时目录，
# 否则会把测试计数写进仓库那份 `runtime/limiter-state.json`（与 test_cr9_92_realtime 同一纪律）。
os.environ["LIMITER_STATE_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="cr1048-limiter-"), "limiter-state.json")
# TTL 归零：每组换桩响应再调 aggregate，缓存一开就会读上一枚桩的旧值＝假绿。
os.environ["REALTIME_TTL_S"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import requests as REAL_REQUESTS  # noqa: E402

import app.realtime as rt  # noqa: E402
from app.providers import tencent_provider as tp  # noqa: E402
from app.utils.timeutil import beijing_today  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


TODAY_COMPACT = beijing_today().replace("-", "")
URLS: list[str] = []
PARAMS: list[dict] = []


def _fields(price: float, prev: float, name: str = "腾讯控股", code: str = "00700",
            ts: str = "2026/11/25 14:30:00") -> list[str]:
    """腾讯 `qt.gtimg.cn` 字段数组：只填被映射的那些位，长度 78（与实网一致）。"""
    f = [""] * 78
    f[0] = "100"
    f[1] = name
    f[2] = code
    f[3] = str(price)
    f[4] = str(prev)
    f[5] = str(prev)
    f[6] = "23590022"
    f[30] = ts
    f[31] = f"{price - prev:.3f}"
    f[32] = f"{(price - prev) / prev * 100:.2f}"
    f[33] = str(max(price, prev))
    f[34] = str(min(price, prev))
    return f


class _Resp:
    def __init__(self, text: str = "", content: bytes | None = None, payload: dict | None = None):
        self.text = text
        self.content = content if content is not None else text.encode("gbk", errors="ignore")
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload or {}


class _Shim:
    def __init__(self, get):
        self.get = get


def _install(quote_price: float = 337.4, prev: float = 341.6,
             empty_quote_for: str | None = None) -> None:
    """按 URL 分派替身；`empty_quote_for` 可让某个符号返回空（模拟上游静默空）。

    分时/日K 都按**请求里的那个符号**决定回什么：这正是要锁的边界——
    请求 `r_hk00700` 就必须拿空，请求 `hk00700` 就必须有数据。
    """
    URLS.clear()
    PARAMS.clear()

    def _get(url, params=None, **kw):
        URLS.append(str(url))
        PARAMS.append({"url": str(url), "params": dict(params or {})})
        u = str(url)
        if "qt.gtimg.cn" in u:
            syms = u.split("q=")[-1].split(",")
            out = []
            for sym in syms:
                if empty_quote_for and sym == empty_quote_for:
                    continue  # 上游对不认识的符号直接不回这一行
                f = _fields(quote_price, prev, code=sym.replace("r_hk", "").replace("hk", ""))
                out.append('v_' + sym + '="' + "~".join(f) + '";')
            return _Resp(content="".join(out).encode("gbk", errors="ignore"))
        if "ifzq.gtimg.cn" in u and "minute" in u:
            sym = str((params or {}).get("code") or "")
            # 实测：`r_` 前缀不被识别 ⇒ 空 data
            if sym.startswith("r_"):
                return _Resp(payload={"data": {}})
            rows = ["0930 339.800 1352993 460186025.69", "0931 340.400 1400000 480000000.00",
                    "0932 337.400 1500000 500000000.00"]
            return _Resp(payload={"data": {sym: {"data": {"date": TODAY_COMPACT, "data": rows}}}})
        if "ifzq.gtimg.cn" in u and "fqkline" in u:
            param = str((params or {}).get("param") or "")
            sym = param.split(",")[0]
            if sym.startswith("r_"):
                return _Resp(payload={"data": {}})
            return _Resp(payload={"data": {sym: {"day": [
                ["2026-11-25", "339.8", "337.4", "348.0", "336.0", "23590022"],
            ]}}})
        raise AssertionError(f"请求了白名单外的域名：{url}")

    shim = _Shim(_get)
    tp.requests = rt.requests = shim


def cleanup() -> None:
    tp.requests = REAL_REQUESTS
    rt.requests = REAL_REQUESTS


# ---------- ① 实时区现价必须走 r_hk ----------

def test_realtime_price_uses_realtime_symbol() -> None:
    _install()
    try:
        out = rt.aggregate("hk", "00700", parts=("price",))
    finally:
        cleanup()
    quote_urls = [u for u in URLS if "qt.gtimg.cn" in u]
    check("①实时区港股现价：请求符号为 r_hk00700（不再用 15 分钟延迟档）",
          len(quote_urls) == 1 and "q=r_hk00700" in quote_urls[0],
          str(quote_urls))
    check("①实时区港股现价：价格解析正确（字段位与 hk 同构）",
          out["price"]["price"] == 337.4 and out["price"]["prevClose"] == 341.6,
          str(out.get("price")))
    check("①实时区港股现价：币种 HKD 不丢",
          out["price"]["currency"] == "HKD", str(out["price"].get("currency")))
    check("①实时区港股现价：时间戳归一到 ISO",
          out["price"]["timestamp"] == "2026-11-25T14:30:00", str(out["price"].get("timestamp")))


# ---------- ② 实时区分时腿必须仍走 hk（r_ 在分时端点静默空） ----------

def test_realtime_intraday_keeps_delayed_symbol() -> None:
    _install()
    try:
        out = rt.aggregate("hk", "00700", parts=("intraday",))
    finally:
        cleanup()
    # 分时符号在 params.code 里，不在 URL 上——按 params 断言，别按 URL 猜。
    minute_codes = [p["params"].get("code") for p in PARAMS if "minute" in p["url"]]
    check("②实时区港股分时：符号仍是 hk00700（r_ 在分时端点返回空 data）",
          minute_codes == ["hk00700"], str(minute_codes))
    check("②实时区港股分时：分时真的取到了（不是静默空）",
          out["intraday"] is not None and len(out["intraday"]["points"]) == 3,
          str(out.get("intraday")))
    check("②实时区港股分时：归属日为当日", out["intradayDateIsToday"] is True,
          str(out.get("intradayDateIsToday")))


# ---------- ③ 分时/日K 的符号入口根本没被动过 ----------

def test_shared_symbol_function_untouched() -> None:
    """`_hk_symbol` 是分时与日K 共用的那条，`r_` 会让它们静默归零 ⇒ 必须恒为 hk。"""
    check("③`_hk_symbol` 恒返回延迟档 hk（分时/日K 共用的那条，绝不可带 r_）",
          tp._hk_symbol("00700") == "hk00700", str(tp._hk_symbol("00700")))
    check("③`_symbol_for('hk', ...)` 恒返回 hk（分时与日K 走这条）",
          tp._symbol_for("hk", "00700") == "hk00700", str(tp._symbol_for("hk", "00700")))
    check("③`_quote_symbol('hk', ...)` 仍是 hk（/quote 与 /quotes 走这条，未变）",
          tp._quote_symbol("hk", "00700") == "hk00700", str(tp._quote_symbol("hk", "00700")))
    check("③`_realtime_quote_symbol('hk', ...)` 是 r_hk（只有实时区现价走这条）",
          tp._realtime_quote_symbol("hk", "00700") == "r_hk00700",
          str(tp._realtime_quote_symbol("hk", "00700")))


# ---------- ④ 日K 备源必须仍走 hk ----------

def test_kline_uses_delayed_symbol() -> None:
    URLS.clear()
    _install()
    try:
        k = tp.TencentProvider().get_kline("hk", "00700", "20261101", "20261130")
    finally:
        cleanup()
    check("④日K：符号仍是 hk00700（r_ 在日K端点返回空 data）",
          len(k["candles"]) == 1, str(k.get("candles")))
    check("④日K：解析正确（开/收/高/低）",
          k["candles"][0]["close"] == 337.4 and k["candles"][0]["low"] == 336.0,
          str(k["candles"][0]))


# ---------- ⑤ /quote 与 /quotes（列表富集、刷新）必须未被改动 ----------

def test_plain_quote_paths_unchanged() -> None:
    URLS.clear()
    _install()
    try:
        q = tp.TencentProvider().get_quote("hk", "00700")
        bulk = tp.TencentProvider().get_quotes("hk", ["00700"])
    finally:
        cleanup()
    quote_urls = [u for u in URLS if "qt.gtimg.cn" in u]
    check("⑤`get_quote`（/quote）：符号仍是 hk00700，未切实时档",
          all("q=hk00700" in u and "r_hk" not in u for u in quote_urls),
          str(quote_urls))
    check("⑤`get_quotes`（/quotes 列表富集与刷新）：符号仍是 hk00700",
          bulk.get("00700", {}).get("price") == 337.4 and q["price"] == 337.4,
          str(bulk.get("00700")))


# ---------- ⑥ r_ 空响应必须显式失败，且不许偷回延迟档 ----------

def test_empty_realtime_quote_fails_loudly() -> None:
    """上游若对 r_hk 静默空（HTTP 200 但不回这一行），必须显式失败，不许 fallback 到 hk。"""
    URLS.clear()
    _install(empty_quote_for="r_hk00700")
    try:
        out = rt.aggregate("hk", "00700", parts=("price",))
    finally:
        cleanup()
    check("⑥r_hk 空响应：现价为空（不冒领、不返回 0 价）",
          out["price"] is None, str(out.get("price")))
    check("⑥r_hk 空响应：标记 degraded（不伪装成成功）",
          out["degraded"] is True, str(out.get("degraded")))
    check("⑥r_hk 空响应：**没有**偷偷改请求延迟档 hk00700（否则延迟价格重新混入）",
          not any("q=hk00700" in u for u in URLS), str(URLS))


# ---------- ⑦ 其它类型符号映射零改动 ----------

def test_other_types_unchanged() -> None:
    check("⑦A股现价：sh600519（r_ 对 A股无效，必须不变）",
          tp._realtime_quote_symbol("stock", "600519") == "sh600519",
          str(tp._realtime_quote_symbol("stock", "600519")))
    check("⑦场内基金现价：sz159915（不变）",
          tp._realtime_quote_symbol("fund", "159915") == "sz159915",
          str(tp._realtime_quote_symbol("fund", "159915")))
    check("⑦美股现价：usAAPL（r_ 对美股无差异，保持原样）",
          tp._realtime_quote_symbol("us", "AAPL") == "usAAPL",
          str(tp._realtime_quote_symbol("us", "AAPL")))
    check("⑦港股短码补零：700 → r_hk00700",
          tp._realtime_quote_symbol("hk", "700") == "r_hk00700",
          str(tp._realtime_quote_symbol("hk", "700")))
    check("⑦港股非法码拒绝：600519（6 位）→ None",
          tp._realtime_quote_symbol("hk", "600519") is None,
          str(tp._realtime_quote_symbol("hk", "600519")))
    check("⑦港股非法码拒绝：AAPL → None",
          tp._realtime_quote_symbol("hk", "AAPL") is None,
          str(tp._realtime_quote_symbol("hk", "AAPL")))


# ---------- ⑧ 域名白名单未被扩宽 ----------

def test_no_new_hosts() -> None:
    URLS.clear()
    _install()
    try:
        rt.aggregate("hk", "00700")
    finally:
        cleanup()
    hosts = {u.split("/")[2] for u in URLS if "//" in u}
    check("⑧实时区域名面仍是腾讯这两个（没有为新档位引入新域名）",
          hosts <= {"qt.gtimg.cn", "ifzq.gtimg.cn"}, str(sorted(hosts)))


def main() -> None:
    test_realtime_price_uses_realtime_symbol()
    test_realtime_intraday_keeps_delayed_symbol()
    test_shared_symbol_function_untouched()
    test_kline_uses_delayed_symbol()
    test_plain_quote_paths_unchanged()
    test_empty_realtime_quote_fails_loudly()
    test_other_types_unchanged()
    test_no_new_hosts()

    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("\n失败项：")
        for name, _, detail in fails:
            print(f"  - {name}" + (f" — {detail}" if detail else ""))
        sys.exit(1)


if __name__ == "__main__":
    main()
