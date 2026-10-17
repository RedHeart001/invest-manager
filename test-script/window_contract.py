"""闸2 的现场腿：把 web 登记要读的那些键，对着**真响应**再核一遍，并把键面回写快照。

离线那三条腿（`web/lib/ds-contract.test.ts`）证的是"两侧的字面对得上、快照没过期"；
它拦不住"ds 少回了一个键"这种运行时形态——那一半只有真响应能答，而真响应要花钱。
所以本件默认 `--dry-run`：只打印会打哪几条、每条几发，一次 HTTP 都不发。

纪律（与 `window_a2/a3` 同一套；10-12 主人的字＝「window_contract.py 挂 Fuse＋CAP＋/products 显式点名」，
在此之前它是七件里**唯一没有停手判据**的一件）：
 - 每发之前过 `Fuse`：本机 `/health` 读东财桶，`cooldown>0` ⇒ 立刻停不重试；连续 2 发非 200 ⇒ 当场停；
   硬上限 `CAP_REQUESTS`。⚠️ **`CAP_REQUESTS` 数的是 ds 请求数，不是上游发数**（`/products` 一条就能分页
   多发，桶是按上游算的）⇒ 这条闸管"别把清单跑第二遍"，管不了"这一条几发"，逐条估数打在计划里给人看。
 - `/products`（整张列表＝分页多发，本窗最贵）**不进默认计划**，要它得 `--only /products` 显式点名。
 - 走 127.0.0.1 的 data-service，**不直连上游** ⇒ 这些发会花上游额度、会动东财桶，所以排在 10-13 窗口里跑。
 - 快照只存**键面**，不存数值 ⇒ 回写文件不会把行情抄进仓库。但它是**版本管理里的文件**，
   `--write` 之后 `web/lib/ds-contract.snapshot.json` 会变 dirty，窗口收尾要单独一笔提交。
 - 判据是"快照里的键在真响应里一个都不能少"（改名/摘键＝红）；多出来的键不算红（CR9-31 加键不破坏调用方）。
 - 覆盖面分母**从 `ds-contract.ts` 的 `NO_LIVE_PROBE` 现查**（10-12 定档＝10 枚：12 登记 − 2 枚排除；
   10-13 CR9-92 落 `/quote/realtime` ⇒ 现值 11 枚＝13 登记 − 同样那 2 枚排除），
   本件不抄第二份；`--selftest` 里"探针集合 == 分母"是一枚真牙齿 ⇒ 清单加了端点而现场腿没加探针＝自测红。

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

from window_lib import (  # noqa: E402
    Fuse,
    FuseStop,
    NoProxyOpener,
    Receipt,
    beijing_today,
    http_json,
    limiter_digest,
)

CONTRACT_TS = REPO_ROOT / "web" / "lib" / "ds-contract.ts"
SNAPSHOT_JSON = REPO_ROOT / "web" / "lib" / "ds-contract.snapshot.json"

CAP_REQUESTS = 12  # 硬闸（数的是 ds 请求数）
EXPENSIVE = {"/products"}  # 整张列表分页多发 ⇒ 不进默认计划

# 每条真发会打几发上游（10-12 按读码估的，`--live` 之后以 `/health` 桶增量为准）
PROBES: list[dict[str, Any]] = [
    {"path": "/quote", "params": {"type": "stock", "code": "600519"}, "egress": "1 发（TTL 命中则 0）"},
    {"path": "/kline", "params": {"type": "stock", "code": "600519", "interval": "1d"}, "egress": "1 发"},
    # `/quote/verified` 那条探针随 10-17 CR9-115 一起摘：它的调用方（详情页按钮与 BFF 路由）已删，
    # 端点本身仍在 ds 里，但闸2 的清单不再登记它 ⇒ 留着探针会让下面"探针集合 == 分母"那枚自测红。
    # CR9-92（10-13）新增的这一枚是**第一次对着真响应核实时区的键面**：它同时是 1a 的验收腿
    # （`sources`／`hasTodayData` 这些键在真响应里到底有没有），也是闸2 L3 那条"已知陈旧"清单的销账动作。
    {"path": "/quote/realtime", "params": {"type": "stock", "code": "600519"},
     "egress": "3 发（腾讯现价＋新浪现价＋腾讯分时＝实时区「一次取全」那一跳；10s 只问现价的那一跳是 2 发）"},
    {"path": "/news", "params": {"code": "600519"}, "egress": "1 发（东财新闻）"},
    {"path": "/quotes", "params": {"type": "stock", "codes": "600519"}, "egress": "1 发"},
    {"path": "/fund/holdings", "params": {"code": "510300"}, "egress": "1 发"},
    {"path": "/fund/report", "params": {"code": "510300"},
     "egress": "2–3 发（`akshare_provider.py:782` 公告 1 发＋`:809-817` 行业配置按年份循环 1–2 发；6h TTL）"},
    {"path": "/bond/yieldcurve", "params": {"days": "90"}, "egress": "1 发（内存缓存 30 分钟）"},
    {"path": "/hotspots/status", "params": {}, "egress": "0 发（读调度器状态，本地内存、零上游、零副作用）"},
    {"path": "/products", "params": {"type": "stock"}, "egress": "整张列表＝分页多发，本窗最贵的一条（要点名才跑）"},
]


def declared_paths() -> list[str]:
    """从 `ds-contract.ts` 现查登记了哪些端点（清单的单一来源在那儿，这里不抄第二份）"""
    text = CONTRACT_TS.read_text(encoding="utf-8")
    return re.findall(r'path:\s*"(/[a-z/]+)"', text)


def no_live_probe() -> dict[str, str]:
    """分母的排除表现查 ts（`NO_LIVE_PROBE`）——排除住在哪、为什么排除，都只有那一份。
    锚点必须带 `const`：文件头注释里也提到这个标识符，不带就匹配到注释后面第一个 `{}` 块上，
    读回来是空 dict ⇒ 分母静默变成 12，排除失效且不报错（10-12 首跑 selftest 就是这么抓到的）。"""
    text = CONTRACT_TS.read_text(encoding="utf-8")
    m = re.search(r"const\s+NO_LIVE_PROBE[^{]*\{(.*?)\n\}", text, re.S)
    if not m:
        raise SystemExit("读不到 `NO_LIVE_PROBE` ⇒ 分母无从计算（去 ds-contract.ts 确认那块还在）")
    return dict(re.findall(r'"(/[a-z/]+)"\s*:\s*"([^"]+)"', m.group(1)))


def denominator() -> list[str]:
    return [p for p in declared_paths() if p not in no_live_probe()]


def plan(only: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """→ (会跑的探针, 被「显式点名」规则挡住的昂贵探针)"""
    picks = [p for p in PROBES if (not only or p["path"] in only)]
    if not only:
        picks = [p for p in picks if p["path"] not in EXPENSIVE]
    held = [p["path"] for p in PROBES if p["path"] in EXPENSIVE and p not in picks]
    return picks, held


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
        "priorCapturedAt": entry.get("capturedAt") if entry else None,
    }
    receipt.add(rec)
    return rec


def write_snapshot(snapshot: dict[str, Any], records: list[dict[str, Any]]) -> int:
    written = 0
    for r in records:
        if r.get("status") != 200 or not isinstance(r["surface"].get("topLevel"), list):
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
    denom = denominator()
    picks, held = plan(a.only)
    print("== 登记的端点（现查 ds-contract.ts）")
    print(json.dumps({
        "declared": declared_paths(),
        "排除（各有理由，住在 NO_LIVE_PROBE）": no_live_probe(),
        "分母": len(denom),
        "本件会点": [p["path"] for p in picks],
        "被最贵规则挡住": held,
        "探针集合==分母": sorted(p["path"] for p in PROBES) == sorted(denom),
    }, ensure_ascii=False, indent=1))
    receipt = Receipt("windowContract", dry=not a.live)
    if not a.live:
        for p in picks:
            print(f"  [dry] {p['path']} 参数={p['params']} ⇒ 出网估：{p['egress']}")
        print(f"\n[dry-run] 演练 {len(picks)} 条：一条 HTTP 都不发（连 /health 也不读）。")
        if held:
            print(f"        {held} 未进默认计划（整张列表分页多发）⇒ 要它：--live --only {held[0]}")
        return 0
    opener = NoProxyOpener()
    snapshot = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
    fuse = Fuse(opener, max_requests=min(CAP_REQUESTS, len(picks)), watch_eastmoney=True)
    records: list[dict[str, Any]] = []
    stopped: str | None = None
    for p in picks:
        try:
            fuse.check()
        except FuseStop as e:
            stopped = f"{e}（已跑 {fuse.sent} 发，后面 {len(picks) - len(records)} 条未发）"
            print(f"\n⛔ 保险丝停手：{stopped}")
            break
        rec = collect(opener, p, snapshot, receipt)
        fuse.record(rec["status"])
        records.append(rec)
    bad = [r["path"] for r in records if r["vanished"]]
    s = {
        "端点": [r["path"] for r in records],
        "非200": [f'{r["path"]}={r["status"]}' for r in records if r["status"] != 200],
        "快照里有而真响应没有的键": {r["path"]: r["vanished"] for r in records if r["vanished"]},
        "保险丝": {"已发ds请求": fuse.sent, "连续非200": fuse.consecutive_non200,
                   "东财族未注册": fuse.eastmoney_family_absent, "停手": stopped},
        "东财桶末读": fuse.last_digest,
        "回写": None,
    }
    if a.write and stopped is None:
        s["回写"] = f'{write_snapshot(snapshot, records)} 枚端点 → {SNAPSHOT_JSON.name}'
    elif a.write:
        s["回写"] = "拒写（保险丝停过手＝这一轮的键面不完整，别把半截清单抄成快照）"
    print("\n== 现场腿汇总\n" + json.dumps(s, ensure_ascii=False, indent=1))
    receipt.finish(s)
    return 0 if not bad and not s["非200"] and stopped is None else 1


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
    ck("/quote/realtime 在登记之列（`verifyVerdict` 三态现在只有这一条消费方，10-08 读错键那一枚的家）",
       "/quote/realtime" in declared)
    # 这一枚是真牙齿：清单加了端点而现场腿没加探针／或探针偷偷多采一枚被排除的 ⇒ 自测红
    ck("探针集合 == 分母（分母现查 NO_LIVE_PROBE，不抄第二份）",
       sorted(p["path"] for p in PROBES) == sorted(denominator()))
    ck("分母＝10（登记 13 − 排除 3；10-17 CR9-115 撤掉 `/quote/verified` 那条登记与探针，"
       "10-16 CR9-111 那轮曾到 11；排除数不抄第二份——原来写死的 `- 2` 一加第三条排除就会假红）",
       len(denominator()) == len(declared) - len(no_live_probe()) == 10)
    ck("/hotspots/status 已挪进探针清单且零上游（0 发＝不动桶）",
       any(p["path"] == "/hotspots/status" and p["egress"].startswith("0") for p in PROBES))
    ck("有副作用的 POST 永不自动采（run 触发抓取／start 起研报）",
       not any(p["path"] in {"/hotspots/run", "/research/start"} for p in PROBES))

    picks, held = plan(set())
    ck("/products 不进默认计划", all(p["path"] != "/products" for p in picks) and held == ["/products"])
    ck("点名才跑：--only /products 会把它取回来",
       [p["path"] for p in plan({"/products"})[0]] == ["/products"])
    ck("硬上限存在且不超（CAP 数的是 ds 请求数）",
       CAP_REQUESTS >= len(picks) and len(picks) == len(denominator()) - 1)

    h_cool = {"limiters": [{"name": "eastmoney", "cooldown": 12.5, "granted": 3, "denied": 0,
                            "consecutiveFailures": 0, "seen": {}, "seenTotal": 0}]}
    f = Fuse(NoProxyOpener(), max_requests=12, health_provider=lambda: h_cool)
    try:
        f.check()
        ck("cooldown>0 第一发之前就停", False)
    except FuseStop as e:
        ck("cooldown>0 第一发之前就停", "cooldown" in str(e))
    f2 = Fuse(NoProxyOpener(), max_requests=1, health_provider=lambda: {"limiters": []})
    f2.check()
    f2.record(200)
    try:
        f2.check()
        ck("达硬上限 ⇒ 不再多发一发", False)
    except FuseStop as e:
        ck("达硬上限 ⇒ 不再多发一发", "max_requests" in str(e))
    f3 = Fuse(NoProxyOpener(), max_requests=12, health_provider=lambda: {"limiters": []})
    f3.record(502)
    f3.record(500)
    try:
        f3.check()
        ck("连续 2 发非 200 ⇒ 停", False)
    except FuseStop as e:
        ck("连续 2 发非 200 ⇒ 停", "非 200" in str(e))
    f4 = Fuse(NoProxyOpener(), max_requests=12, health_provider=lambda: {"version": "旧码"})
    try:
        f4.check()
        ck("/health 没有 limiters 位 ⇒ 判为旧码、停", False)
    except FuseStop as e:
        ck("/health 没有 limiters 位 ⇒ 判为旧码、停", "旧码" in str(e))

    print(f"\nselftest {sum(checks)}/{len(checks)} PASS")
    return 0 if all(checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--live", action="store_true", help="真打 127.0.0.1 的 data-service（会花上游额度）")
    ap.add_argument("--write", action="store_true", help="采完把键面回写快照 JSON（版本管理文件，会产生 dirty）")
    ap.add_argument("--only", type=str, default="", help="逗号分隔的端点子集（也是点名 /products 的唯一途径）")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    a.only = {p.strip() for p in a.only.split(",") if p.strip()}
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
