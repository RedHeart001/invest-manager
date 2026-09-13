"""P0 阶段集成冒烟测试（对运行中的 data-service 执行）。

运行方式（先启动 uvicorn）：
    PYTHONUTF8=1 .venv/Scripts/python tests/test_p0.py

覆盖：/health、/quote（沪深创业板 + 错误路径）、/kline（区间过滤 +
数据合理性）、quote 与 kline 当日交叉验证。
"""

import json
import sys

import requests

BASE = "http://localhost:8000"
TIMEOUT = 30

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  <- {detail}" if not cond and detail else ""))


def get(path: str, **params) -> requests.Response:
    return requests.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)


# ---------- 1. health ----------
r = get("/health")
check("health 返回 200 且 status=ok", r.status_code == 200 and r.json().get("status") == "ok", r.text[:100])

# ---------- 2. quote 正常用例（沪/深/创业板） ----------
quotes = {}
for code, expected_name in [("600519", "贵州茅台"), ("000001", "平安银行"), ("300750", "宁德时代")]:
    r = get("/quote", type="stock", code=code)
    d = r.json()
    quotes[code] = d
    ok = (
        r.status_code == 200
        and d.get("name") == expected_name
        and isinstance(d.get("price"), (int, float))
        and d["price"] and d["price"] > 0
    )
    if ok:  # OHLC 合理性：low <= min(open, price) 且 high >= max(open, price)，涨跌幅 <11%
        ok = (
            d["low"] is not None and d["low"] <= min(d["open"], d["price"])
            and d["high"] >= max(d["open"], d["price"])
            and abs(d["price"] - d["prevClose"]) / d["prevClose"] < 0.11
            and d["source"] == "akshare"
            and d["timestamp"] is not None
        )
    check(f"quote {code}（{expected_name}）数据合理", ok, json.dumps(d, ensure_ascii=False)[:200])

# ---------- 3. quote 错误路径 ----------
r = get("/quote", type="stock", code="999999")
check("quote 不存在代码 → 502 + detail", r.status_code == 502 and "999999" in r.json().get("detail", ""), r.text[:150])

r = requests.get(f"{BASE}/quote", timeout=TIMEOUT)
check("quote 缺 code → 422 参数校验", r.status_code == 422, r.text[:150])

r = get("/quote", type="option", code="600519")
check("quote 不支持类型 → 400", r.status_code == 400 and "unsupported" in r.json().get("detail", ""), r.text[:150])

# ---------- 4. kline ----------
r = get("/kline", type="stock", code="600519", start="20260101")
d = r.json()
candles = d.get("candles", [])
check("kline 600519 返回 200 且数量合理(>50)", r.status_code == 200 and len(candles) > 50, f"count={len(candles)}")

dates = [c["date"] for c in candles]
check("kline 日期严格递增", all(a < b for a, b in zip(dates, dates[1:])))
check("kline start 参数过滤生效", all(c["date"] >= "2026-01-01" for c in candles))
check(
    "kline 每根 OHLC 合理（low≤min(open,close) 且 high≥max(open,close)）",
    all(c["low"] <= min(c["open"], c["close"]) and c["high"] >= max(c["open"], c["close"]) for c in candles),
)
check("kline 字段完整（volume/amount 非空）", all(c.get("volume") is not None and c.get("amount") is not None for c in candles[-30:]))

r = get("/kline", type="foo", code="600519")
check("kline 不支持类型 → 400", r.status_code == 400, r.text[:150])

# ---------- 5. quote 与 kline 当日交叉验证（收盘后 price 应等于当日 close） ----------
q = quotes.get("600519", {})
today = candles[-1] if candles else {}
if q and today:
    q_day = (q.get("timestamp") or "")[:10].replace("-", "")
    k_day = today["date"][:10].replace("-", "")
    same_day = q_day == k_day
    check(
        "交叉验证：quote.price == 当日 kline.close（同交易日）",
        same_day and abs(q["price"] - today["close"]) < 0.01,
        f"quote={q.get('price')} kline_close={today.get('close')} ts={q.get('timestamp')}",
    )
    check(
        "交叉验证：quote.high/low == 当日 kline.high/low",
        abs(q["high"] - today["high"]) < 0.01 and abs(q["low"] - today["low"]) < 0.01,
        f"quote_hl=({q.get('high')},{q.get('low')}) kline_hl=({today.get('high')},{today.get('low')})",
    )
else:
    check("交叉验证前提（quote 与 kline 均可用）", False)

# ---------- 汇总 ----------
fails = [x for x in results if not x[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
if fails:
    print("失败项：")
    for name, _, detail in fails:
        print(f"  - {name}: {detail[:150]}")
sys.exit(1 if fails else 0)
