"""刀 C 探针：转债→正股映射到底存不存在，用一次读数回答（E-3 的 #65 里那一格）。

背景（10-12 现查）：`web/lib/events.ts` 给转债的那句"公告源暂未接入"，卡点是**映射**——
`grep 正股|stock_code|bond_stock|转股` 在 `data-service/app`＋`web/lib` 的 .py/.ts 里零命中。
没有"这只转债对应哪只股票"，转债公告就挂不到任何详情页上。所以 bond 那一刀到底做不做，
取决于一个纯事实问题：**上游那张表里有没有"正股代码"这一列**。

⚠️ 成本更正（这条件存在的首要理由）：账上原记"1 发"。`ak.bond_zh_cov()`
（`akshare/bond/bond_zh_cov.py:309`）自己先取 `result.pages` 再**逐页循环** `requests.get`
（`pageSize=500`，现册 1,052 只 ⇒ **≥3 发**），所以这一发是一条 burst，不是一发。
本件因此自带一道**请求数硬闸**：包装 `requests.get` 只数不拦，超过 `CAP_REQUESTS` 立刻抛，
把"顺手多打两页"这种形态挡在码里而不是靠人记。

直连上游、不经 data-service ⇒ **不碰它的令牌桶**（与 `realtime_probe.py` 同一纪律），
所以出网证据取我自己数到的请求数，`/health` 的东财增量在这里读不到（不是"没出网"）。

用法：
    python test-script/window_bond_map.py --selftest
    python test-script/window_bond_map.py                 # 演练态（默认）：只读盘上锁定版源码，零 HTTP
    python test-script/window_bond_map.py --live          # 真调上游（10-13 到场，且主人给字之后）

形制与 `window_contract.py` 对齐（10-13 下午改）：花钱那一侧**必须显式点名 `--live`**。
此前这里是"不带 `--dry-run` 就真调"，而 docstring 与 `test-script/README.md` 都写着 `--live`
⇒ 到场的人照文档敲 `--live` 会 argparse 报错（安全地失败），照裸敲的人则静默买上游。
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "test-script"))

from window_lib import Receipt, beijing_today  # noqa: E402

CAP_REQUESTS = 4  # 现册 1052 只 / pageSize 500 = 3 页，留 1 发余量；超了就抛
PAGE_SIZE = 500
BOND_COL = "债券代码"
STOCK_COL = "正股代码"
# 锁定版 akshare 源码里那张重命名表（`bond_zh_cov.py:343` 起）——离线能读到的最强证据
AK_SRC_GLOBS = [
    "data-service/.venv/Lib/site-packages/akshare/bond/bond_zh_cov.py",
    "data-service/.venv/lib/python*/site-packages/akshare/bond/bond_zh_cov.py",
]


class CostStop(RuntimeError):
    """请求数超过硬闸——这一发的成本必须停在纸面上算好的那个数。"""


def estimate_pages(n_rows: int) -> int:
    return max(1, math.ceil(n_rows / PAGE_SIZE))


def offline_evidence() -> dict[str, Any]:
    """零出网读盘：锁定版 akshare 的那张列名重命名表里有没有 `正股代码`。

    这只证明"库内锁定的这一版会产出这一列"，不证明"今天上游真给非空值"——后者归 `--live`。
    """
    out: dict[str, Any] = {"sourceFile": None, "stockColInRenameTable": None, "keptColumns": []}
    for pat in AK_SRC_GLOBS:
        hits = sorted(glob.glob(str(REPO_ROOT / pat)))
        if not hits:
            continue
        out["sourceFile"] = str(Path(hits[0]).relative_to(REPO_ROOT))
        text = Path(hits[0]).read_text(encoding="utf-8", errors="replace")
        body = text.split("def bond_zh_cov(", 1)[-1]
        marker = "big_df.columns = ["
        if marker in body:
            block = body.split(marker, 1)[1].split("]", 1)[0]
            names = [
                ln.strip().strip(",").strip('"')
                for ln in block.split("\n")
                if ln.strip().startswith('"')
            ]
            out["keptColumns"] = [n for n in names if n and n != "_"]
            out["stockColInRenameTable"] = STOCK_COL in names
        break
    return out


def analyze_cov(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """纯函数：一张 `bond_zh_cov` 的行 → 映射这一格能不能填。

    三态是判据不是描述：列不存在＝这条路要先自建映射；列在但全空＝上游给了壳；
    非空且唯一＝"转债代码 → 正股代码"直接可用。
    """
    if not rows:
        return {"verdict": "零行（读不到表）", "usable": False, "rows": 0}
    cols = list(rows[0].keys())
    if STOCK_COL not in cols:
        return {
            "verdict": "列不存在：映射得先自建",
            "usable": False,
            "rows": len(rows),
            "columnsSample": cols[:12],
        }
    if BOND_COL not in cols:
        return {
            "verdict": "有正股代码列，但认不出转债代码列（键面变了）",
            "usable": False,
            "rows": len(rows),
            "columnsSample": cols[:12],
        }
    pairs = [
        (str(r.get(BOND_COL, "")).strip(), str(r.get(STOCK_COL, "")).strip())
        for r in rows
    ]
    filled = [(b, s) for b, s in pairs if b and s]
    if not filled:
        return {"verdict": "列在但全空（上游只给了壳）", "usable": False, "rows": len(rows)}
    stock_codes = {s for _, s in filled}
    return {
        "verdict": "映射可用（按正股代码建反向索引即可）",
        "usable": True,
        "rows": len(rows),
        "filledRows": len(filled),
        "distinctStocks": len(stock_codes),
        "manyToOne": len(filled) > len(stock_codes),
        "samplePairs": filled[:3],
    }


def counting_get(real_get, counter: dict[str, int]):
    """包一层 requests.get：数请求数，超过硬闸就抛（把成本停在算好的那个数上）。"""

    def wrapper(url, *a, **kw):
        counter["requests"] += 1
        if counter["requests"] > CAP_REQUESTS:
            raise CostStop(
                f"请求数超上限：{counter['requests']} > {CAP_REQUESTS}（已停手，未继续翻页）"
            )
        return real_get(url, *a, **kw)

    return wrapper


def live_run(receipt: Receipt) -> dict[str, Any]:
    import requests  # noqa: PLC0415

    # 让 app 自己配 NO_PROXY（`main.py:12` 的 `NO_PROXY=*` 保护国内直连；手设会读错形态）
    sys.path.insert(0, str(REPO_ROOT / "data-service"))
    import app.main  # noqa: F401,E402

    import akshare as ak  # noqa: PLC0415,E402

    counter = {"requests": 0}
    real_get = requests.get
    requests.get = counting_get(real_get, counter)
    err = None
    rows: list[dict[str, Any]] = []
    try:
        df = ak.bond_zh_cov()
        rows = df.to_dict("records")
    except Exception as e:  # 上游/翻页异常都要落回执，不许静默返空表
        err = f"{type(e).__name__}: {e}"
    finally:
        requests.get = real_get
    verdict = analyze_cov(rows)
    rec = {
        "atBeijing": beijing_today(),
        "requestsCounted": counter["requests"],
        "cap": CAP_REQUESTS,
        "error": err,
        **verdict,
    }
    receipt.add(rec)
    return rec


def summarize(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "读数对象": "ak.bond_zh_cov() 那张表（转债在册清单）",
        "不是读数对象": "转债公告/强赎下修事件本身——这一发只回答『映射有没有』",
        "usable": rec.get("usable"),
        "verdict": rec.get("verdict"),
        "requestsCounted": rec.get("requestsCounted"),
        "estimatedPages": None,
        "不经 ds 桶": "这一发绕过 data-service ⇒ 它的东财计数器不会为它动（不是没出网）",
        "对 #65 的作用": "usable=true ⇒ 刀 B/乙 的前置从猜测变成读数；false ⇒ bond 那一格继续挂『未接入』",
        **{k: v for k, v in rec.items() if k in ("rows", "filledRows", "distinctStocks", "samplePairs", "error")},
    }


def run(a: argparse.Namespace) -> int:
    receipt = Receipt("windowC1-covmap", dry=not a.live)
    ev = offline_evidence()
    print("== 离线证据（零出网，读盘上锁定版源码）")
    print(json.dumps(ev, ensure_ascii=False, indent=1))
    receipt.add({"kind": "offlineEvidence", **ev})
    if not a.live:
        print(
            "\n[dry-run] 真跑会发（要它：加 `--live`）：1 次 ak.bond_zh_cov() ⇒ 按 pageSize=500 逐页循环，"
            f"硬闸 {CAP_REQUESTS} 发；请求数由本件自己数（不经 ds 桶，读不到桶增量）。"
        )
        receipt.finish(summarize({"verdict": "dry-run", "usable": None, "requestsCounted": 0}))
        return 0
    rec = live_run(receipt)
    s = summarize(rec)
    s["estimatedPages"] = estimate_pages(rec.get("rows") or PAGE_SIZE)
    print("\n== C1 汇总\n" + json.dumps(s, ensure_ascii=False, indent=1))
    receipt.finish(s)
    return 0 if rec.get("error") is None else 1


def selftest() -> int:
    checks = []

    def ck(name: str, cond: bool) -> None:
        checks.append(cond)
        print(f"  {'PASS' if cond else 'FAIL'} {name}")

    ck("列不存在 ⇒ 不可用并点名列面",
       analyze_cov([{"债券代码": "110002", "债券简称": "国药转债"}])["usable"] is False)
    ck("列不存在时的判据字面", "列不存在" in analyze_cov([{"x": "1"}])["verdict"])
    ck("有正股列但全空 ⇒ 读成『上游只给了壳』而不是可用",
       analyze_cov([{BOND_COL: "110002", STOCK_COL: ""}])["verdict"].startswith("列在但全空"))
    ck("列在但认不出转债代码列 ⇒ 键面变了，不许硬用",
       analyze_cov([{"code": "110002", STOCK_COL: "600511"}])["usable"] is False)
    usable = analyze_cov([
        {BOND_COL: "110002", STOCK_COL: "600511"},
        {BOND_COL: "113009", STOCK_COL: "600905"},
    ])
    ck("非空两行 ⇒ 映射可用", usable["usable"] is True and usable["distinctStocks"] == 2)
    ck("两只转债挂同一正股 ⇒ manyToOne 记账但不判坏",
       analyze_cov([{BOND_COL: "a", STOCK_COL: "X"}, {BOND_COL: "b", STOCK_COL: "X"}])["manyToOne"] is True)
    ck("零行读成读不到表，不读成可用", analyze_cov([])["usable"] is False)

    # 成本闸：包装层超上限必须抛，且不把请求发出去
    calls: list[str] = []

    def fake_get(url, *a, **kw):
        calls.append(url)
        return "ok"

    wrapped = counting_get(fake_get, {"requests": 0})
    stopped = None
    for _ in range(CAP_REQUESTS + 2):
        try:
            wrapped("http://example.invalid/x")
        except CostStop as e:
            stopped = str(e)
            break
    ck(f"请求数到第 {CAP_REQUESTS + 1} 发即抛 CostStop", stopped is not None)
    ck("抛之后再没有新请求发出（数到的 == 上限）", len(calls) == CAP_REQUESTS)

    ck("分页估数：1052 只 / 500 ⇒ 3 发（账上原记 1 发是错的）", estimate_pages(1052) == 3)
    # 花钱那一侧必须显式点名（10-13 下午与 `window_contract.py` 对齐的形制）。
    # 这一枚是**会红的样本**：谁把 `if not a.live` 那道门拆掉，`live_run` 被换成"一调就炸"的桩后
    # 裸跑就会在这里响亮地失败——而不是等到某个到场的人敲裸命令、静默买走上游额度。
    entered: list[str] = []
    real_live_run = globals()["live_run"]

    def boom_live_run(receipt):  # noqa: ANN001
        entered.append("live_run")
        raise AssertionError("演练态不许进 live_run")

    globals()["live_run"] = boom_live_run
    try:
        rc = run(argparse.Namespace(dry_run=False, live=False))
    except AssertionError:
        rc = 1
    finally:
        globals()["live_run"] = real_live_run
    ck("不带 `--live` 的裸跑＝演练态：一次都没进 `live_run`（花钱要显式点名）", rc == 0 and not entered)
    ev = offline_evidence()
    ck("离线证据件三键齐（读不到源码时也得给出这三键）",
       set(ev.keys()) == {"sourceFile", "stockColInRenameTable", "keptColumns"})
    if ev["sourceFile"]:
        ck("锁定版源码里『正股代码』确在重命名表内（10-12 读到的形态）",
           ev["stockColInRenameTable"] is True and BOND_COL in ev["keptColumns"])
        ck("重命名表里被 akshare 抹掉的 `_` 不进 keptColumns", "_" not in ev["keptColumns"])
    print(f"\nselftest {sum(checks)}/{len(checks)} PASS")
    return 0 if all(checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="（已是默认，保留兼容旧字面）零 HTTP，只读盘上锁定版源码")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--live", action="store_true", help="真调 ak.bond_zh_cov()（会花上游额度；不给这一枚就演练）")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
