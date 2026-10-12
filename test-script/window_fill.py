"""P5 第 50 项三格决策表的回填件：读数只准往既定的格里填，填不进来的必须自己说为什么填不进。

这条件存在的理由＝主人 10-07 丙那句「数没到之前先把判据钉死，读数只往表里填、不再临时定标准」，
而 10-08 那一窗真正的漏不是没测，是**测到的东西被抄进了不属于它的格子**：
`verify_metric` 走的是含东财主源的全链（chain.py:67），而 OPT-3 实时区按红线**不打东财**——
所以 A2 拿到的分歧率是「主链共识参考值」，**不是**实时区的共识率。本件默认**拒填**那一格，
要填必须显式给 `--realtime-object`（届时实时区真有了自己的源集，读数对象才对得上）。

同样拒填的还有 N：`PROFILES` 里只有 `eastmoney` 与 `akshare-obs` 两族
（limiter.py:449-471，10-12 现查），腾讯/新浪**没有任何族闸** ⇒
"N × (60/TTL) ≤ 12" 那套算术管的是东财桶，而实时区不走东财 ⇒ 没有闸给 N 上界，
本件不许凭一个错对象的算术输出一个看起来像结论的数。

用法：
    python test-script/window_fill.py             # 读盘上最新回执，输出三格＋④ 的现值/拒填
    python test-script/window_fill.py --selftest  # fixture：含"该拒填的两格"与"填得进的那格"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from window_lib import RUNTIME_DIR, VERDICTS  # noqa: E402

TTL_PRESET = 10.0   # 预设值，账上明写"数没到之前不得当作已定引用"
MINUTE_PRESET = 60.0


def load_latest(pattern: str) -> list[dict]:
    files = sorted(RUNTIME_DIR.glob(pattern)) if RUNTIME_DIR.exists() else []
    if not files:
        return []
    rows = []
    for line in files[-1].read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return [r for r in rows if r.get("kind", "").startswith("a2")]


def seconds_between(a: str, b: str) -> float | None:
    try:
        return abs((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds())
    except (TypeError, ValueError):
        return None


def cell1_ttl(rows: list[dict]) -> dict:
    """格一＝现价 TTL。判据：实测最大变化间隔 ≤ TTL ⇒ 该 TTL 不跳不漏。"""
    by: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("price") is not None and r.get("status") == 200:
            by.setdefault(f"{r.get('type')}/{r.get('code')}", []).append(r)
    changes: list[float] = []
    spacings: list[float] = []
    for key, seq in by.items():
        seq.sort(key=lambda r: r.get("atBeijing") or "")
        for prev, nxt in zip(seq, seq[1:]):
            gap = seconds_between(prev.get("atBeijing"), nxt.get("atBeijing"))
            if gap is None:
                continue
            spacings.append(gap)
            if prev.get("price") != nxt.get("price"):
                changes.append(gap)
    if not by:
        return {"cell": "格一 现价 TTL", "state": "无读数", "text": "A2 里没有可用现价样本 ⇒ 不填"}
    if changes:
        bound = max(spacings)
        return {
            "cell": "格一 现价 TTL", "state": "可填",
            "maxChangeIntervalS": max(changes), "measurableBoundS": bound,
            "text": (f"实测最大变化间隔 ≤ {max(changes):.0f}s；TTL 预设 {TTL_PRESET:.0f}s "
                     f"{'盖得住' if max(changes) <= TTL_PRESET else '盖不住 ⇒ 二选一：降 TTL 或文案承认陈旧度（定档＝降 TTL，10-07 丙）'}"
                     f"｜可测上界＝采样间隔 {bound:.0f}s，比它更短的跳动本件看不见"),
        }
    bound = max(spacings) if spacings else None
    return {
        "cell": "格一 现价 TTL", "state": "有效负结果",
        "measurableBoundS": bound,
        "text": (f"两次采样价未变，采样间隔 {bound:.0f}s ⇒ 只能得出『变化间隔 > {bound:.0f}s 或今日无跳动』。"
                 f"这是粒度顶住、不是没测（10-08 那一窗同一形），不许写成『10s TTL 可用』"),
    }


def cell2_minute(rows: list[dict]) -> dict:
    """格二＝分时缓存 60s。本窗不重测：判据要的是两发 `interval=1m` 相隔 ≥65s 后分钟戳是否推进，
    而那一发在 10-08 已拿到（账上 n 36→41、末点 10:06→10:11）⇒ 这里只负责**如实指回去**。"""
    return {
        "cell": "格二 分时缓存 60s", "state": "本窗不测",
        "text": "已成立于 10-08 10:1x（账上读数 n 36→41、末点推进、序列日期==北京今日）；"
                "本窗 A 段没有 1m 两发项，若要让读数可复核需另排一发，别拿旧账当新数",
    }


def cell3_n() -> dict:
    return {
        "cell": "格三 同窗并发只数 N", "state": "拒填",
        "text": ("东财桶算术 N×(60/TTL)≤12 的对象是 eastmoney 族，而实时区按红线不打东财；"
                 "PROFILES 现只有 eastmoney/akshare-obs 两族（10-12 现查）⇒ 腾讯侧无闸可给上界，"
                 "凭错对象的算术输出 N 就是伪造结论。改判方向＝给实时区挂独立观测族先攒计数"),
    }


def cell4_divergence(rows: list[dict], realtime_object: bool) -> dict:
    kept = [r for r in rows if r.get("verifyVerdict") in VERDICTS]
    no_second = [r for r in kept if r["verifyVerdict"] == "no_second_source"]
    degraded = [r for r in kept if r.get("isDegradation")]
    agree = [r for r in kept if r["verifyVerdict"] == "agree"]
    diverged = [r for r in kept if r["verifyVerdict"] == "diverged"]
    denom = len(agree) + len(diverged)
    base = {
        "cell": "④ 跨源共识分歧率",
        "samples": len(rows),
        "parsed": len(kept),
        "denominator": denom,
        "numeratorDiverged": len(diverged),
        "rate": round(len(diverged) / denom, 4) if denom else None,
        "excludedNoSecondSource": len(no_second),
        "excludedDegradation": len(degraded),
    }
    if not denom:
        base["state"] = "无读数"
        base["text"] = "分母为 0（全被判据摘掉或没读到三态）⇒ 不输出率"
        return base
    if not realtime_object:
        base["state"] = "拒填实时区那一格"
        base["text"] = ("读数是「主链共识参考值」（verify_metric 用全链、含东财主源，chain.py:67），"
                        f"值＝{base['rate']}；OPT-3 实时区源集不含东财 ⇒ 对象不同、不许搬运。"
                        "要填实时区那一格请待该端点存在并以 --realtime-object 明示")
        return base
    base["state"] = "可填"
    base["text"] = f"读数对象＝实时区源集（调用方以 --realtime-object 担保），分歧率＝{base['rate']}"
    return base


def render(cells: list[dict]) -> None:
    print("\n== 第 50 项三格决策表 ＋ ④（回填件输出）")
    for c in cells:
        flag = {"可填": "✅", "拒填": "⛔", "拒填实时区那一格": "⛔", "无读数": "⏳",
                "有效负结果": "⚠️", "本窗不测": "➖"}.get(c["state"], "•")
        print(f"  {flag} {c['cell']}［{c['state']}］")
        print(f"     {c['text']}")
    print("\n  抄进账本时按既有纪律带日期＋出处（回执文件名），别写裸数。")


def selftest() -> int:
    checks = []

    def ck(name, cond):
        checks.append(cond)
        print(f"  {'PASS' if cond else 'FAIL'} {name}")

    rows_moved = [
        {"kind": "a2", "type": "stock", "code": "600519", "status": 200, "price": 10.0,
         "atBeijing": "2026-10-13T09:30:00+08:00", "verifyVerdict": "agree", "isDegradation": False},
        {"kind": "a2", "type": "stock", "code": "600519", "status": 200, "price": 10.2,
         "atBeijing": "2026-10-13T09:30:30+08:00", "verifyVerdict": "agree", "isDegradation": False},
    ]
    c1 = cell1_ttl(rows_moved)
    ck("价在两发之间变了 ⇒ 格一填得进且带可测上界",
       c1["state"] == "可填" and c1["maxChangeIntervalS"] == 30.0)
    c1b = cell1_ttl([{**rows_moved[0]}, {**rows_moved[1], "price": 10.0}])
    ck("价没变 ⇒ 格一输出『有效负结果』而不是『TTL 可用』",
       c1b["state"] == "有效负结果" and "不许写成" in c1b["text"])

    # ④ 的两个方向：不给 flag 必须拒填（去掉守卫就该翻回旧行为＝顺序判据的两半样本）
    c4 = cell4_divergence(rows_moved, False)
    c4y = cell4_divergence(rows_moved, True)
    ck("默认拒填实时区那一格", c4["state"] == "拒填实时区那一格" and c4["denominator"] == 2)
    ck("给了 --realtime-object 才转成可填", c4y["state"] == "可填")
    ck("两半之间读数本身没变（只变对象声明）", c4["rate"] == c4y["rate"] == 0.0)

    zero = cell4_divergence([{"kind": "a2", "verifyVerdict": "no_second_source", "status": 200}], False)
    ck("分母为 0 时不输出率", zero["state"] == "无读数" and zero["denominator"] == 0)

    degraded_only = cell4_divergence(
        [{"kind": "a2", "verifyVerdict": "agree", "isDegradation": True, "status": 200},
         {"kind": "a2", "verifyVerdict": "diverged", "isDegradation": True, "status": 200}], True)
    ck("note 含『主源不可用，已降级至』那两发被单列（分母仍算，但可见）",
       degraded_only["excludedDegradation"] == 2 and degraded_only["denominator"] == 2)

    c3 = cell3_n()
    ck("格三在腾讯无族闸的事实下拒填 N", c3["state"] == "拒填")
    ck("格二如实指回 10-08 而不是当成新读数", cell2_minute([])["state"] == "本窗不测")
    ck("没有回执文件时不编数（cell1 读空）", cell1_ttl([])["state"] == "无读数")
    print(f"\nselftest {sum(checks)}/{len(checks)} PASS")
    return 0 if all(checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--realtime-object", action="store_true",
                    help="声明本轮 A2 的读数对象就是实时区源集（默认不许）")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    rows = load_latest("windowA-a2-*.jsonl")
    if not rows:
        print(f"盘上没有 windowA-a2-*.jsonl 回执（{RUNTIME_DIR}）⇒ 各格按无读数处理，先跑 A2")
    cells = [cell1_ttl(rows), cell2_minute(rows), cell3_n(),
             cell4_divergence(rows, a.realtime_object)]
    render(cells)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
