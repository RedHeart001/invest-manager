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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from window_lib import (  # noqa: E402
    BEIJING,
    NoProxyOpener,
    Receipt,
    beijing_today,
    families_of,
    git_stamp,
    limiter_digest,
    read_health,
    source_freshness,
    listening_endpoint,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# 红线读数对象（10-13 下午改，任务书追加节 09:5x ① 那句「这句自证到此作废」的执行件版本）。
# 旧这一位扫的是 `quote/realtime` 这个 token 在不在＝"1a 还没开工"的证明；CR9-92 今天落了码 ⇒
# 它从此必然命中＝常红＝等于没有（闸报"不许搬的东西"＝闸失效，同一形）。
# 现在扫的是**红线本体**：实时那条链路的 URL 字面里不许出现东财家族的 host。
# ⚠️ 只认 URL 字面，不认散文：`realtime.py:70` 那句注释里写着 `fund.eastmoney`（说的是场外基金
#    为什么没腿），朴素 grep 会把它读成破线——那正是 10-12 "命中 3 条全是回执文件"那一形的反面。
REALTIME_PATH_FILES = [
    "data-service/app/realtime.py",
    "data-service/app/providers/tencent_provider.py",
]
EASTMONEY_HOST_TOKENS = ("eastmoney", "dfcfw", "push2")
# 完整三条（链注册面／域名集／`acquire` 换抛桩仍跑完整条路）住在离线套件里，本件不重造判据：
AUTHORITATIVE_SUITE = "data-service/tests/test_cr9_92_realtime.py"

URL_HOST_RE = re.compile(r"https?://([A-Za-z0-9._-]+)")

DS_KEY_SOURCES = [
    "data-service/app/main.py",
    "data-service/app/providers/chain.py",
    "data-service/app/utils/limiter.py",
    "data-service/app/sync_scheduler.py",
    "data-service/app/hotspot/scheduler.py",
    # 10-13 下午补：CR9-92 之后实时条那两条腿也是装载面。这一清单此前停在"实时路径还不存在"
    # 那一刻 ⇒ 我 18:1x 改了 `app/realtime.py`，装载证据却拿没改过的文件比大小、照判"成立"。
    # 与红线档同一形：代码面长了，仪器清单没跟着长（现查用 REALTIME_PATH_FILES，不再另抄一份）。
    *REALTIME_PATH_FILES,
]


def egress_hosts(text: str) -> list[str]:
    """URL 字面里的 host（散文里出现的裸域名不算）。"""
    return sorted(set(URL_HOST_RE.findall(text)))


def red_line_scan(root: Path, files: list[str]) -> dict:
    """逐文件报"读到的 host／其中属于东财家族的 host／文件在不在"。"""
    hosts: list[str] = []
    missing: list[str] = []
    per_file: dict[str, list[str]] = {}
    for rel in files:
        f = root / rel
        if not f.is_file():
            missing.append(rel)
            continue
        found = egress_hosts(f.read_text(encoding="utf-8", errors="replace"))
        per_file[rel] = found
        hosts.extend(found)
    em = sorted({h for h in hosts if any(t in h.lower() for t in EASTMONEY_HOST_TOKENS)})
    return {
        "scope": files,
        "hosts": sorted(set(hosts)),
        "eastmoneyHosts": em,
        # "读不到就停"：文件缺失时这一位**不能**绿——扫不到东财字面可能是因为根本没扫到文件
        # （10-12 那枚正则没锚 `const`、读回空 dict 而分母静默改变，就是同一形）。
        "pass": not em and not missing,
        "missingFiles": missing,
        "perFile": per_file,
        "authoritativeSuite": AUTHORITATIVE_SUITE,
    }


def load_evidence(ds_start: str | None, mtimes: list[dict]) -> dict:
    """装载证据（CR9-24 那一形的牙齿）：源文件 mtime 晚于进程 StartTime ⇒ 进程装的是旧码。

    ⚠️ 两侧都必须是 ISO 才能比大小。此前这里拿 PowerShell 的**中文区域格式**
    （`2026年10月13日 13:08:33`）去和 `2026-10-13T18:17:28+08:00` 比字符串，`'-' < '年'` 恒成立
    ⇒ 无论真实时序如何都判"装载成立"＝常绿，10-13 18:1x 我改完 `realtime.py` 后跑它仍报成立才发现。
    现在格式不对就直接判"读不出"，不再静默比较。
    """
    newest = max((s["mtime"] for s in mtimes if s["mtime"]), default=None)
    out: dict = {"processStartTime": ds_start, "newestSourceMtime": newest}
    if not ds_start or ds_start.startswith("<") or "Select-Object" in str(ds_start):
        out["verdict"] = "未取到 StartTime ⇒ 装载与否读不出（这一窗所有读数标『树戳未知』）"
        return out
    if "T" not in str(ds_start):
        out["verdict"] = f"StartTime 字面不是 ISO（{ds_start}）⇒ 不参与比大小（否则字符串序会恒判成立）"
        return out
    if not newest:
        out["verdict"] = "源文件 mtime 一个都没读到 ⇒ 装载与否读不出"
        return out
    out["verdict"] = (
        "源文件 mtime 晚于进程 StartTime ⇒ 进程装的是旧码（改动没生效，读数不能当新码凭据）"
        if str(newest)[:19] > str(ds_start)[:19]
        else "进程 StartTime 不早于源文件 mtime ⇒ 装载成立"
    )
    return out


def preflight(opener: NoProxyOpener, receipt: Receipt) -> dict:
    out: dict = {"beijingToday": beijing_today(), "git": git_stamp()}

    # 1) 红线自证（读数对象＝实时链路的出网 host 里有没有东财家族，见上方注释）
    out["redLine"] = red_line_scan(REPO_ROOT, REALTIME_PATH_FILES)

    # 2) 两侧监听 + 装载证据
    out["ds"] = listening_endpoint(8000)
    out["web"] = listening_endpoint(3000)
    out["sourceMtimes"] = source_freshness(DS_KEY_SOURCES)

    # 3) 基线读数（东财桶 / 落盘那本账 / 备份 / coveredDays / 实时条那一族）
    try:
        health = read_health(opener)
        out["health"] = limiter_digest(health)
        # `realtime-obs` 是 observe-only 族（红线③：实时路径不许出现 20s 排队，所以它只 `observe()`）。
        # 这一位的 granted／denied 一旦非零＝有人让实时条去 acquire 了桶 ⇒ 红线破了。
        # 读不到这一族 ⇒ 记 None 并写清原因，**不判破线**（没人打开那一屏时它本就不该出现在清单里）。
        out["realtimeFamily"] = _family_verdict(health)
        out["loadEvidence"] = load_evidence(out["ds"].get("processStartTime"), out["sourceMtimes"])
    except Exception as e:
        out["health"] = None
        out["healthError"] = f"{type(e).__name__}: {e}"
        out["realtimeFamily"] = None

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
    print(f"  红线（{len(r['scope'])} 枚实时链路文件的 URL host）：读到 {r['hosts']}")
    print(f"    ⇒ 其中东财家族＝{r['eastmoneyHosts'] or '无'} ⇒ {'未破线 ✅' if r['pass'] else '已破线 ⚠️'}"
          + (f"｜文件缺失＝{r['missingFiles']}" if r["missingFiles"] else ""))
    print(f"    完整三条断言（链注册面／域名集／acquire 抛桩）住在 {r['authoritativeSuite']}")
    fam = out.get("realtimeFamily")
    if fam is None:
        print(f"  realtime-obs 族＝读不到（{out.get('healthError') or '这一族不在清单里＝没人打开过那一屏'}）⇒ 不判破线")
    else:
        print(f"  realtime-obs 族＝seenTotal {fam['seenTotal']}｜granted {fam['granted']}／denied {fam['denied']}"
              f" ⇒ {'⚠️ 出现 acquire＝红线③破了' if fam['acquireDetected'] else '只有 observe＝红线③成立'}"
              f"｜seen＝{json.dumps(fam['seen'], ensure_ascii=False)}")
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
        {"name": "realtime-obs", "cooldown": 0.0, "consecutiveFailures": 0, "granted": 0,
         "denied": 0, "seen": {"realtime.price.tencent.stock": 6, "realtime.price.sina.stock": 6},
         "seenTotal": 12},
    ],
    "limitersDurable": {"eastmoney": {"granted": 9, "denied": 1}},
    "limitersWindow": {"coveredDays": ["2026-10-11", "2026-10-12"], "keptDays": 2},
    "dbBackup": {"lastRun": "2026-10-12T03:30:00", "nextRun": "2026-10-13T03:30:00",
                 "lastError": None, "fromDisk": True},
}


