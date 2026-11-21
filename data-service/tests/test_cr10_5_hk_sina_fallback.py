"""CR10-5 离线单测：港股列表的第二腿（新浪 `getHKStockData`）——不依赖网络、零出网。

判别对象＝10-22 02:00 那一轮拿到的那条新证据：**hk 是六类里唯一没有降级腿的一档**
（`lastResult.results[hk]` 只有 `error`、没有 `note`，而同夜 stock／us 两档降级成功）。

成对形状（C34）：
- 正向＝东财失败时新浪仍被有界探测，失败诊断保留实际行数、页数与停止原因；
- 🔁 反向＝东财成功时**一次都没碰新浪**；
- CR10-40：新浪没有声明总数，实测约 2,806 行与东财约 4,751 行不等价；无论取尽、
  预算停止或卡页都**不得返回 products/intentionalSubset**，必须抛错保留旧数据；
- 🔁 两支都失败同样抛 `ProviderError`，不静默返回空列表。

记账这一维也被钉住：降级那一趟必须打 `akshare-obs` 族的 `sina.hk-list`，
**不许自造账外账**（10-09 之后本项目的红线）。
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# 与 test_g6_hk 同一条纪律：先于 app 的任何 import 把 limiter 落盘账本指到临时目录——
# 本套件会真走 `akshare-obs` 族的门，不指走就把测试计数写进仓库那份 runtime/limiter-state.json。
os.environ["LIMITER_STATE_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="cr105-limiter-"), "limiter-state.json")

from app.providers import base, hk_provider as hp  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402
from app.providers import akshare_provider as ap  # noqa: E402  AK_OBS_LIMITER 这枚实例住在 provider 侧

results: list[tuple[str, bool, str]] = []

EM_ROWS = [
    {"f12": "00700", "f14": "腾讯控股"},
    {"f12": "09988", "f14": "阿里巴巴-W"},
]
SINA_ROWS = [
    {"symbol": "00001", "name": "长和", "lasttrade": "66.25"},
    {"symbol": "00700", "name": "腾讯控股", "lasttrade": "419.00"},
]
# 东财那支产出的键面＝列表契约（web 的 sync 只吃这几枚）
EM_KEYS = {"type", "code", "name", "pinyin", "pinyinInitials", "exchange", "tags"}


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _em_ok(p: hp.HkProvider, rows: list[dict] | None = EM_ROWS) -> list[str]:
    """把东财那一支钉成"必成功"，并记录它被打了几个 host 请求。"""
    seen: list[str] = []

    def _fake(hosts, path, params):
        seen.append(path)
        if rows is None:
            raise ProviderError("hk eastmoney request failed on all hosts: RemoteDisconnected")
        return {"data": {"total": str(len(rows)), "diff": rows}}

    p._em_json = _fake  # type: ignore[assignment]
    return seen


def _sina_pages(p: hp.HkProvider, pages: dict[int, list[dict]], boom: Exception | None = None) -> list[int]:
    """新浪那一支的替身：记下被请求过的页码（＝判别"到底有没有走到这条腿"的读数）。"""
    called: list[int] = []

    def _fake_page(page: int) -> list[dict]:
        called.append(page)
        if boom is not None:
            raise boom
        return pages.get(page, [])

    p._sina_hk_page = _fake_page  # type: ignore[assignment]
    return called


def test_primary_success_never_touches_sina() -> None:
    """🔁 反向：东财完整成功 ⇒ 不碰新浪，并显式声明采集完整。"""
    p = hp.HkProvider()
    _em_ok(p)
    called = _sina_pages(p, {1: SINA_ROWS})

    out = p.list_products("hk")
    check("东财成功时一次都没调新浪", called == [], f"sina pages={called}")
    check("东财完整主源带 (items, meta)",
          isinstance(out, tuple) and len(out[0]) == 2, str(type(out)))
    if isinstance(out, tuple):
        items, meta = out
        check("主源采集完整且非产品口径子集",
              meta.get("acquisitionComplete") is True and meta.get("productPolicySubset") is False
              and meta.get("declaredCount") == len(items) == 2, str(meta))


def test_em_snapshot_integrity_guards() -> None:
    """主源也必须证明声明页完整，不能用覆盖写把重复代码藏起来。"""
    p = hp.HkProvider()

    def duplicate(hosts, path, params):
        return {"data": {"total": 2, "diff": [
            {"f12": "00700", "f14": "腾讯控股"},
            {"f12": "00700", "f14": "重复代码"},
        ]}}

    p._em_json = duplicate  # type: ignore[assignment]
    called = _sina_pages(p, {})
    raised = ""
    try:
        p._list_products_em()
    except ProviderError as e:
        raised = str(e)
    check("东财首页重复代码 ⇒ 主候选失败", "duplicate/blank code" in raised, raised)
    check("主候选失败不等于允许低覆盖诊断源交付", called == [], str(called))

    p = hp.HkProvider()
    p._em_json = lambda hosts, path, params: {"data": {"total": 10001, "diff": [
        {"f12": str(i).zfill(5), "f14": f"名称{i}"} for i in range(100)
    ]}}  # type: ignore[assignment]
    raised = ""
    try:
        p._list_products_em()
    except ProviderError as e:
        raised = str(e)
    check("声明页数超过硬上限 ⇒ 拒绝截断，不发后续页", "exceed cap" in raised, raised)

    p = hp.HkProvider()
    p._em_json = lambda hosts, path, params: {"data": {"total": 0, "diff": [
        {"f12": "00700", "f14": "腾讯控股"},
    ]}}  # type: ignore[assignment]
    raised = ""
    try:
        p._list_products_em()
    except ProviderError as e:
        raised = str(e)
    check("声明为零却有原始行 ⇒ 拒绝伪完整候选", "invalid declared total" in raised, raised)


def test_all_hosts_down_falls_back() -> None:
    """东财失败可探测新浪，但低覆盖诊断源永远不能成为提交候选。"""
    p = hp.HkProvider()
    _em_ok(p, rows=None)
    called = _sina_pages(p, {1: SINA_ROWS, 2: []})

    raised, out = "", None
    try:
        out = p.list_products("hk")
    except ProviderError as e:
        raised = str(e)
    check("东财全 host 失败 ⇒ 走到新浪诊断源", called == [1, 2], str(called))
    check("即使新浪自身取尽也拒绝交付（无 total，不能证明与东财集合等价）",
          out is None and "no equivalent complete source" in raised, raised[:220])
    check("失败读数保留新浪行数、穷尽页与东财原因",
          "2 行" in raised and "stop=exhausted" in raised and "eastmoney" in raised, raised[:240])


def test_empty_first_page_also_falls_back() -> None:
    p = hp.HkProvider()
    _em_ok(p, rows=[])
    called = _sina_pages(p, {1: SINA_ROWS, 2: []})
    try:
        p.list_products("hk")
        out = "unexpected success"
    except ProviderError:
        out = "rejected"
    check("东财首页空 diff 触发诊断源，但最终仍不交付",
          called == [1, 2] and out == "rejected", f"{called} / {out}")


def test_meta_and_envelope_source() -> None:
    """东财完整成功的主源元数据经 HTTP 归一不丢失；失败源无 meta 可透传。"""
    p = hp.HkProvider()
    _em_ok(p)
    _sina_pages(p, {1: SINA_ROWS, 2: []})
    got_items, envelope = base.list_products_with_meta(p, "hk")
    check("完整主源元数据声明来源与完整性",
          envelope.get("source") == "akshare-hk" and envelope.get("acquisitionComplete") is True
          and envelope.get("productPolicySubset") is False and len(got_items) == 2, str(envelope))


def test_budget_stop_declares_subset() -> None:
    orig = hp.HK_SINA_SOFT_BUDGET_S
    try:
        hp.HK_SINA_SOFT_BUDGET_S = -1.0
        p = hp.HkProvider()
        _em_ok(p, rows=None)
        called = _sina_pages(p, {1: SINA_ROWS, 2: SINA_ROWS, 3: SINA_ROWS})
        raised = ""
        try:
            p.list_products("hk")
        except ProviderError as e:
            raised = str(e)
        check("预算用完只发 1 页，停止原因保留在失败诊断", called == [1] and "stop=budget" in raised, raised[:200])
        check("主动停不再声明 intentionalSubset 或返回产品行", "no equivalent complete source" in raised)
    finally:
        hp.HK_SINA_SOFT_BUDGET_S = orig


def test_stalled_pages_stop_early() -> None:
    p = hp.HkProvider()
    _em_ok(p, rows=None)
    called = _sina_pages(p, {1: SINA_ROWS, 2: SINA_ROWS, 3: SINA_ROWS, 4: SINA_ROWS})
    raised = ""
    try:
        p.list_products("hk")
    except ProviderError as e:
        raised = str(e)
    check("重复页两连即停，不一路翻到 ceiling", len(called) <= 3, str(called))
    check("卡页诊断同样拒绝候选，保留去重后的 2 行读数",
          "stop=stalled" in raised and "2 行" in raised, raised[:220])


def test_both_down_raises_never_empty() -> None:
    """🔁 会红的样本：两支都失败必须抛 ProviderError。把实现改成 `return []` 这一条必须红。"""
    p = hp.HkProvider()
    _em_ok(p, rows=None)
    _sina_pages(p, {}, boom=ConnectionError("sina refused"))
    raised = None
    out = None
    try:
        out = p.list_products("hk")
    except ProviderError as e:
        raised = str(e)
    check("🔁 两支都失败＝抛 ProviderError（不许静默返回空列表）",
          raised is not None and not isinstance(out, list), f"raised={raised!r} out={out!r}")
    check("错误原文把两支的失败都带上（只说新浪＝归因丢一半）",
          bool(raised) and "eastmoney" in raised and "sina" in raised, str(raised)[:240])


def test_sina_empty_rows_also_raises() -> None:
    """新浪回 200 但一行没有＝同样不许落成"到货 0 只"。"""
    p = hp.HkProvider()
    _em_ok(p, rows=None)
    _sina_pages(p, {1: []})
    try:
        out = p.list_products("hk")
        check("🔁 新浪空数组＝抛错，不返回 []", False, str(out))
    except ProviderError as e:
        check("🔁 新浪空数组＝抛错，不返回 []", "no equivalent complete source" in str(e) and "0 行" in str(e), str(e)[:200])


def test_other_type_guard() -> None:
    """🔁 类型守卫：非 hk 仍抛错，且**不因为加了降级腿就去打新浪**。"""
    p = hp.HkProvider()
    called = _sina_pages(p, {1: SINA_ROWS})
    try:
        p.list_products("stock")
        check("非 hk 类型仍拒绝", False, "no raise")
    except ProviderError as e:
        check("非 hk 类型仍拒绝（unsupported list type）", "unsupported list type" in str(e), str(e)[:120])
    check("🔁 类型守卫那一支没顺带打新浪（省下的就是钱）", called == [], str(called))


def test_fallback_books_to_akshare_obs_family() -> None:
    """降级那一趟的记账归属：打在 `akshare-obs` 族的 `sina.hk-list` 上、不占东财桶。"""
    before = dict(ap.AK_OBS_LIMITER.state()["seen"])

    p = hp.HkProvider()
    _em_ok(p, rows=None)
    _sina_pages(p, {1: SINA_ROWS, 2: []})
    try:
        p.list_products("hk")
    except ProviderError:
        pass

    seen = ap.AK_OBS_LIMITER.state()["seen"]
    check("降级那趟 observe 打在 sina.hk-list（逐函数维度＝下一次调参的唯一依据）",
          int(seen.get("sina.hk-list", 0)) > int(before.get("sina.hk-list", 0)),
          f"before={json.dumps(before, ensure_ascii=False)} after={json.dumps(seen, ensure_ascii=False)}")


if __name__ == "__main__":
    test_primary_success_never_touches_sina()
    test_em_snapshot_integrity_guards()
    test_all_hosts_down_falls_back()
    test_empty_first_page_also_falls_back()
    test_meta_and_envelope_source()
    test_budget_stop_declares_subset()
    test_stalled_pages_stop_early()
    test_both_down_raises_never_empty()
    test_sina_empty_rows_also_raises()
    test_other_type_guard()
    test_fallback_books_to_akshare_obs_family()

    fails = [x for x in results if not x[1]]
    # 汇总行必须是 `gate.mjs` 认得的两种形态之一（`===== N/M 通过 =====` 或 `== 标题：N/M 通过 ==`）。
    # 10-22 全量闸1 实测：写成 `===== 标题 N/M 通过 =====` 时两条正则都不匹配 ⇒ 闸判「解析不出」＝红，
    # 而套件本身 27/27 全绿 ⇒ 假红。这里改成带标题的第二形（标题与数字之间有全角冒号）。
    print(f"\n== CR10-5 hk 降级腿：{len(results) - len(fails)}/{len(results)} 通过 ==")
    if fails:
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:200]}")
    sys.exit(1 if fails else 0)
