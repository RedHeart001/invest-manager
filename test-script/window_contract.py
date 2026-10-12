"""闸2 的现场腿：把 web 登记要读的那些键，对着**真响应**再核一遍，并把键面回写快照。

离线那三条腿（`web/lib/ds-contract.test.ts`）证的是"两侧的字面对得上、快照没过期"；
它拦不住"ds 少回了一个键"这种运行时形态——那一半只有真响应能答，而真响应要花钱。
所以本件默认 `--dry-run`：只打印会打哪几条、每条几发，一次 HTTP 都不发。

纪律（与 `window_a2/a3` 同一套）：
 - 走 127.0.0.1 的 data-service，**不直连上游** ⇒ 这些发会花上游额度、会动东财桶，
   所以排在 10-13 窗口里跑，跑前先看 `/health` 的桶态；`/products` 一条就是整张列表，最贵。
 - 快照只存**键面**，不存数值 ⇒ 回写文件不会把行情抄进仓库。
 - 判据是"快照里的键在真响应里一个都不能少"（改名/摘键＝红）；多出来的键不算红（CR9-31 加键不破坏调用方）。

用法：
    python test-script/window_contract.py --selftest
    python test-script/window_contract.py --dry-run
    python test-script/window_contract.py --live --only /quote,/kline      # 到场只点两条
    python test-script/window_contract.py --live --write                   # 采完回写快照
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "test-script"))

from window_lib import NoProxyOpener, Receipt, beijing_today, http_json  # noqa: E402

CONTRACT_TS = REPO_ROOT / "web" / "lib" / "ds-contract.ts"
SNAPSHOT_JSON = REPO_ROOT / "web" / "lib" / "ds-contract.snapshot.json"

# 每条真发会打几发上游（10-12 按读码估的，`--live` 之后以 `/health` 桶增量为准）
PROBES: list[dict[str, Any]] = [
    {"path": "/quote", "params": {"type": "stock", "code": "600519"}, "egress": "1 发（TTL 命中则 0）"},
    {"path": "/kline", "params": {"type": "stock", "code": "600519", "interval": "1d"}, "egress": "1 发"},
    {"path": "/quote/verified", "params": {"type": "stock", "code": "600519", "field": "price"}, "egress": "≈3 发（主源＋备源比对）"},
    {"path": "/news", "params": {"code": "600519"}, "egress": "1 发（东财新闻）"},
    {"path": "/quotes", "params": {"type": "stock", "codes": "600519"}, "egress": "1 发"},
    {"path": "/fund/holdings", "params": {"code": "510300"}, "egress": "1 发"},
    {"path": "/fund/report", "params": {"code": "510300"}, "egress": "1 发"},
    {"path": "/bond/yieldcurve", "params": {"days": "90"}, "egress": "1 发（内存缓存 30 分钟）"},
    {"path": "/products", "params": {"type": "stock"}, "egress": "整张列表＝分页多发，本窗最贵的一条"},
]
# 这两条 web 侧是透传，键面归浏览器那侧；现场腿只核对"还回不回得来"，不回写快照
PASSTHROUGH = {"/hotspots/status", "/hotspots/run", "/research/start"}


def declared_paths() -> list[str]:
    """从 `ds-contract.ts` 现查登记了哪些端点（清单的单一来源在那儿，这里不抄第二份）"""
    text = CONTRACT_TS.read_text(encoding="utf-8")
    return re.findall(r'path:\s*"(/[a-z/]+)"', text)


def key_surface(obj: Any) -> dict[str, Any]:
    """真响应 → 键面：顶层键 ＋ 每个数组字段第一行的键。"""
    if not isinstance(obj, dict):
        return {"topLevel": None, "rows": None}
    rows: dict[str, list[str]] = {}
    for k, v in obj.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            rows[k] = sorted(v[0].keys())
    return {"topLevel": sorted(obj.keys()), "rows": rows or None}


def vanished_keys(snapshot_entry: dict[str, Any] | None, surface: dict[str, Any]) -> list[str]:
    """快照里有、真响应没有 ⇒ 有人改名或摘键（这就是本件要抓的那一形）"""
    if not snapshot_entry:
        return []
    out: list[str] = []
    top = surface.get("topLevel") or []
    if snapshot_entry.get("topLevel"):
        out += [f"{k}（顶层）" for k in snapshot_entry["topLevel"] if k not in top]
    for field, keys in (snapshot_entry.get("rows") or {}).items():
        have = (surface.get("rows") or {}).get(field, [])
        out += [f"{field}[].{k}" for k in keys if k not in have]
    return out


def collect(opener: NoProxyOpener, probe: dict[str, Any], snapshot: dict[str, Any], receipt: Receipt) -> dict[str, Any]:
    status, body, err = http_json(opener, probe["path"], probe["params"])
    surface = key_surface(body)
    entry = snapshot.get("endpoints", {}).get(probe["path"])
    # 非 200 的键面不是响应键面（那是 `detail` 错误体），拿它比快照只会造假阳性
    vanished = vanished_keys(entry, surface) if status == 200 else []
    rec = {
        "path": probe["path"],
        "status": status,
        "error": err,
        "surface": surface,
        "vanished": vanished,
        "passthrough": probe["path"] in PASSTHROUGH,
        "priorCapturedAt": entry.get("capturedAt") if entry else None,
    }
    receipt.add(rec)
    return rec


def write_snapshot(snapshot: dict[str, Any], records: list[dict[str, Any]]) -> int:
    written = 0
    for r in records:
        if r["passthrough"] or r.get("status") != 200 or not isinstance(r["surface"].get("topLevel"), list):
            continue
        snapshot["endpoints"][r["path"]] = {
            "capturedAt": beijing_today(),
            "provenance": "test-script/window_contract.py --live --write（现场腿，真响应键面）",
            "topLevel": r["surface"]["topLevel"],
            "rows": r["surface"]["rows"],
        }
        written += 1
    if written:
        SNAPSHOT_JSON.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return written


def run(a: argparse.Namespace) -> int:
    declared = declared_paths()
    picks = [p for p in PROBES if (not a.only or p["path"] in a.only)]
    planned = [p["path"] for p in picks]
    print("== 登记的端点（现查 ds-contract.ts）")
    print(json.dumps({"declared": declared, "本件会点": planned, "未覆盖(透传类)": sorted(PASSTHROUGH)}, ensure_ascii=False, indent=1))
    receipt = Receipt("windowContract", dry=not a.live)
    if not a.live:
        for p in picks:
            print(f"  [dry] {p['path']} 参数={p['params']} ⇒ 出网估：{p['egress']}")
        print(f"\n[dry-run] 演练 {len(picks)} 条：一条 HTTP 都不发（连 /health 也不读）。")
        return 0
    opener = NoProxyOpener()
    snapshot = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
    records = [collect(opener, p, snapshot, receipt) for p in picks]
    bad = [r["path"] for r in records if r["vanished"]]
    s = {
        "端点": [r["path"] for r in records],
        "非200": [f'{r["path"]}={r["status"]}' for r in records if r["status"] != 200],
        "快照里有而真响应没有的键": {r["path"]: r["vanished"] for r in records if r["vanished"]},
        "回写": None,
    }
    if a.write:
        s["回写"] = f'{write_snapshot(snapshot, records)} 枚端点 → {SNAPSHOT_JSON.name}'
    print("\n== 现场腿汇总\n" + json.dumps(s, ensure_ascii=False, indent=1))
    receipt.finish(s)
    return 0 if not bad and not s["非200"] else 1


def selftest() -> int:
    checks = []

    def ck(name: str, cond: bool) -> None:
        checks.append(cond)
        print(f"  {'PASS' if cond else 'FAIL'} {name}")

    surface = key_surface({"type": "stock", "price": 1, "candles": [{"date": "d", "close": 1}], "note": None})
    ck("键面拆成顶层＋数组行，且不抄数值", surface == {
        "topLevel": ["candles", "note", "price", "type"],
        "rows": {"candles": ["close", "date"]},
    })
    entry = {"capturedAt": "2026-10-08", "topLevel": ["type", "price"], "rows": {"candles": ["date", "close", "volume"]}}
    ck("真响应少了 candles[].volume ⇒ 点名到住的那一层",
       vanished_keys(entry, surface) == ["candles[].volume"])
    ck("多出来的键不算红（CR9-31 加键不破坏调用方）",
       vanished_keys({"capturedAt": "x", "topLevel": ["type"], "rows": None}, surface) == [])
    ck("没有旧快照时不假报", vanished_keys(None, surface) == [])
    ck("非 dict 响应读成空键面而不是崩", key_surface([]) == {"topLevel": None, "rows": None})

    declared = declared_paths()
    ck("清单的单一来源在 ts 里，件内不抄第二份（现查 ≥10 条）", len(declared) >= 10)
    ck("/quote/verified 在登记之列（10-08 那一枚读错键的端点）", "/quote/verified" in declared)
    ck("现场腿的探针都对着已登记的端点",
       all(p["path"] in declared for p in PROBES))
    ck("透传类不回写快照", all(p in PASSTHROUGH for p in ["/hotspots/status", "/hotspots/run"]))
    print(f"\nselftest {sum(checks)}/{len(checks)} PASS")
    return 0 if all(checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--live", action="store_true", help="真打 127.0.0.1 的 data-service（会花上游额度）")
    ap.add_argument("--write", action="store_true", help="采完把键面回写快照 JSON")
    ap.add_argument("--only", type=str, default="", help="逗号分隔的端点子集")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    a.only = {p.strip() for p in a.only.split(",") if p.strip()}
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
