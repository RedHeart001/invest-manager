"""CR10-5 离线单测：港股列表的第二腿（新浪 `getHKStockData`）——不依赖网络、零出网。

判别对象＝10-22 02:00 那一轮拿到的那条新证据：**hk 是六类里唯一没有降级腿的一档**
（`lastResult.results[hk]` 只有 `error`、没有 `note`，而同夜 stock／us 两档降级成功）。

成对形状（C34）：
- 正向＝东财失败时新浪行被映射成与东财**同一 schema**；
- 🔁 反向＝东财成功时**一次都没碰新浪**（这一枚不判别＝写个"降级会跑"的用例照样绿）；
- 🔁 会红的样本＝两支都失败时必须抛 `ProviderError`，**不许静默返回空列表**
  （把实现改成 `return []` 本套必须红——"没到货"与"到货 0 只"是两件事）；
- 覆盖面声明＝主动停（预算／卡页／上限）才带 `intentionalSubset`，翻页取尽时不许声明。

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
    """🔁 反向（整套的牙齿）：东财成功 ⇒ 新浪一次都不该被调用，返回形状仍是裸 list。"""
    p = hp.HkProvider()
    _em_ok(p)
    called = _sina_pages(p, {1: SINA_ROWS})

    out = p.list_products("hk")
    check("🔁 东财成功时一次都没调新浪（这一枚不红＝「降级会不会跑」根本没法信）",
          called == [], f"sina pages={called}")
    check("东财成功仍返回裸 list（`test_g6_hk` 钉的那个形状没被改口）",
          isinstance(out, list) and len(out) == 2, str(type(out)))
    check("东财成功时不声明 degraded", not isinstance(out, tuple))


def test_all_hosts_down_falls_back() -> None:
    """东财抛 ProviderError（02:00 那一夜的原文形状）⇒ 换新浪，schema 逐枚对。"""
    p = hp.HkProvider()
    _em_ok(p, rows=None)
    called = _sina_pages(p, {1: SINA_ROWS, 2: []})

    out = p.list_products("hk")
    check("东财全 host 失败 ⇒ 走到新浪（页码从 1 开始）", called[:1] == [1], str(called))
    if not isinstance(out, tuple):
        check("降级那支必须返回 (items, meta)", False, str(type(out)))
        return
    items, meta = out
    check("新浪行与东财行同 schema（键面逐枚对，不预设列名）",
          all(set(x.keys()) == EM_KEYS for x in items), str([sorted(x) for x in items][:1]))
    check("新浪 symbol/name 映射正确（00001 长和）",
          {x["code"]: x["name"] for x in items} == {"00001": "长和", "00700": "腾讯控股"},
          str(items))
    check("exchange 仍标 HK、type 仍标 hk（消费侧不分源）",
          all(x["exchange"] == "HK" and x["type"] == "hk" for x in items))
    check("pinyinInitials 非空（新浪短名同样要能拼音检索）",
          all(x["pinyinInitials"] for x in items), str([x["pinyinInitials"] for x in items]))


def test_empty_first_page_also_falls_back() -> None:
    """第二个失败出口也要换源：东财回 200 但 `diff` 为空（`hk list empty (all hosts)`）。"""
    p = hp.HkProvider()
    _em_ok(p, rows=[])  # {"data": {"total": "0", "diff": []}} → 首页空 ⇒ 抛 ProviderError
    called = _sina_pages(p, {1: SINA_ROWS, 2: []})
    out = p.list_products("hk")
    check("东财首页空 diff 也触发降级（不止「全部 host 异常」那一条出口）",
          called[:1] == [1] and isinstance(out, tuple), f"{called} / {type(out)}")


def test_meta_and_envelope_source() -> None:
    """CR9-31 的显式声明：meta 的 source／degraded／note，经归一后信封里读得到 sina-hk-spot。"""
    p = hp.HkProvider()
    _em_ok(p, rows=None)
    _sina_pages(p, {1: SINA_ROWS, 2: []})
    items, meta = p.list_products("hk")

    check("meta 声明 source=sina-hk-spot（落码后的现场判据就这一串）",
          meta.get("source") == "sina-hk-spot", str(meta.get("source")))
    check("meta 带 degraded=True", meta.get("degraded") is True, str(meta))
    check("翻页取尽 ⇒ 不许声明 intentionalSubset（那是「我们自己的口径」那一档）",
          meta.get("intentionalSubset") is False, str(meta.get("intentionalSubset")))
    note = str(meta.get("note"))
    check("note 写清短名这一枚对撞点（别让消费侧自己发现）",
          "短名" in note and "00001" in note, note[:200])
    check("note 写清是东财先不可用（可归因、不是静默换源）",
          "东财港股列表不可用" in note, note[:120])

    got_items, envelope = base.list_products_with_meta(p, "hk")
    check("list_products_with_meta 归一后信封里的出网源＝sina-hk-spot（web 拼的那句 note 靠它）",
          envelope.get("source") == "sina-hk-spot" and len(got_items) == 2, str(envelope))


def test_budget_stop_declares_subset() -> None:
    """到 soft budget 主动停＝拿到多少算多少，且必须声明 intentionalSubset（缩水闸靠它放行）。"""
    orig = hp.HK_SINA_SOFT_BUDGET_S
    try:
        hp.HK_SINA_SOFT_BUDGET_S = -1.0  # 逼第一页之后即停
        p = hp.HkProvider()
        _em_ok(p, rows=None)
        called = _sina_pages(p, {1: SINA_ROWS, 2: SINA_ROWS, 3: SINA_ROWS})
        items, meta = p.list_products("hk")
        check("预算用完就主动停（只发 1 页，绝不越界捶源）", called == [1], str(called))
        check("主动停＝有意子集，meta 必须声明 intentionalSubset=True",
              meta.get("intentionalSubset") is True, str(meta.get("intentionalSubset")))
        check("主动停的覆盖面写进 note（页数与停止原因可读）",
          "主动停" in str(meta.get("note")), str(meta.get("note"))[:200])
    finally:
        hp.HK_SINA_SOFT_BUDGET_S = orig


def test_stalled_pages_stop_early() -> None:
    """上游反复回同一页 ⇒ 连停两页就收手（这一形＝再打就是白花钱，不能靠 ceiling 兜）。"""
    p = hp.HkProvider()
    _em_ok(p, rows=None)
    called = _sina_pages(p, {1: SINA_ROWS, 2: SINA_ROWS, 3: SINA_ROWS, 4: SINA_ROWS})
    items, meta = p.list_products("hk")
    check("重复页两连即停（≤3 页，不是一路翻到 90）", len(called) <= 3, str(called))
    check("卡页也按有意子集声明（覆盖面缺口不是上游又劣化一档）",
          meta.get("intentionalSubset") is True, str(meta.get("intentionalSubset")))
    check("行数仍等于去重后的代码数（重复页不许把同一只数两次）", len(items) == 2, str(items))


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
        check("🔁 新浪空数组＝抛错，不返回 []", "empty from both sources" in str(e), str(e)[:200])


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
    p.list_products("hk")

    seen = ap.AK_OBS_LIMITER.state()["seen"]
    check("降级那趟 observe 打在 sina.hk-list（逐函数维度＝下一次调参的唯一依据）",
          int(seen.get("sina.hk-list", 0)) > int(before.get("sina.hk-list", 0)),
          f"before={json.dumps(before, ensure_ascii=False)} after={json.dumps(seen, ensure_ascii=False)}")


if __name__ == "__main__":
    test_primary_success_never_touches_sina()
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
