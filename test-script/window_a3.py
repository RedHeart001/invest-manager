"""P4 窗口 A3 采样器：逐类单点取「此刻到底是谁在供货」，并证明这一发确实出了网。

任务书 :38 的判据是两条——采样间隔必须 > 族闸 `min_interval 5s`（连续 burst 读不出"档"，
10-06 就栽过一次），以及 `source` 字面 ＋ `note` 是否为空。这里再加一条任务书当时**没有**的：
**每发前后各读一次 `/health` 的东财桶增量**。没有这一条，"200 ＋ source=akshare"完全可能是
自家 TTL 缓存的回声（本地 200 但一次上游都没打），那样的读数对"档"毫无判别力。
读不出增量时把限制一起写，不含糊过去（us／crypto 不经东财桶＝这一维本来就无证据）。

主源名按注册面抄（不是猜）：`akshare`＝东财（akshare_provider.py:322）、
`akshare-fund-nav`＝场外净值（`akshare_provider.py` 里那枚 `"source": f"{self.source}-fund-nav"`）、`akshare-hk`＝东财港股直连（hk_provider.py:70）、
`yfinance`＝美股主源（openbb_provider.py:80）、`coingecko`＝加密单源（crypto_provider.py:59）、
备源 `tencent`／`sina-bond`（sina_bond_provider.py:37）。

码位与 A2 同源（10-12 从 dev.db 只读 SQL 取的在册码）；**hk 00700 不在库**（hk 0 行＝CR9-26 上游态），
这一发打的是 ds 端点、与 Product 表无关，所以它有效但别拿它当"库里 hk 到货"的证据。
crypto 那一发要求 ds 是带 `HTTPS_PROXY` 起的（`main.py:12` 的 `NO_PROXY=*` 会屏蔽注册表代理）；
CoinGecko 失败时这里记的是"配置态"，不能读成"上游挂了"。

用法：
    python test-script/window_a3.py --dry-run
    python test-script/window_a3.py --selftest
    python test-script/window_a3.py            # 真跑（10-13 到场）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from window_lib import (  # noqa: E402
    EASTMONEY_FAMILIED_TYPES,
    DEGRADE_MARKER,
    Fuse,
    FuseStop,
    NoProxyOpener,
    Pacer,
    Receipt,
    SchemaDrift,
    http_json,
    limiter_digest,
    require_keys,
)

CAP_REQUESTS = 6  # 逐类各 1 发
MIN_SPACING_S = 15.0
PRIMARY_SOURCES: dict[str, set[str]] = {
    "stock": {"akshare"},
    "fund": {"akshare", "akshare-fund-nav"},
    "bond": {"akshare"},
    "hk": {"akshare-hk"},
    "us": {"yfinance"},
    "crypto": {"coingecko"},
}
DEFAULT_PLAN = [
    ("stock", "600519"),
    ("fund", "510300"),
    ("bond", "110002"),
    ("hk", "00700"),
    ("crypto", "BTC"),
    ("us", "AAPL"),
]


BACKUP_SOURCES = {"tencent", "sina-bond", "sina"}  # tencent_provider.py:138／sina_bond_provider.py:37／sina_provider.py:85


def grade(source, note, status) -> str:
    """档位按**注册面**的字面判，不按"有没有 note"猜：
    东财系字面＝主源档；腾讯/新浪系＝备源／降级档；其余原样报"未知字面"（不许硬归类）。"""
    if status != 200:
        return "失败态"
    if source is None:
        return "读不出"
    degraded = bool(note and DEGRADE_MARKER in note)
    if any(source in s for s in PRIMARY_SOURCES.values()):
        return "主源档" if not degraded else "备源／降级档"
    if source in BACKUP_SOURCES or degraded:
        return "备源／降级档"
    return f"未知源字面（{source}）"


def collect(opener, fuse, pacer, type_, code, receipt):
    fuse.check()
    need = pacer.wait()
    if need > 0:
        receipt.add({"kind": "a3-plan", "type": type_, "code": code, "pendingSpacing": round(need, 1)})
        return None
    before = limiter_digest(http_json(opener, "/health")[1] or {}) if type_ in EASTMONEY_FAMILIED_TYPES else None
    status, body, err = http_json(opener, "/quote", {"type": type_, "code": code})
    after = limiter_digest(http_json(opener, "/health")[1] or {}) if type_ in EASTMONEY_FAMILIED_TYPES else None
    fuse.record(status)

    rec: dict = {"kind": "a3", "type": type_, "code": code, "status": status, "error": err,
                 "fuse": {"sent": fuse.sent, "consecutiveNon200": fuse.consecutive_non200,
                          "eastmoneyFamilyAbsent": fuse.eastmoney_family_absent}}
    if isinstance(body, dict):
        if status == 200:
            try:
                require_keys(body, ("source",), where=f"a3 {type_}/{code}")
                rec["source"] = body.get("source")
                rec["price"] = body.get("price")
                rec["timestamp"] = body.get("timestamp")
                rec["note"] = body.get("note")
                rec["isDegradation"] = bool(rec.get("note") and DEGRADE_MARKER in rec["note"])
                rec["grade"] = grade(rec["source"], rec.get("note"), status)
            except SchemaDrift as e:
                rec["schemaDrift"] = str(e)
        else:
            # 非 200 时 ds 的 detail 必带 type/code（CR9-30），原样抄回、不改写
            rec["detail"] = body.get("detail")
            rec["grade"] = grade(None, None, status)
    if before and after:
        delta_g = _d(after["eastmoneyGranted"], before["eastmoneyGranted"])
        delta_d = _d(after["eastmoneyDenied"], before["eastmoneyDenied"])
        rec["eastmoneyDelta"] = {"granted": delta_g, "denied": delta_d}
        if status == 200 and delta_g == 0 and delta_d == 0:
            rec["possiblyCached"] = True
            rec["proofOfEgress"] = "东财桶零增量 ⇒ 这一发可能是 TTL 回声，对『档』无判别力"
        else:
            rec["proofOfEgress"] = f"东财桶 granted+{delta_g} denied+{delta_d}"
    else:
        rec["proofOfEgress"] = "该类型不经东财桶 ⇒ 出网与否无法从计数证明（这一维没证据，不是零）"
    receipt.add(rec)
    return rec


def _d(a, b):
    return (a - b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None


def summarize(rows: list[dict]) -> dict:
    per = {}
    for r in rows:
        per[f"{r['type']}/{r['code']}"] = {
            "status": r.get("status"),
            "source": r.get("source") or r.get("detail"),
            "grade": r.get("grade"),
            "note": r.get("note"),
            "egress": r.get("proofOfEgress"),
        }
    return {
        "samples": len(rows),
        "perType": per,
        "主源档": sum(1 for r in rows if r.get("grade") == "主源档"),
        "备源／降级档": sum(1 for r in rows if r.get("grade") == "备源／降级档"),
        "无判别力样本（TTL 回声或读不出）": sum(
            1 for r in rows if r.get("possiblyCached") or r.get("grade") in (None, "读不出", "失败态")
        ),
        "minSpacingS": MIN_SPACING_S,
    }


def build_plan(types: str, code: str) -> list[tuple[str, str]]:
    # #76：老写法只有 DEFAULT_PLAN 里不存在的类型才用得上 --code，给了 --types＋--code 时码被静默吞
    if not types:
        return list(DEFAULT_PLAN)
    table = dict(DEFAULT_PLAN)
    return [(t, (code or table.get(t, ""))) for t in types.split(",")]


def run(a) -> int:
    plan = [(t, c) for t, c in build_plan(a.types, a.code) if c][:CAP_REQUESTS]
    print(f"A3 计划：逐类各 1 发＝{len(plan)} 发，同发间隔下界 {MIN_SPACING_S}s（> 族闸 min_interval 5s）")
    opener = NoProxyOpener()
    receipt = Receipt("windowA-a3", dry=a.dry_run)
    if a.dry_run:
        for type_, code in plan:
            print(f"  [dry] /quote?type={type_}&code={code}"
                  f"{'' if type_ in EASTMONEY_FAMILIED_TYPES else '（不经东财桶⇒出网无计数证据）'}")
        print("  演练态：一次 HTTP 都没发（含 /health）")
        return 0
    fuse = Fuse(opener, max_requests=CAP_REQUESTS, watch_eastmoney=True)
    pacer = Pacer(MIN_SPACING_S, allow_sleep=True)
    rows, stopped = [], None
    for type_, code in plan:
        try:
            rec = collect(opener, fuse, pacer, type_, code, receipt)
            if rec:
                rows.append(rec)
        except FuseStop as e:
            stopped = str(e)
            print(f"\n⛔ 保险丝停手：{e}（已发 {fuse.sent} 发）")
            break
    s = summarize(rows)
    s["fuseStopped"] = stopped
    print("\n== A3 汇总\n" + json.dumps(s, ensure_ascii=False, indent=1))
    receipt.finish(s)
    return 0 if stopped is None else 1


def selftest() -> int:
    checks = []

    def ck(name, cond):
        checks.append(cond)
        print(f"  {'PASS' if cond else 'FAIL'} {name}")

    ck("东财系字面 ⇒ 主源档（note 为空）", grade("akshare", None, 200) == "主源档")
    ck("akshare-fund-nav 也算主源（场外净值那条腿）", grade("akshare-fund-nav", None, 200) == "主源档")
    ck("腾讯供货 ⇒ 备源／降级档", grade("tencent", DEGRADE_MARKER + " tencent", 200).startswith("备源"))
    ck("腾讯无 note 也算备源档（字面本身已说明是谁在供货）", grade("tencent", None, 200) == "备源／降级档")
    ck("东财字面却带降级句 ⇒ 不自相矛盾地当成主源，归备源档",
       grade("akshare", DEGRADE_MARKER + " tencent", 200) == "备源／降级档")
    ck("新浪转债备源认得", grade("sina-bond", None, 200) == "备源／降级档")
    ck("未知字面不硬归类，原样报出来", "未知源字面" in grade("who-knows", None, 200))
    ck("502 读成失败态而不是主源档", grade(None, None, 502) == "失败态")
    ck("yfinance/coingecko 是主源字面（美股/加密各自只有它）",
       grade("yfinance", None, 200) == "主源档" and grade("coingecko", None, 200) == "主源档")

    # TTL 回声那一形：200 但东财桶零增量 ⇒ 必须自己标出来
    rows = [
        {"type": "stock", "code": "600519", "status": 200, "source": "akshare", "grade": "主源档",
         "possiblyCached": True, "proofOfEgress": "x"},
        {"type": "us", "code": "AAPL", "status": 200, "source": "yfinance", "grade": "主源档",
         "proofOfEgress": "该类型不经东财桶"},
    ]
    s = summarize(rows)
    ck("汇总里『无判别力样本』把 TTL 回声那一发数进去了", s["无判别力样本（TTL 回声或读不出）"] == 1)
    ck("计划条数不超逐类各 1 发的上限", len(DEFAULT_PLAN) == CAP_REQUESTS)
    ck("hk 那一发在计划里被显式标注不在库（0 行）",
       any(t == "hk" for t, _ in DEFAULT_PLAN) and "00700" in [c for _, c in DEFAULT_PLAN])
    # #76 的牙齿＝两半样本：摘掉 --code 必须翻回旧行为，否则这条断言恒真
    ck("#76·甲：给了 --types 又给 --code ⇒ 码用 --code（不再被 DEFAULT_PLAN 顶掉）",
       build_plan("bond", "127116") == [("bond", "127116")])
    ck("#76·乙：只给 --types ⇒ 仍取 DEFAULT_PLAN 那只码",
       build_plan("bond", "") == [("bond", dict(DEFAULT_PLAN)["bond"])] and
       build_plan("bond", "") != [("bond", "127116")])
    ck("#76·丙：不给 --types ⇒ --code 不参与，整张默认计划原样",
       build_plan("", "127116") == list(DEFAULT_PLAN))
    print(f"\nselftest {sum(checks)}/{len(checks)} PASS")
    return 0 if all(checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--types", type=str, default="", help="逗号分隔，只跑其中几类")
    ap.add_argument("--code", type=str, default="")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