def _family_verdict(health: dict) -> dict | None:
    """从 `/health` 那一族里读出"实时条有没有碰过桶"（preflight 第 3 步用的同一份判据）。"""
    obs = families_of(health).get("realtime-obs")
    return (
        None if obs is None
        else {"granted": obs.get("granted"), "denied": obs.get("denied"),
              "seen": obs.get("seen"), "seenTotal": obs.get("seenTotal"),
              "acquireDetected": bool(obs.get("granted")) or bool(obs.get("denied"))}
    )


def selftest() -> int:
    """断言分三族：① 取数面读得出／`limiters` 是列表不是字典（上一窗就是把形状读错的那一族）／
    cooldown>0 会被读成"该停手"而不是"没这个键"；② 红线档换了读数对象后的判别力（URL 认、散文不认、
    文件缺失不许判绿）；③ `realtime-obs` 那一族的 observe/acquire 两半都会翻。"""
    checks: list[tuple[str, bool]] = []

    def ck(name: str, cond: bool) -> None:
        checks.append((name, cond))
        print(f"  {'PASS' if cond else 'FAIL'} {name}")

    d = limiter_digest(FIXTURE_HEALTH)
    for name, got, want in (
        ("东财 cooldown", d["eastmoneyCooldown"], 12.5),
        ("东财 granted", d["eastmoneyGranted"], 44),
        ("coveredDays 宽度", d["coveredDays"], ["2026-10-11", "2026-10-12"]),
        ("族清单", d["familiesPresent"], ["akshare-obs", "eastmoney", "realtime-obs"]),
        ("备份 fromDisk", d["dbBackup"]["fromDisk"], True),
    ):
        ck(f"{name}＝{want}（读到 {got}）", got == want)
    # 反向样本：缺 limiters 时不得读成"冷却为 0"（读成 0＝保险丝假绿）
    d2 = limiter_digest({"version": "x"})
    ck(f"无 limiters 时 cooldown 读成 None 而不是 0＝{d2['eastmoneyCooldown']}", d2["eastmoneyCooldown"] is None)

    # ② 红线档：只认 URL 字面里的 host。这三枚是这次换读数对象的判别力证明。
    ck("URL 字面里的东财 host ⇒ 判破线",
       egress_hosts('u = "https://push2.eastmoney.com/a?b=1"') == ["push2.eastmoney.com"])
    ck("散文里提 `fund.eastmoney`（没有 URL 字面）⇒ 不算出网 host，不判破线",
       egress_hosts("# 场外基金净值全在 fund.eastmoney，所以这一类没有腿") == [])
    tmp = Path(__file__).resolve().parent / "_redline_selftest.py"
    tmp.write_text('URL = "https://push2.eastmoney.com/x"\n', encoding="utf-8")
    try:
        r = red_line_scan(REPO_ROOT, [f"test-script/{tmp.name}"])
        ck("植入一枚含东财 URL 的实时链路文件 ⇒ 扫描抓到并判破线",
           r["eastmoneyHosts"] == ["push2.eastmoney.com"] and r["pass"] is False, )
    finally:
        tmp.unlink()
    r = red_line_scan(REPO_ROOT, REALTIME_PATH_FILES)
    ck("现查仓库：实时链路两枚文件都在位、host 集合非空、且无东财家族 ⇒ 未破线",
       not r["missingFiles"] and bool(r["hosts"]) and r["pass"] is True)
    r = red_line_scan(REPO_ROOT, ["data-service/app/does_not_exist.py"])
    ck("文件读不到 ⇒ 判红而不是判绿（读不到就停，别把空扫描当证据）",
       r["pass"] is False and r["missingFiles"] == ["data-service/app/does_not_exist.py"])

    # ③ `realtime-obs` 那一族：observe-only 成立 ⇔ 出现 acquire 就响亮地报破线
    fam = _family_verdict(FIXTURE_HEALTH)
    ck("fixture 里 realtime-obs 只有 observe ⇒ acquireDetected False",
       fam is not None and fam["acquireDetected"] is False and fam["seenTotal"] == 12)
    boom = {"limiters": [{"name": "realtime-obs", "granted": 1, "denied": 0, "seen": {}, "seenTotal": 0,
                          "cooldown": 0.0, "consecutiveFailures": 0}]}
    ck("🔁 反向：granted 变 1 ⇒ acquireDetected True（这一族一旦碰桶就点名）",
       _family_verdict(boom)["acquireDetected"] is True)
    ck("这一族缺席（没人打开过那一屏）⇒ 读成 None 而不是判破线", _family_verdict({"limiters": []}) is None)

    # ④ 装载证据：这一档此前是**常绿**的（拿中文区域格式的 StartTime 与 ISO mtime 比字符串）。
    mtimes = [{"path": "data-service/app/realtime.py", "mtime": "2026-10-13T18:17:28+08:00"}]
    ck("装载：源文件 mtime 晚于进程 StartTime ⇒ 判『进程装的是旧码』",
       load_evidence("2026-10-13T13:08:33", mtimes)["verdict"].startswith("源文件 mtime 晚于进程"))
    ck("装载：进程 StartTime 晚于源文件 mtime ⇒ 判『装载成立』（两半都会翻）",
       load_evidence("2026-10-13T18:20:00", mtimes)["verdict"].startswith("进程 StartTime 不早于"))
    # 这一枚就是旧实现会假绿的那一例：区域格式（中文）的 StartTime 一律不许拿去比大小
    v = load_evidence("2026年10月13日 13:08:33", mtimes)["verdict"]
    ck("装载：StartTime 是中文区域格式 ⇒ 判『读不出』而不是判『成立』（旧实现就在这儿恒绿）",
       "读不出" in v or "不参与比大小" in v)
    ck("装载：StartTime 缺失 ⇒ 读不出而不是成立", load_evidence(None, mtimes)["verdict"].startswith("未取到"))
    ck("锁步：实时链路那几枚文件必须在装载清单里（否则改了它们，装载证据读的是别的文件）",
       all(p in DS_KEY_SOURCES for p in REALTIME_PATH_FILES))

    passed = sum(1 for _, ok in checks if ok)
    print(f"\nselftest {passed}/{len(checks)} PASS")
    return 0 if all(ok for _, ok in checks) else 1


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
    fam = out.get("realtimeFamily") or {}
    reasons = []
    if not out["redLine"]["pass"]:
        reasons.append(
            f"实时链路文件的 URL host 里出现东财家族＝{out['redLine']['eastmoneyHosts']}"
            if out["redLine"]["eastmoneyHosts"]
            else f"实时链路文件读不到＝{out['redLine']['missingFiles']}（空扫描不能当证据）"
        )
    if fam.get("acquireDetected"):
        reasons.append(f"`realtime-obs` 出现 acquire（granted {fam['granted']}／denied {fam['denied']}）⇒ 红线③破了")
    if reasons:
        print("\n⚠️ 红线破了：" + "；".join(reasons) + "\n        先停手报主人，别在这一棵树上继续买入游额度。")
        receipt.finish({"summary": "preflight", "redLine": False, "reasons": reasons})
        return 1
    receipt.finish({"summary": "preflight", "redLine": True, "hosts": out["redLine"]["hosts"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
