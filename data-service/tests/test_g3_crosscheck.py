"""G3 离线单测：双源交叉验证（R13，批次 D）。

运行方式：
    .venv/Scripts/python tests/test_g3_crosscheck.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.providers.base import (  # noqa: E402
    BaseProvider,
    ProviderError,
    register,
    register_chain,
)
from app.providers.chain import verify_metric  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


class _P(BaseProvider):
    def __init__(self, source: str, price):
        self.source = source
        self._price = price

    def get_quote(self, type_: str, code: str) -> dict:
        if self._price is None:
            raise ProviderError(f"{self.source} no price")
        return {"source": self.source, "price": self._price}

    def get_kline(self, *a, **k) -> dict:
        raise ProviderError("n/a")


def test_within_threshold() -> None:
    register(["__cc_a"], _P("primary", 100.0))
    register_chain(["__cc_a"], _P("backup", 100.2), position=1)  # 偏差 0.2%
    r = verify_metric("__cc_a", lambda p: p.get_quote("__cc_a", "X"), field="price", threshold_pct=0.5)
    check("G3：阈值内 → crossChecked=true", r.get("crossChecked") is True)
    check("G3：阈值内 → note 标注双源一致", "双源一致" in str(r.get("note")), str(r.get("note")))
    check("G3：主源值保留", r.get("price") == 100.0, str(r.get("price")))


def test_exceeds_threshold() -> None:
    register(["__cc_b"], _P("primary", 100.0))
    register_chain(["__cc_b"], _P("backup", 105.0), position=1)  # 偏差 5%
    r = verify_metric("__cc_b", lambda p: p.get_quote("__cc_b", "X"), field="price", threshold_pct=0.5)
    check("G3：超阈值 → note 含偏差标注", "双源偏差" in str(r.get("note")), str(r.get("note")))
    check("G3：超阈值 → 显式列出两源值", "primary: 100.0" in str(r.get("note")) and "backup: 105.0" in str(r.get("note")), str(r.get("note")))


def test_backup_unavailable() -> None:
    register(["__cc_c"], _P("primary", 100.0))
    register_chain(["__cc_c"], _P("backup", None), position=1)  # 备源不可用
    r = verify_metric("__cc_c", lambda p: p.get_quote("__cc_c", "X"), field="price")
    check("G3：备源不可用不阻塞主源结果", r.get("price") == 100.0)
    check("G3：备源不可用写入说明", "不可用" in str(r.get("note")), str(r.get("note")))


def test_no_backup_source() -> None:
    register(["__cc_d"], _P("primary", 100.0))  # 无备源
    r = verify_metric("__cc_d", lambda p: p.get_quote("__cc_d", "X"), field="price")
    check("G3：无备源 → crossChecked=false 且不报错", r.get("crossChecked") is False and r.get("price") == 100.0)


if __name__ == "__main__":
    test_within_threshold()
    test_exceeds_threshold()
    test_backup_unavailable()
    test_no_backup_source()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
