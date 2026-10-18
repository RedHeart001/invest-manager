"""C21 离线单测（10-18 追加九十二 刀 F）：`to_float` 的非有限值一律视同缺失。

背景＝10-18 完整性审计查出的形状：CONSTRAINTS 里 14 枚纪律**有运行时守卫却没有红测**，
删掉守卫闸1 不会红。本套闭的是 **C21**（`app/utils/num.py` 那句"NaN／±Inf 视同缺失"），
它是其中唯一一枚"纯函数＋零出网＋后果写在 docstring 里"的：非有限值一旦漏进响应，
Starlette 的 `json.dumps(allow_nan=False)` 会抛 `ValueError` ⇒ 详情页 500，
而"缺失＝剔除"类过滤同时失效（P6／09-13 review 两次踩到）。

运行方式（不需要任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_c21_num_guard.py

判别力自证（C34 成对）＝本套自带一枚 `_legacy_to_float`（**摘掉 `math.isfinite` 那道门**的
旧形状），断言它在同样六项输入上**会**放行 NaN／Inf ⇒ 证明上面那些 OK 是真咬得住的，
不是恒绿的清单。盘上真钻（改 `num.py` 再复原）另记在账上。
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14 同族：用例名带全角／符号，GBK 控制台需要自带 UTF-8 输出
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _legacy_to_float(value, default=None):
    """C21 落地**之前**的形状：只挡 TypeError／ValueError，非有限值照放行。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


NON_FINITE = ["nan", float("nan"), "inf", float("inf"), "-inf", float("-inf")]


def test_non_finite_becomes_default() -> None:
    from app.utils.num import to_float

    for v in NON_FINITE:
        check(f"C21：非有限值 {v!r} ⇒ default（不是以非 null 形式漏进响应）",
              to_float(v, default=None) is None, repr(to_float(v, default=None)))
        check(f"C21：同一输入带显式 default ⇒ 返回那个 default",
              to_float(v, default=-1.0) == -1.0, repr(to_float(v, default=-1.0)))
    check("C21：None／'-' 两形仍按缺失（既有行为，防本轮改动顺手改掉）",
          to_float(None) is None and to_float("-") is None,
          f"{to_float(None)!r} / {to_float('-')!r}")
    check("C21：正常值照收（0 与负数不能被当成缺失）",
          to_float("0") == 0.0 and to_float(-3.5) == -3.5 and to_float("2e3") == 2000.0,
          f"{to_float('0')!r} / {to_float(-3.5)!r}")


def test_response_stays_serializable() -> None:
    """docstring 承诺的那一形：载荷里不许有 NaN，否则 `allow_nan=False` 抛 ValueError＝500。"""
    from app.utils.num import to_float

    payload = {"price": to_float("nan"), "prev": to_float(float("inf")), "chg": to_float("1.25")}
    try:
        json.dumps(payload, allow_nan=False)
        ok, detail = True, ""
    except ValueError as e:  # pragma: no cover - 只在回归时出现
        ok, detail = False, f"{type(e).__name__}: {e}"
    check("C21：含非有限输入的响应可被 Starlette 那套 allow_nan=False 序列化", ok, detail)
    check("C21：缺失＝键值为 null（'缺失即剔除'类过滤的判据面），不是 NaN 那种非 null",
          payload["price"] is None and payload["prev"] is None, repr(payload))


def test_teeth_legacy_shape_passes_nan() -> None:
    """反向验证：摘掉 `math.isfinite` 那道门 ⇒ 上面每一条都该红（否则这套没牙齿）。"""
    from app.utils.num import to_float

    leaked = [v for v in NON_FINITE if _legacy_to_float(v, default=None) is not None]
    check("🔁 C21 的牙齿：旧形状会放行全部六枚非有限值（本套的 OK 由这条提供判别力）",
          len(leaked) == len(NON_FINITE), f"leaked={leaked!r}")
    try:
        json.dumps({"p": _legacy_to_float("nan")}, allow_nan=False)
        old_serializable = True
    except ValueError:
        old_serializable = False
    check("🔁 旧形状产出的正是那句承诺要拦的 500（allow_nan=False 当场抛）",
          old_serializable is False, f"old_serializable={old_serializable}")
    check("🔁 现形状与旧形状在正常值上一致（判别力只落在非有限那一侧，不是换了判据对象）",
          all(_legacy_to_float(v) == to_float(v) for v in ["1.5", "0", "-2", 3, "abc", None]),
          "正常值两侧不一致")
    check("尺自证：math.isfinite 就是那道门（本文件对它的引用不是装饰）",
          math.isfinite(1.0) and not math.isfinite(float("nan")), "")


def main() -> int:
    test_non_finite_becomes_default()
    test_response_stays_serializable()
    test_teeth_legacy_shape_passes_nan()
    passed = sum(1 for _n, ok, _d in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"[FAIL] {name}  <- {detail}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
