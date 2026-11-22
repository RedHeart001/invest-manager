"""CR10-42：港交所官方证券表作为 hk 完整独立备源，零出网反向测试。"""
from __future__ import annotations

import datetime as dt
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
os.environ["LIMITER_STATE_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="cr1042-hkex-limiter-"), "limiter-state.json")

from openpyxl import Workbook  # noqa: E402
from app.providers import hk_provider as hp  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402

results: list[tuple[str, bool, str]] = []
TODAY = dt.date(2026, 11, 22)
HEADERS = ["Stock Code", "Name of Securities", "Category", "Sub-Category"] + [None] * 14


def check(name: str, cond: object, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def workbook(rows: list[list[object]], *, chinese: bool = False, updated: str = "Updated as at 21/11/2026", header_drift: bool = False) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "ListOfSecurities"
    ws.append(["證券列表" if chinese else "List of Securities"])
    ws.append([updated.replace("Updated as at", "更新日期") if chinese else updated])
    ws.append((["股份代號", "股份名稱", "分類", "次分類"] + [None] * 14) if chinese else (["Changed Code"] + HEADERS[1:] if header_drift else HEADERS))
    for row in rows:
        ws.append(row + [None] * (18 - len(row)))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def row(code: str, name: str, category: str = "Equity") -> list[object]:
    return [code, name, category, "Equity Securities (Main Board)" if category == "Equity" else ""]


def raises(fn) -> str:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return ""


def test_official_workbook_mapping() -> None:
    en = workbook([
        row("00001", "CKH HOLDINGS"),
        row("00700", "TENCENT"),
        row("02800", "TRACKER FUND", "Exchange Traded Products"),
        row("00823", "LINK REIT", "Real Estate Investment Trusts"),
        row("04000", "BOND", "Debt Securities"),
        row("10000", "DW", "Derivative Warrants"),
        row("20000", "CBBC", "Callable Bull/Bear Contracts"),
    ])
    cn = workbook([
        row("00001", "長和"), row("00700", "騰訊控股"), row("02800", "盈富基金", "交易所買賣產品"),
        row("00823", "領展", "房地產投資信託基金"), row("04000", "債券", "債務證券"),
        row("10000", "窩輪", "衍生權證"), row("20000", "牛熊證", "牛熊證"),
    ], chinese=True)
    items, meta = hp._hkex_products(en, cn, today=TODAY)
    check("只保留与原 hk 范围对应的四类，不吞入衍生权证/牛熊证",
          [x["code"] for x in items] == ["00001", "00700", "02800", "00823", "04000"], str(items))
    check("中文官方名入库且代码补零", items[0]["name"] == "長和" and items[0]["code"] == "00001", str(items[0]))
    check("完整采集与产品分类子集分账",
          meta["acquisitionComplete"] is True and meta["productPolicySubset"] is True
          and meta["intentionalSubset"] is True and meta["declaredCount"] == 7
          and meta["acquiredCount"] == 7, str(meta))
    check("来源显式标记 HKEX 与降级", meta["source"] == "hkex-securities-list" and meta["degraded"] is True, str(meta))


def test_workbook_fail_closed() -> None:
    good_en = workbook([row("00001", "CKH"), row("00700", "TENCENT")])
    good_cn = workbook([row("00001", "長和"), row("00700", "騰訊")], chinese=True)
    check("英文表重复代码拒绝", "duplicate" in raises(lambda: hp._hkex_products(
        workbook([row("00001", "A"), row("1", "B")]), good_cn, today=TODAY)))
    check("中文表缺代码拒绝", "code set" in raises(lambda: hp._hkex_products(
        good_en, workbook([row("00001", "長和")], chinese=True), today=TODAY)))
    check("名称空白不能交付", "blank" in raises(lambda: hp._hkex_products(
        good_en, workbook([row("00001", ""), row("00700", "騰訊")], chinese=True), today=TODAY)))
    check("非法代码不能靠 zfill 变合法", "invalid" in raises(lambda: hp._hkex_products(
        workbook([row("ABC", "BAD")]), workbook([row("ABC", "壞")], chinese=True), today=TODAY)))
    check("表头漂移拒绝", "header" in raises(lambda: hp._hkex_products(
        workbook([row("00001", "A")], header_drift=True), good_cn, today=TODAY)))
    stale_cn = workbook([row("00001", "長和")], chinese=True, updated="Updated as at 01/11/2026")
    check("过期的官方快照不能冒充当前名单", "stale" in raises(lambda: hp._hkex_products(
        workbook([row("00001", "A")], updated="Updated as at 01/11/2026"), stale_cn, today=TODAY)))
    next_day = workbook([row("00001", "A")], updated="Updated as at 23/11/2026")
    next_day_cn = workbook([row("00001", "長和")], chinese=True, updated="Updated as at 23/11/2026")
    check("周末预发布下一交易日是合法快照", len(hp._hkex_products(next_day, next_day_cn, today=TODAY)[0]) == 1)
    far_future = workbook([row("00001", "A")], updated="Updated as at 30/11/2026")
    far_future_cn = workbook([row("00001", "長和")], chinese=True, updated="Updated as at 30/11/2026")
    check("异常未来日期仍拒绝", "future" in raises(lambda: hp._hkex_products(far_future, far_future_cn, today=TODAY)))
    check("坏 XLSX 显式失败", bool(raises(lambda: hp._hkex_products(b"not xlsx", good_cn, today=TODAY))))


def test_real_workbook_bad_dimension_is_not_truncated() -> None:
    """港交所实测 worksheet dimension 错写 A1:R8；必须按真实内容读而非信元数据。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "ListOfSecurities"
    ws.append(["List of Securities"])
    ws.append(["Updated as at 21/11/2026"])
    ws.append(HEADERS)
    for item in [row("00001", "CKH"), row("00700", "TENCENT")]:
        ws.append(item + [None] * 14)
    # openpyxl 保存时会重算，因此直接改 XML 模拟上游错误元数据。
    import zipfile
    raw = io.BytesIO()
    wb.save(raw)
    source = zipfile.ZipFile(io.BytesIO(raw.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                content = content.replace(b'<dimension ref="A1:R5"/>', b'<dimension ref="A1:R1"/>')
            target.writestr(info, content)
    en = out.getvalue()
    cn = workbook([row("00001", "長和"), row("00700", "騰訊")], chinese=True)
    items, meta = hp._hkex_products(en, cn, today=TODAY)
    check("错误 dimension 不截断真实尾行", len(items) == 2 and meta["declaredCount"] == 2, str(meta))


def test_fallback_order() -> None:
    p = hp.HkProvider()
    p._list_products_em = lambda: (_ for _ in ()).throw(ProviderError("em down"))  # type: ignore[assignment]
    expected = ([{"type": "hk", "code": "00700", "name": "騰訊控股"}], {"acquisitionComplete": True})
    p._list_products_hkex = lambda: expected  # type: ignore[assignment]
    sina_called = []
    p._list_products_sina = lambda reason: sina_called.append(reason)  # type: ignore[assignment]
    check("东财失败后官方完整备源直接交付，不再花钱翻新浪", p.list_products("hk") == expected and not sina_called)


if __name__ == "__main__":
    test_official_workbook_mapping()
    test_workbook_fail_closed()
    test_real_workbook_bad_dimension_is_not_truncated()
    test_fallback_order()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        raise SystemExit(1)
