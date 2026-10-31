"""CR10-6 离线单测：腾讯备源日 K 的「窄窗口漏当日根」——不依赖网络、零出网。

判别对象＝2026-10-30 实测那条现场证据：同一天、同一标的（600519），只改上游请求
`param` 里的 `s,e` 就对不上——

| 上游请求窗口 | 返回根数 | 最后一根 |
|---|---|---|
| 无 start/end | 640 | 2026-10-30 |
| `2026-09-01,2026-10-30`（59 天） | 38 | 2026-10-30 |
| `2026-10-23,2026-10-30`（7 天） | 5 | **2026-10-29** |
| `2026-10-23`（无 end） | 6 | 2026-10-30 |

⇒ 上游**按"请求键"命中一份缺当日 bar 的陈旧快照**；窄窗口是触发器。

修法（本套件钉的就是它）：**上游请求键稳定**（固定起点 + 北京今天 + 固定 count），
调用方要的 `start/end` 只在 provider 内**本地过滤**。

成对形状（C34）：
- 正向＝窄窗口也拿得到当日根（这才是缺陷本体）；
- 🔁 反向＝**上游请求参数不许再随调用方窗口变化**（把 `s_req/e_req` 改回 `s,e`
  本套必须红——那是原缺陷的写法）；
- 🔁 会红的样本＝过滤后为空必须抛 `ProviderError`，**不许静默返回空列表**
  （"窗口内没数据"与"到货 0 根"是两件事，C11 同口径）；
- 边界＝窗口外的根必须被过滤掉（本地过滤不能变成"整段回全量"）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from app.providers import tencent_provider as tp  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402

results: list[tuple[str, bool, str]] = []

# 上游"稳定宽窗口"会返回的形态：含当日的完整序列（用固定交易日构造，脱离实时）
ROWS = [
    ["2026-10-22", "1340.00", "1345.00", "1350.00", "1335.00", "40000"],
    ["2026-10-23", "1345.00", "1350.00", "1355.00", "1342.00", "41000"],
    ["2026-10-26", "1350.00", "1352.00", "1358.00", "1348.00", "42000"],
    ["2026-10-27", "1352.00", "1348.00", "1356.00", "1344.00", "43000"],
    ["2026-10-28", "1348.00", "1349.99", "1352.00", "1345.00", "41500"],
    ["2026-10-29", "1349.99", "1354.00", "1356.00", "1330.01", "42992"],
    ["2026-10-30", "1363.00", "1392.05", "1393.37", "1352.98", "59927"],
]
LAST_DATE = "2026-10-30"


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  <- {detail}" if not cond and detail else ""))


class _FakeResp:
    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": {"sh600519": {"qfqday": self._rows}}}


def _install(rows=None):
    """把 provider 的上游请求换成固定 rows，并记录**实际发出的上游 param**。"""
    sent = {}
    rows = ROWS if rows is None else rows

    def fake_get(url, params=None, **kwargs):
        sent["param"] = (params or {}).get("param")
        return _FakeResp(rows)

    tp.requests.get = fake_get
    return sent


def _kline(**kw):
    return tp.TencentProvider().get_kline("stock", "600519", interval="1d", **kw)


# ---------- 1. 正向：窄窗口也必须拿到当日根（原缺陷的正面） ----------
def _expect_in_window(lo: str, hi: str) -> int:
    """fixture 里落在 [lo,hi] 的根数——断言从数据推导，不硬编码（硬编码错一次就假红）。"""
    return sum(1 for r in ROWS if lo <= r[0] <= hi)


def test_narrow_window_keeps_today():
    sent = _install()
    r = _kline(start="20261023", end="20261030")
    c = r["candles"]
    check("正向：窄窗口 20261023..20261030 的最后一根是当日", c[-1]["date"] == LAST_DATE,
          f"last={c[-1]['date'] if c else None}")
    # ⚠️ 这个数就是缺陷的指纹：修复前上游只回 5 根（漏当日），修复后是 6 根。
    expect = _expect_in_window("2026-10-23", "2026-10-30")
    check(f"正向：窄窗口含窗口内全部根（{expect} 根，缺陷时是 {expect - 1} 根）",
          len(c) == expect, f"n={len(c)} expect={expect}")
    check("正向：首根不早于 start", c[0]["date"] == "2026-10-23", c[0]["date"])


def test_four_windows_all_keep_today():
    for st in ("20260101", "20260102", "20261023", "20261025"):
        _install()
        c = _kline(start=st, end="20261030")["candles"]
        check(f"正向：start={st} 的最后一根是当日", c[-1]["date"] == LAST_DATE,
              f"last={c[-1]['date'] if c else None}")


# ---------- 2. 🔁 反向：上游请求键不许随调用方窗口漂移 ----------
def _parse_param(param: str) -> list[str]:
    """`sh600519,day,2015-01-01,2026-10-30,1200,qfq` → 六段列表。"""
    return str(param or "").split(",")


def test_upstream_key_is_stable():
    sent_a = _install()
    _kline(start="20261023", end="20261030")
    pa = sent_a.get("param")

    sent_b = _install()
    _kline(start="20260901", end="20261030")
    pb = sent_b.get("param")

    check("🔁 反向：两个不同调用窗口发出的上游 param 必须逐字相同", pa == pb,
          f"a={pa} b={pb}")

    parts = _parse_param(pa)
    check("🔁 反向：上游 param 形如 sym,day,start,end,count,qfq", len(parts) == 6, str(pa))
    if len(parts) == 6:
        check("🔁 反向：上游起点固定 2015-01-01（不取调用方 start）",
              parts[2] == "2015-01-01", str(pa))
        check("🔁 反向：上游终点＝北京今天（不取调用方 end）",
              parts[3] == tp._beijing_today_iso(), f"param_end={parts[3]} today={tp._beijing_today_iso()}")
        check("🔁 反向：上游 count 固定 1200（不随窗口长度变）", parts[4] == "1200", str(pa))
        check("🔁 反向：上游 param 里不出现窄窗口的 2026-10-23",
              "2026-10-23" not in str(pa), str(pa))


# ---------- 3. 边界：窗口外必须被过滤 ----------
def test_filters_outside_window():
    _install()
    c = _kline(start="20261026", end="20261029")["candles"]
    dates = [x["date"] for x in c]
    check("边界：窗口外的根被过滤（4 根）", len(c) == 4, f"n={len(c)} dates={dates}")
    check("边界：首根＝start 当天", dates[0] == "2026-10-26", dates[0])
    check("边界：末根＝end 当天", dates[-1] == "2026-10-29", dates[-1])


# ---------- 4. 🔁 会红的样本：过滤后为空必须抛错 ----------
def test_empty_window_raises():
    _install()
    try:
        _kline(start="20270101", end="20270131")
        check("🔁 过滤后为空必须抛 ProviderError（不许静默返回空列表）", False, "返回了结果")
    except ProviderError as e:
        check("🔁 过滤后为空必须抛 ProviderError（不许静默返回空列表）", True, "")
    except Exception as e:  # noqa: BLE001
        check("🔁 过滤后为空必须抛 ProviderError（不许静默返回空列表）", False,
              f"{type(e).__name__}: {e}")


def test_upstream_empty_raises():
    _install(rows=[])
    try:
        _kline(start="20261001", end="20261030")
        check("🔁 上游空序列必须抛 ProviderError", False, "返回了结果")
    except ProviderError:
        check("🔁 上游空序列必须抛 ProviderError", True, "")
    except Exception as e:  # noqa: BLE001
        check("🔁 上游空序列必须抛 ProviderError", False, f"{type(e).__name__}: {e}")


# ---------- 5. 不传窗口＝全量，不回退成空 ----------
def test_no_window_returns_all():
    _install()
    c = _kline()["candles"]
    check("无窗口时返回全序列（7 根）", len(c) == 7, f"n={len(c)}")
    check("无窗口时最后一根仍是当日", c[-1]["date"] == LAST_DATE, c[-1]["date"])


if __name__ == "__main__":
    test_narrow_window_keeps_today()
    test_four_windows_all_keep_today()
    test_upstream_key_is_stable()
    test_filters_outside_window()
    test_empty_window_raises()
    test_upstream_empty_raises()
    test_no_window_returns_all()

    fails = [x for x in results if not x[1]]
    # 汇总行必须是 gate.mjs 认得的两种形态之一（`===== N/M 通过 =====` 或 `== 标题：N/M 通过 ==`）
    print(f"\n== CR10-6 腾讯日K窗口：{len(results) - len(fails)}/{len(results)} 通过 ==")
    if fails:
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:200]}")
    sys.exit(1 if fails else 0)
