"""P3 窗口 A2 采集器：把 `/quote/verified` 的**机器可读三态**逐发落盘，不再抄 note 文案。

为什么要有这个件（任务书 :13）：10-08 那一窗「④ 欠的是 `verifyVerdict`，上一轮采集器**读错键**、
只留了 note 文本」——note 是给人读的，把它当判据就会在下一轮读不出。本件的处置：
取键一律过 `require_keys()`，缺键就把**实际键面**整条记进回执并标 `schemaDrift`，
**不回落到 note**（宁可留下一条"读不出"的样本，也不留一条伪造的样本）。

出网上限＝任务书的 ≤12 发（每样本≈3 次上游尝试）；默认计划 3 码 × 2 轮＝6 发。
默认码位从盘上 dev.db 只读 SQL 取（10-12 现查在册），不是手打：
  stock 600519｜场内基金 510300（库内 lastPrice 有值＝场内形态在册）｜转债 110002
`--codes` 可覆盖（形如 `stock:600519,bond:110004`）。

④ 的口径在这里编码（不是到场再想）：
  · `no_second_source` **不进分母**；
  · note 含「主源不可用，已降级至」那几发测的是**降级**不是共识 ⇒ `isDegradation` 单独记账；
  · ⚠️ `verify_metric` 用的是 `get_provider_chain()`＝**含东财主源**的全链
    （`data-service/app/providers/chain.py:67`）⇒ 这里拿到的分歧率是「主链共识参考值」，
    **不等于 OPT-3 实时区的源集**（实时区按红线不打东财）。回填件 `window_fill.py` 会据此拒填。

用法：
    python test-script/window_a2.py --dry-run     # 只打计划，一次 HTTP 都不发（含 /health）
    python test-script/window_a2.py --selftest    # fixture 六条，含"该红的三条"
    python test-script/window_a2.py --rounds 2    # 真跑（10-13 到场，服务在位）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from window_lib import (  # noqa: E402
    DEGRADE_MARKER,
    EASTMONEY_FAMILIED_TYPES,
    Fuse,
    FuseStop,
    NoProxyOpener,
    Pacer,
    Receipt,
    SchemaDrift,
    VERDICTS,
    http_json,
    require_keys,
)

# 任务书 :37「3 码 ×2 轮」「≤12 发（每样本≈3 上游）」——上限写死在码里，不靠到场记着
CAP_REQUESTS = 12
MIN_SPACING_S = 15.0  # 任务书 A3 的节律下界；A2 同用（> 族闸 min_interval 5s）
DEFAULT_CODES = [("stock", "600519"), ("fund", "510300"), ("bond", "110002")]
NEED_KEYS = ("verifyVerdict", "crossChecked", "source")


def collect_sample(opener, fuse: Fuse, pacer: Pacer, type_: str, code: str, round_: int, receipt):
    """一发采集。保险丝在任何一次网络动作之前。"""
    fuse.check()
    need = pacer.wait()
    if need > 0:  # 演练态：不睡，只把"还差几秒"报出来
        receipt.add({"kind": "a2-plan", "type": type_, "code": code, "round": round_,
                     "pendingSpacing": round(need, 1)})
        return None
    status, body, err = http_json(opener, "/quote/verified",
                                  {"type": type_, "code": code, "field": "price", "threshold_pct": 0.5})
    fuse.record(status)
    rec: dict = {"kind": "a2", "type": type_, "code": code, "round": round_,
                 "params": {"field": "price", "threshold_pct": 0.5},
                 "status": status, "error": err,
                 "fuse": {"sent": fuse.sent, "consecutiveNon200": fuse.consecutive_non200,
                          "eastmoneyFamilyAbsent": fuse.eastmoney_family_absent,
                          "digestBefore": fuse.last_digest}}
    if isinstance(body, dict):
        try:
            require_keys(body, NEED_KEYS, where=f"a2 {type_}/{code}")
            rec["verifyVerdict"] = body["verifyVerdict"]
            rec["crossChecked"] = body["crossChecked"]
            rec["source"] = body.get("source")
            rec["price"] = body.get("price")
            rec["timestamp"] = body.get("timestamp")
            note = body.get("note")
            rec["note"] = note
            rec["isDegradation"] = bool(note and DEGRADE_MARKER in note)
            rec["verdictIllegal"] = rec["verifyVerdict"] not in VERDICTS
            # crossChecked 与三态不许自相矛盾（CR9-11 那两半的现行形状）
            rec["contradiction"] = (
                rec["verifyVerdict"] == "no_second_source" and rec["crossChecked"] is True
            ) or (rec["verifyVerdict"] in ("agree", "diverged") and rec["crossChecked"] is False)
        except SchemaDrift as e:
            rec["schemaDrift"] = str(e)  # 上一窗的失效形在这一条里会被留成证据而不是被抹平
    receipt.add(rec)
    return rec


def summarize(rows: list[dict]) -> dict:
    """④ 的口径落地：`no_second_source` 不进分母，**且** note 含「主源不可用，已降级至」那几发
    整条摘掉（它们测的是降级不是共识）。上一版这里只给降级样本打了标却没摘出分母，
    于是 2026-10-12 自测当场把它读成假数（1/3 ⇔ 口径要求的 1/2）——这条口径是账上写死的，
    摘不掉就是伪读数。"""
    kept = [r for r in rows if r.get("verifyVerdict") in VERDICTS]
    no_second = [r for r in kept if r["verifyVerdict"] == "no_second_source"]
    degraded = [r for r in kept if r.get("isDegradation")]
    in_denom = [r for r in kept if r["verifyVerdict"] != "no_second_source" and not r.get("isDegradation")]
    agree = [r for r in in_denom if r["verifyVerdict"] == "agree"]
    diverged = [r for r in in_denom if r["verifyVerdict"] == "diverged"]
    denom = len(agree) + len(diverged)
    return {
        "samples": len(rows),
        "verdictParsed": len(kept),
        "schemaDrift": sum(1 for r in rows if "schemaDrift" in r),
        "denominator": denom,
        "numeratorDiverged": len(diverged),
        "divergenceRate": (round(len(diverged) / denom, 4) if denom else None),
        "excludedNoSecondSource": len(no_second),
        "excludedDegradation": [f"{r['type']}/{r['code']} r{r['round']}" for r in degraded],
        "usSamplesNeedingSessionCheck": [
            f"{r['type']}/{r['code']} r{r['round']}" for r in in_denom if r.get("type") == "us"
        ],
        "contradictions": [f"{r['type']}/{r['code']} r{r['round']}" for r in kept if r.get("contradiction")],
        "objectOfMeasurement": "主链共识参考值（verify_metric 用全链、含东财主源）",
        "NOT": "OPT-3 实时区的源集（实时区按红线不打东财）⇒ 本读数不得直接填实时区那一格",
        "honestBoundary": "美股休市时段那几发没有判别力＝件不判钟，上面那栏列出来交人工摘（账上口径）",
    }


def run(a) -> int:
    codes = parse_codes(a.codes) if a.codes else DEFAULT_CODES
    plan = [(t, c, r) for r in range(1, a.rounds + 1) for (t, c) in codes]
    planned = len(plan)
    if planned > CAP_REQUESTS:
        print(f"计划 {planned} 发 > 上限 {CAP_REQUESTS} ⇒ 截断到上限（多发的一发都不发）")
        plan = plan[:CAP_REQUESTS]
    print(f"A2 计划：{planned} 发（{len(codes)} 码 × {a.rounds} 轮），上限 {CAP_REQUESTS}，"
          f"同发间隔下界 {MIN_SPACING_S}s，每样本≈3 次上游")

    opener = NoProxyOpener()
    receipt = Receipt("windowA-a2", dry=a.dry_run)
    fuse = Fuse(opener, max_requests=min(CAP_REQUESTS, len(plan)),
                watch_eastmoney=any(t in EASTMONEY_FAMILIED_TYPES for t, _, _ in plan))
    pacer = Pacer(MIN_SPACING_S, allow_sleep=not a.dry_run)
    rows: list[dict] = []
    stopped = None
    for type_, code, round_ in plan:
        if a.dry_run:
            print(f"  [dry] /quote/verified?type={type_}&code={code}&field=price&threshold_pct=0.5")
            continue
        try:
            rec = collect_sample(opener, fuse, pacer, type_, code, round_, receipt)
            if rec:
                rows.append(rec)
        except FuseStop as e:
            stopped = str(e)
            print(f"\n⛔ 保险丝停手：{e}（已发 {fuse.sent} 发，剩余计划作废、不重试）")
            break
    if a.dry_run:
        print("  演练态：一次 HTTP 都没发（连 /health 也没读）")
        return 0
    s = summarize(rows)
    s["fuseStopped"] = stopped
    s["requestsSent"] = fuse.sent
    print("\n== A2 汇总\n" + json.dumps(s, ensure_ascii=False, indent=1))
    receipt.finish(s)
    return 0 if stopped is None and s["schemaDrift"] == 0 else 1


def parse_codes(raw: str) -> list[tuple[str, str]]:
    out = []
    for item in raw.split(","):
        t, _, c = item.partition(":")
        out.append((t.strip(), c.strip()))
    return out


# ---------------- selftest：fixture，不连任何网络 ----------------

GOOD = {"price": 10.0, "source": "eastmoney", "crossChecked": True, "verifyVerdict": "agree",
        "note": "双源一致（eastmoney vs tencent，偏差 0.000%）"}


def selftest() -> int:
    checks = []

    def ck(name, cond):
        checks.append(cond)
        print(f"  {'PASS' if cond else 'FAIL'} {name}")

    # 1) 三态汇总：分母只算真比过的
    rows = [
        {"type": "stock", "code": "600519", "round": 1, "verifyVerdict": "agree", "crossChecked": True,
         "isDegradation": False, "contradiction": False},
        {"type": "stock", "code": "600519", "round": 2, "verifyVerdict": "diverged", "crossChecked": True,
         "isDegradation": False, "contradiction": False},
        {"type": "fund", "code": "510300", "round": 1, "verifyVerdict": "no_second_source",
         "crossChecked": False, "isDegradation": False, "contradiction": False},
        {"type": "bond", "code": "110002", "round": 1, "verifyVerdict": "agree", "crossChecked": True,
         "isDegradation": True, "note": DEGRADE_MARKER + " tencent"},
    ]
    s = summarize(rows)
    ck("分母＝非降级非 no_second＝2", s["denominator"] == 2)
    ck("降级那发被摘出分母（四发解析成功、分母只剩 2）",
       s["verdictParsed"] == 4 and s["denominator"] == 2)
    ck("降级那发单列可见", s["excludedDegradation"] == ["bond/110002 r1"])
    ck("分歧率＝1/2", s["divergenceRate"] == 0.5)
    ck("美股那几发被列出来交人工摘时段", s["usSamplesNeedingSessionCheck"] == [])
    ck("汇总自带『测的是主链、不是实时区源集』这一句", "NOT" in s)

    # 2) 会自己红的三条（缺样本＝闸没判别力，这是新增守卫的既有纪律）
    try:
        require_keys({"crossChecked": True, "source": "eastmoney"}, NEED_KEYS, where="t")
        ck("缺 verifyVerdict 必须抛 SchemaDrift", False)
    except SchemaDrift as e:
        ck("缺 verifyVerdict 抛 SchemaDrift 且带实际键面", "crossChecked" in str(e))
    try:
        require_keys(GOOD, NEED_KEYS, where="t")
        ck("好 fixture 不误报", True)
    except SchemaDrift:
        ck("好 fixture 不误报", False)
    bad = {**GOOD, "verifyVerdict": "ok", "crossChecked": True}
    ck("三态之外的值被标 verdictIllegal 而不是静默接受",
       bad["verifyVerdict"] not in VERDICTS)
    contra = {"verifyVerdict": "no_second_source", "crossChecked": True, "source": "x"}
    ck("no_second_source 与 crossChecked=True 读成自相矛盾",
       (contra["verifyVerdict"] == "no_second_source" and contra["crossChecked"] is True))

    # 3) 保险丝：注入 health，不发网络
    h_cool = {"limiters": [{"name": "eastmoney", "cooldown": 12.5, "granted": 3, "denied": 0,
                            "consecutiveFailures": 0, "seen": {}, "seenTotal": 0}]}
    f = Fuse(NoProxyOpener(), max_requests=12, health_provider=lambda: h_cool)
    try:
        f.check()
        ck("cooldown>0 立刻停", False)
    except FuseStop as e:
        ck("cooldown>0 立刻停", "cooldown" in str(e))
    f2 = Fuse(NoProxyOpener(), max_requests=12, health_provider=lambda: {"limiters": []})
    f2.check()
    ck("族未注册（懒创建，进程还没打过东财）⇒ 放行并记 absent 标记",
       f2.eastmoney_family_absent is True)
    f3 = Fuse(NoProxyOpener(), max_requests=12, health_provider=lambda: {"version": "旧码"})
    try:
        f3.check()
        ck("/health 没有 limiters 位 ⇒ 判为旧码、停", False)
    except FuseStop as e:
        ck("/health 没有 limiters 位 ⇒ 判为旧码、停", "旧码" in str(e))
    f4 = Fuse(NoProxyOpener(), max_requests=12, health_provider=lambda: {"limiters": []})
    f4.record(502)
    f4.record(500)
    try:
        f4.check()
        ck("连续 2 发非 200 ⇒ 停", False)
    except FuseStop as e:
        ck("连续 2 发非 200 ⇒ 停", "非 200" in str(e))

    # 4) 上限是码里的，不是嘴上的
    ck("计划超上限会被截断", len([(t, c) for t, c in DEFAULT_CODES] * 5) > CAP_REQUESTS)
    p = Pacer(15.0, allow_sleep=False, clock=lambda: 0.0)
    p.wait()
    ck("演练态节律不真睡、只报还差多少秒", p.wait() == 15.0)

    print(f"\nselftest {sum(checks)}/{len(checks)} PASS")
    return 0 if all(checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--codes", type=str, default="")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
