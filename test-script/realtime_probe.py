"""实时源额度探针（只读观测，不写库、不碰 data-service 进程）。

目的：给「当日实时价格区域」定轮询间隔 N 提供额度证据。测的是**耐受度/耗时/形态**，
不是"跳不跳数"——今天是周日，任何源都不会有新成交，交易日复测才能看刷新节奏。

口径：每个候选按固定间隔连发 K 次，记录成功率、P50/P95 耗时、平均字节、解析形态。
东财刻意只发 10 次 @6s（=10 次/分，落在自家 PROFILES 的 rate_per_min=12 护栏内），
避免影响当晚 23:00 的同步。
"""

from __future__ import annotations

import json
import statistics
import sys
import time

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # CR9-14：脚本自带 UTF-8 输出

UA = {"User-Agent": "Mozilla/5.0"}
SINA_REF = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}


def p_tencent_quote(text: str) -> dict:
    # v_sh600519="1~贵州茅台~600519~现价~昨收~今开~...~时间戳~"
    f = text.split("~")
    return {"name": f[1] if len(f) > 1 else None, "price": f[3] if len(f) > 3 else None, "ts": f[30] if len(f) > 30 else None}


def p_tencent_minute(text: str) -> dict:
    j = json.loads(text)
    sym = next(iter((j.get("data") or {}).values()), {})
    day = (sym.get("data") or {}).get("date")
    rows = ((sym.get("data") or {}).get("data")) or []
    return {"day": day, "bars": len(rows), "last": rows[-1].split()[1] if rows else None}


def p_sina_quote(text: str) -> dict:
    # var hq_str_sh600519="贵州茅台,开,昨收,现价,高,低,...,日期,时间,...";
    body = text.split('="', 1)[-1].rstrip('";\n')
    f = body.split(",")
    return {"name": f[0] if f else None, "price": f[3] if len(f) > 3 else None, "day": f[30] if len(f) > 30 else None}


def p_em_quote(text: str) -> dict:
    d = (json.loads(text).get("data") or {})
    return {"price": d.get("f43"), "ts": d.get("f86")}


def p_coingecko(text: str) -> dict:
    j = json.loads(text)
    return {"price": (j.get("bitcoin") or {}).get("usd")}


def p_yahoo(text: str) -> dict:
    m = (json.loads(text).get("chart") or {}).get("result") or [{}]
    ts = m[0].get("timestamp") or []
    return {"bars": len(ts), "last": time.strftime("%Y-%m-%d", time.gmtime(ts[-1])) if ts else None}


def p_binance(text: str) -> dict:
    rows = json.loads(text)
    return {"bars": len(rows), "last": time.strftime("%Y-%m-%d", time.gmtime(rows[-1][0] / 1000)) if rows else None}


CANDIDATES = [
    # 已实现链路
    ("tencent_quote_stock", "https://qt.gtimg.cn/q=sh600519", UA, p_tencent_quote, 12, 5),
    ("tencent_minute_stock", "https://ifzq.gtimg.cn/appstock/app/minute/query?code=sh600519", UA, p_tencent_minute, 12, 5),
    ("tencent_quote_hk", "https://qt.gtimg.cn/q=hk00700", UA, p_tencent_quote, 12, 5),
    ("tencent_minute_hk", "https://ifzq.gtimg.cn/appstock/app/minute/query?code=hk00700", UA, p_tencent_minute, 12, 5),
    # 新候选（未实现，先测额度与形态）
    ("sina_quote_stock", "https://hq.sinajs.cn/list=sh600519", SINA_REF, p_sina_quote, 12, 5),
    ("tencent_quote_us?", "https://qt.gtimg.cn/q=usAAPL", UA, p_tencent_quote, 6, 10),
    # 海外（需 HTTPS_PROXY）
    ("coingecko_simple", "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", UA, p_coingecko, 6, 10),
    ("yahoo_chart_1m", "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1m&range=1d", UA, p_yahoo, 6, 10),
    ("binance_kline_1m", "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=500", UA, p_binance, 6, 10),
    # 东财对照：刻意压在自家护栏内（10 次 / 60s < rate_per_min=12）
    ("eastmoney_quote_ctl", "https://push2.eastmoney.com/api/qt/stock/get?fltt=2&invt=2&fields=f43,f86&secid=1.600519", UA, p_em_quote, 10, 6),
]


def run(name: str, url: str, headers: dict, parse, n: int, gap: float) -> None:
    lat: list[float] = []
    sizes: list[int] = []
    errs: list[str] = []
    shape: dict = {}
    for i in range(n):
        t0 = time.perf_counter()
        try:
            r = requests.get(url, headers=headers, timeout=15)
            ms = (time.perf_counter() - t0) * 1000
            if r.status_code != 200:
                errs.append(f"HTTP {r.status_code}")
                continue
            shape = parse(r.text)
            lat.append(ms)
            sizes.append(len(r.content))
        except Exception as e:  # noqa: BLE001
            errs.append(f"{type(e).__name__}: {str(e)[:60]}")
        if i < n - 1:
            time.sleep(gap)
    p50 = statistics.median(lat) if lat else float("nan")
    p95 = sorted(lat)[max(0, int(len(lat) * 0.95) - 1)] if lat else float("nan")
    uniq = sorted({e.split(":")[0] for e in errs})
    print(
        f"{name:22s} ok={len(lat)}/{n} gap={gap}s  p50={p50:6.0f}ms p95={p95:6.0f}ms "
        f"bytes={int(statistics.mean(sizes)) if sizes else 0:6d}  {shape}"
        + (f"  ERR={uniq} x{len(errs)}" if errs else "")
    )
    sys.stdout.flush()


print(f"probe start {time.strftime('%Y-%m-%d %H:%M:%S')}  proxy={bool(__import__('os').environ.get('HTTPS_PROXY'))}")
for c in CANDIDATES:
    run(*c)
print("probe done", time.strftime("%H:%M:%S"))
