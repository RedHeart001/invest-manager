"""CR10-47 离线回归：国债收益率曲线列名换形（2026-11-25）。

背景（11-25 正式探针）：`ak.bond_zh_us_rate()` 返回 9,395 行、13 列，但列名已从
裸 “3月/6月/1年/…” 改为 “中国国债收益率2年/5年/10年/30年/…”。旧解析只认裸列名，
于是整条曲线被判成 `yield curve no valid rows`，页面显示不可用。

本套件只证明解析层：
- 新列名能映射到 `2年/5年/10年/30年`，且不把 `10年-2年` 利差列误当期限；
- 旧列名仍兼容，避免一次上游换形把历史形态打死；
- 无任何可用期限时仍抛 `ProviderError`，不返空曲线冒充成功。

运行方式（无需任何服务在跑，零出网）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr10_47_yield_curve_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd  # noqa: E402

import app.providers.akshare_provider as ap  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _parse(df: pd.DataFrame) -> dict:
    orig = ap._ak_request
    ap._ak_request = lambda fn, seconds, name: df  # type: ignore[assignment]
    try:
        return ap.AkshareProvider().get_yield_curve(days=2)
    finally:
        ap._ak_request = orig  # type: ignore[assignment]


def test_new_schema() -> None:
    df = pd.DataFrame(
        [
            {
                "日期": "2026-11-23",
                "中国国债收益率2年": 1.2351,
                "中国国债收益率5年": 1.3262,
                "中国国债收益率10年": 1.5861,
                "中国国债收益率30年": 2.0499,
                "中国国债收益率10年-2年": 0.351,
                "美国国债收益率10年": 4.92,
            },
            {
                "日期": "2026-11-24",
                "中国国债收益率2年": 1.2304,
                "中国国债收益率5年": 1.3259,
                "中国国债收益率10年": 1.5853,
                "中国国债收益率30年": 2.045,
                "中国国债收益率10年-2年": 0.3549,
                "美国国债收益率10年": 4.91,
            },
        ]
    )
    out = _parse(df)
    check("CR10-47①：新列名解析出 2 行", len(out["curve"]) == 2, str(out))
    last = out["curve"][-1]
    check("CR10-47①：日期原样保留", last["date"] == "2026-11-24", str(last))
    check("CR10-47①：2年映射", last["values"].get("2年") == 1.2304, str(last["values"]))
    check(
        "CR10-47①：5/10/30 年映射",
        last["values"].get("5年") == 1.3259
        and last["values"].get("10年") == 1.5853
        and last["values"].get("30年") == 2.045,
        str(last["values"]),
    )
    check("CR10-47①：利差列不冒充期限", "10年-2年" not in last["values"], str(last["values"]))
    check("CR10-47①：来源仍标 bond-zh-us", out["source"].endswith("-bond-zh-us"), out["source"])


def test_old_schema_still_works() -> None:
    df = pd.DataFrame(
        [
            {
                "日期": "2026-10-20",
                "3月": 1.1,
                "6月": 1.2,
                "1年": 1.3,
                "3年": 1.4,
                "5年": 1.5,
                "7年": 1.6,
                "10年": 1.7,
                "30年": 1.8,
            }
        ]
    )
    out = _parse(df)
    values = out["curve"][-1]["values"]
    check("CR10-47②：旧列名仍解析", len(out["curve"]) == 1, str(out))
    check(
        "CR10-47②：旧 8 个期限全保留",
        all(values.get(t) is not None for t in ("3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年")),
        str(values),
    )


def test_no_valid_rows_still_fails_closed() -> None:
    df = pd.DataFrame([{"日期": "2026-11-24", "无关列": 1.0}])
    try:
        _parse(df)
    except ProviderError as e:
        check("CR10-47③：无可用期限仍抛 ProviderError", "no valid rows" in str(e), str(e))
    else:
        check("CR10-47③：无可用期限仍抛 ProviderError", False, "没有抛错")


def main() -> int:
    test_new_schema()
    test_old_schema_still_works()
    test_no_valid_rows_still_fails_closed()
    passed = sum(1 for _n, ok, _d in results if ok)
    fails = [x for x in results if not x[1]]
    for name, _ok, detail in fails:
        print(f"[FAIL] {name}  <- {detail[:160]}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
