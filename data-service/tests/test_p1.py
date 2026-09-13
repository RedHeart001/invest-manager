"""P1 集成测试：产品列表接口 + 行情覆盖（股票/场内基金/场外基金/可转债）。

运行（先启动 uvicorn）：
    cd data-service && PYTHONUTF8=1 .venv/Scripts/python tests/test_p1.py

注意：会触发少量外部请求（东财/天天基金），避免连续高频执行。
"""

import json
import sys

import requests

BASE = "http://localhost:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  <- {detail}" if not cond and detail else ""))


def get(path: str, **params) -> requests.Response:
    return requests.get(f"{BASE}{path}", params=params, timeout=180)


# ---------- 1. 产品列表 ----------
r = get("/products", type="bond")
body = r.json()
items = body.get("products") or []
check(
    "products?type=bond 返回 200 且数量 > 500",
    r.status_code == 200 and body.get("count", 0) > 500,
    f"status={r.status_code} count={body.get('count')}",
)

sample = items[0] if items else {}
check(
    "产品 schema 字段齐备",
    all(k in sample for k in ("type", "code", "name", "pinyin", "pinyinInitials", "exchange", "tags")),
    json.dumps(sample, ensure_ascii=False)[:180],
)
check(
    "可转债标签正确",
    all("可转债" in (p.get("tags") or []) for p in items[:100]),
    json.dumps(items[0], ensure_ascii=False)[:180],
)
check(
    "代码与名称无空值（抽样 200）",
    all(p["code"] and p["name"] for p in items[:200]),
)

r = get("/products", type="crypto")
# crypto 已有 CoinGecko 列表源（crypto_provider register_list）。可达时返回 200 且有数据，
# 不可达（R12 代理不可用）时返回 502 并显式降级——两者皆正确，不能写死 502。
_body = (r.json() or {}) if r.status_code == 200 else {}
check(
    "products?type=crypto 可用或显式降级（200+数据 或 502）",
    (r.status_code == 200 and len(_body.get("products") or []) > 0)
    or (r.status_code == 502),
    f"status={r.status_code} n={len(_body.get('products') or [])} body={r.text[:120]}",
)

r = get("/products", type="option")
check("products 未支持类型 → 400", r.status_code == 400, f"status={r.status_code}")

# ---------- 2. 批量行情覆盖 ----------
r = get("/quotes", type="stock", codes="600519,000001")
qs = (r.json() or {}).get("quotes") or {}
check(
    "股票批量行情 2/2 且含价格",
    len(qs) == 2 and all(q.get("price") for q in qs.values()),
    json.dumps(qs, ensure_ascii=False)[:180],
)

r = get("/quotes", type="fund", codes="158008")
q = ((r.json() or {}).get("quotes") or {}).get("158008") or {}
check(
    "场内基金（ETF）实时行情含涨跌幅",
    bool(q.get("price")) and q.get("changePct") is not None,
    json.dumps(q, ensure_ascii=False)[:180],
)

r = get("/quotes", type="fund", codes="000001")
q = ((r.json() or {}).get("quotes") or {}).get("000001") or {}
check(
    "场外基金每日净值（单位净值 + 日增长率）",
    bool(q.get("price")) and q.get("changePct") is not None and "nav" in str(q.get("source", "")),
    json.dumps(q, ensure_ascii=False)[:180],
)

# 转债行情：标的改为活跃代码段候选池（未上市/已退市转债无行情属正常，
# 2026-09-13 code review：原写死 123284 一旦退市即误报）
r = get("/quotes", type="bond", codes="123284,123283,123282,111000,113050")
_qs = (r.json() or {}).get("quotes") or {}
_hit = next((k for k, v in _qs.items() if v.get("price")), "")
check(
    "可转债实时行情可用（活跃候选任一命中）",
    bool(_hit),
    f"quotes={list(_qs.keys())} body={r.text[:150]}",
)

# ---------- 3. 单只查询（详情页用） ----------
r = get("/quote", type="fund", code="000001")
check(
    "单只场外基金 quote 可用",
    r.status_code == 200 and bool((r.json() or {}).get("price")),
    r.text[:150],
)

# ---------- 4. 边界 ----------
r = requests.get(f"{BASE}/quotes", params={"type": "stock", "codes": ""}, timeout=30)
check("quotes 空 codes → 400", r.status_code == 400, f"status={r.status_code}")

r = get("/quotes", type="option", codes="600519")
check("quotes 未支持类型 → 400", r.status_code == 400, f"status={r.status_code}")

# ---------- 汇总 ----------
fails = [x for x in results if not x[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
if fails:
    print("失败项：")
    for name, _, detail in fails:
        print(f"  - {name}: {detail[:180]}")
sys.exit(1 if fails else 0)
