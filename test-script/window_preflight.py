"""P1 前置读数器（零出网）：10-13 两窗到场先跑这一条，把"发数之前该看见的东西"一次看全。

它替掉任务书 `:23-27` 那三行手敲 curl＋手抄，并补上任务书当时**没有**的一半：
⑤ 的装载证据（`main.py` 无 `--reload` ⇒ 改动对活进程不可见，CR9-24）——
现在把「关键源文件 mtime」与「监听进程 StartTime」摆在一起比大小，
mtime 晚于 StartTime ⇒ 进程装的是旧码，这一窗的读数就不能当新码的凭据。

用法：
    python test-script/window_preflight.py            # 真读（只连 127.0.0.1，零上游）
    python test-script/window_preflight.py --selftest # 内部 fixture，不需要服务在场
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from window_lib import (  # noqa: E402
    BEIJING,
    NoProxyOpener,
    Receipt,
    beijing_today,
    git_stamp,
    limiter_digest,
    read_health,
    source_freshness,
    listening_endpoint,
)

# 红线＝OPT-3 未破线：实时端点一个字节都还不该存在。
# 注意扫描范围——10-12 实测 `grep -r quote/realtime data-service` 会命中 3 条，
# 但三条全在 `.gitignore` 覆盖的回执/`runtime/` 里（`memline.out`、`runtime/tmp-card*.txt），
# 那种"命中 3"是仪器的假阳，所以这里只扫源码扩展名并显式跳过 runtime。
RED_LINE_TOKEN = "quote/realtime"
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".mjs"}
SKIP_DIR_PARTS = {"runtime", "node_modules", ".next", "__pycache__", ".venv"}

DS_KEY_SOURCES = [
    "data-service/app/main.py",
    "data-service/app/providers/chain.py",
    "data-service/app/utils/limiter.py",
    "data-service/app/sync_scheduler.py",
    "data-service/app/hotspot/scheduler.py",
]


def red_line_scan(root: Path) -> list[str]:
    hits: list[str] = []
    for f in root.rglob("*"):
        if not f.is_file() or f.suffix not in SOURCE_SUFFIXES:
            continue
        if SKIP_DIR_PARTS & set(p.lower() for p in f.parts):
            continue
        try:
            if RED_LINE_TOKEN in f.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(f.relative_to(root)))
        except OSError:
            continue
    return hits


def preflight(opener: NoProxyOpener, receipt: Receipt) -> dict:
    out: dict = {"beijingToday": beijing_today(), "git": git_stamp()}

    # 1) 红线自证（OPT-3 未破线）
    hits = red_line_scan(Path("data-service"))
    out["redLine"] = {"token": RED_LINE_TOKEN, "hits": hits, "pass": not hits}

    # 2) 两侧监听 + 装载证据
    out["ds"] = listening_endpoint(8000)
    out["web"] = listening_endpoint(3000)
    out["sourceMtimes"] = source_freshness(DS_KEY_SOURCES)

    # 3) 基线读数（东财桶 / 落盘那本账 / 备份 / coveredDays）
    try:
        health = read_health(opener)
        out["health"] = limiter_digest(health)
        ds_start = out["ds"].get("processStartTime")
        newest = max((s["mtime"] for s in out["sourceMtimes"] if s["mtime"]), default=None)
        out["loadEvidence"] = {
            "processStartTime": ds_start,
            "newestSourceMtime": newest,
            "verdict": (
                "未取到 StartTime ⇒ 装载与否读不出（这一窗所有读数标『树戳未知』）"
                if not ds_start or ds_start.startswith("<") or "Select-Object" in str(ds_start)
                else ("源文件 mtime 晚于进程 StartTime ⇒ 进程装的是旧码"
                      if newest and str(newest) > str(ds_start)[:19]
                      else "进程 StartTime 不早于源文件 mtime ⇒ 装载成立")
            ),
        }
    except Exception as e:
        out["health"] = None
        out["healthError"] = f"{type(e).__name__}: {e}"

    # 4) web 侧在位（本地回环，零上游）
    try:
        status, body = opener.get("http://127.0.0.1:3000/api/health", {})
        out["webHealth"] = {"status": status, "body": (body or "")[:300]}
    except Exception as e:
        out["webHealth"] = {"error": f"{type(e).__name__}: {e}"}

    receipt.add(out)
    return out


def show(out: dict) -> None:
    print(f"\n== 前置读数（北京今日 {out['beijingToday']}，树 {json.dumps(out['git'], ensure_ascii=False)}）")
    r = out["redLine"]
    print(f"  红线 {r['token']}：源码命中 {len(r['hits'])} 处 ⇒ {'未破线 ✅' if r['pass'] else '已破线 ⚠️ ' + str(r['hits'])}")
    for side in ("ds", "web"):
        info = out[side]
        print(f"  {side} :{info['port']} 监听＝{'在' if info['listening'] else '不在'}"
              f"{'' if info['listening'] else '（' + str(info.get('connectError')) + '）'}"
              f"{' StartTime=' + str(info.get('processStartTime')) if info.get('processStartTime') else ''}")
    if out.get("health"):
        h = out["health"]
        print(f"  东财桶 cooldown={h['eastmoneyCooldown']} granted={h['eastmoneyGranted']} "
              f"denied={h['eastmoneyDenied']} 连续失败={h['eastmoneyConsecutiveFailures']}")
        print(f"  已注册族＝{h['familiesPresent']}｜coveredDays＝{h['coveredDays']}｜keptDays＝{h['keptDays']}")
        print(f"  dbBackup＝{json.dumps(h['dbBackup'], ensure_ascii=False, default=str)}")
    else:
        print(f"  /health 读不到：{out.get('healthError')}")
    if out.get("loadEvidence"):
        print(f"  装载证据＝{out['loadEvidence']['verdict']}")
    print(f"  web /api/health＝{json.dumps(out.get('webHealth'), ensure_ascii=False, default=str)[:200]}")


FIXTURE_HEALTH = {
    "version": "0.0.0-fixture",
    "limiters": [
        {"name": "akshare-obs", "cooldown": 0.0, "consecutiveFailures": 0, "granted": 0,
         "denied": 0, "seen": {"ak.fund_open_fund_info_em": 2}, "seenTotal": 2},
        {"name": "eastmoney", "cooldown": 12.5, "consecutiveFailures": 1, "granted": 44,
         "denied": 3, "seen": {}, "seenTotal": 0},
    ],
    "limitersDurable": {"eastmoney": {"granted": 9, "denied": 1}},
    "limitersWindow": {"coveredDays": ["2026-10-11", "2026-10-12"], "keptDays": 2},
    "dbBackup": {"lastRun": "2026-10-12T03:30:00", "nextRun": "2026-10-13T03:30:00",
                 "lastError": None, "fromDisk": True},
}


def selftest() -> int:
    """三条断言：取数面读得出／`limiters` 是列表不是字典（上一窗就是把形状读错的那一族）／
    cooldown>0 会被读成"该停手"而不是"没这个键"。"""
    fails = 0
    d = limiter_digest(FIXTURE_HEALTH)
    for name, got, want in (
        ("东财 cooldown", d["eastmoneyCooldown"], 12.5),
        ("东财 granted", d["eastmoneyGranted"], 44),
        ("coveredDays 宽度", d["coveredDays"], ["2026-10-11", "2026-10-12"]),
        ("族清单", d["familiesPresent"], ["akshare-obs", "eastmoney"]),
        ("备份 fromDisk", d["dbBackup"]["fromDisk"], True),
    ):
        ok = got == want
        fails += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'} {name}＝{got}" + ("" if ok else f"（期望 {want}）"))
    # 反向样本：缺 limiters 时不得读成"冷却为 0"（读成 0＝保险丝假绿）
    d2 = limiter_digest({"version": "x"})
    ok = d2["eastmoneyCooldown"] is None
    fails += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'} 无 limiters 时 cooldown 读成 None 而不是 0＝{d2['eastmoneyCooldown']}")
    # 红线扫描器自己的判别力：造一个含红线的临时源文件必须被抓到
    tmp = Path("data-service") / "_redline_selftest.py"
    tmp.write_text(f'# {RED_LINE_TOKEN}\n', encoding="utf-8")
    try:
        caught = red_line_scan(Path("data-service"))
        ok = "_redline_selftest.py" in caught
        fails += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'} 红线扫描抓到植入的源文件样本＝{caught}")
    finally:
        tmp.unlink()
    print(f"\nselftest {7 - fails}/7 PASS")
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="不落盘、只打印")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    opener = NoProxyOpener()
    receipt = Receipt("windowA-preflight", dry=a.dry_run)
    out = preflight(opener, receipt)
    show(out)
    if not out["redLine"]["pass"]:
        print("\n⚠️ 红线破了：OPT-3 已有人写码，任务书的前提不再成立，先停手报主人。")
        return 1
    receipt.finish({"summary": "preflight", "redLine": out["redLine"]["pass"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
