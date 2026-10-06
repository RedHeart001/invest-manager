"""R15/M8 离线单测：源族限速器、主备链降级、备源解析。

运行方式（无需服务在跑）：
    .venv/Scripts/python tests/test_p2_m8.py
"""

import os
import sys
import time

# 脚本从 tests/ 启动时，把项目根加入 import 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
# 自带 UTF-8 输出后，跑本脚本不再需要 PYTHONIOENCODING（errors=replace 兜极端情况）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


from app.providers.base import (
    BaseProvider,
    ProviderError,
    get_provider_chain,
    register,
    register_chain,
)
from app.providers.akshare_provider import _sina_symbol_exchange
from app.providers.sina_provider import _etf_symbol
from app.providers.tencent_provider import TencentProvider, _symbol
from app.utils.limiter import FamilyLimiter

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# ---------- 限速器 ----------


def test_limiter() -> None:
    lim = FamilyLimiter("t1", min_interval=0.3, burst=1, rate_per_min=100)
    check("限速器：首次直接放行", lim.acquire(timeout=1.0) is True)
    t0 = time.monotonic()
    check("限速器：突发用尽后强制最小间隔", lim.acquire(timeout=2.0) is True)
    check("限速器：间隔生效且 ≥0.25s", time.monotonic() - t0 >= 0.25,
          f"waited={time.monotonic() - t0:.3f}")

    lim2 = FamilyLimiter("t2", failure_threshold=2, cooldown_base=60.0)
    lim2.on_failure()
    check("限速器：单次失败不熔断", lim2.in_cooldown() is False)
    lim2.on_failure()
    check("限速器：连续失败 2 次进入冷却", lim2.in_cooldown() is True)
    check("限速器：冷却期 acquire 返回 False（转备源）",
          lim2.acquire(timeout=0.1) is False)
    lim2.on_success()
    check("限速器：成功后冷却解除", lim2.in_cooldown() is False)

    lim3 = FamilyLimiter("t3", min_interval=0.0, burst=100, rate_per_min=3)
    for _ in range(3):
        lim3.acquire(timeout=1.0)
    check("限速器：每分钟上限超限不硬等", lim3.acquire(timeout=0.3) is False)


def test_limiter_profile_single_source() -> None:
    """CR9-18：桶参数只有一个来源，调参不会被"首调用获胜"静默吞掉。

    旧缺陷现场：`hotspot/pipeline.py` 先 `get_limiter("eastmoney")`（无参）创建，
    `akshare_provider` 随后传的六个参数因"已存在即复用"而全部丢弃——两处取值今天
    恰好相同所以无症状，一旦按 C-5 调桶就会"改了不生效且不报错"。
    """
    import inspect

    from app.utils import limiter

    params = list(inspect.signature(limiter.get_limiter).parameters)
    check("CR9-18：get_limiter 不再有第二个参数通道（签名只剩 name）",
          params == ["name"], str(params))
    try:
        limiter.get_limiter("eastmoney", min_interval=99.0)  # type: ignore[call-arg]
        kwargs_rejected = False
    except TypeError:
        kwargs_rejected = True
    check("CR9-18🔁：传参数会被拒（调参只能改 PROFILES 一处）", kwargs_rejected)

    em = limiter.get_limiter("eastmoney")
    declared = limiter.PROFILES["eastmoney"]
    actual = {k: getattr(em, k) for k in declared}
    check("CR9-18：线上实例的六个值逐项等于 PROFILES", actual == declared, str(actual))
    check("CR9-18：两个调用点拿到同一个源族实例",
          limiter.get_limiter("eastmoney") is em)

    from app.hotspot import pipeline
    from app.providers import akshare_provider

    check("CR9-18：pipeline._EM 与 akshare.EM_LIMITER 同源同实例",
          pipeline._EM is akshare_provider.EM_LIMITER is em)

    # 🔁 反向对照：改唯一来源，新建族必须真的取到新值（证明这条链没被别处覆盖）
    fake = "__cr9_18_family"
    undeclared = "__cr9_18_undeclared"
    try:
        limiter.PROFILES[fake] = {"min_interval": 0.75, "rate_per_min": 3}
        created = limiter.get_limiter(fake)
        check("CR9-18🔁：PROFILES 改动对新建源族立即生效",
              created.min_interval == 0.75 and created.rate_per_min == 3,
              f"got={created.min_interval}/{created.rate_per_min}")
        unset = limiter.get_limiter(undeclared)
        check("CR9-18🔁：未声明的族回落到类默认值（不是别处的隐式参数）",
              unset.min_interval == FamilyLimiter("probe").min_interval)
    finally:
        limiter.PROFILES.pop(fake, None)
        limiter._LIMITERS.pop(fake, None)
        limiter._LIMITERS.pop(undeclared, None)
        check("CR9-18：临时源族已清干净（不污染其它用例）",
              fake not in limiter.PROFILES and fake not in limiter._LIMITERS)


# ---------- 桶外 akshare 的观测族（#27 第一步，10-03） ----------


def test_akshare_out_of_bucket_observation() -> None:
    """#27 第一步：桶外那条 akshare 路只**数数**，一条都不拦。

    红线是「OPT-3 不得动东财桶」，而 `_ak_request` 里若干处实际打的仍是 eastmoney 域名。
    补限流之前先得有次数可看 ⇒ 观测族 `akshare-obs`。C34 成对：计数长在真实调用点上
    ⇔ 观测不改行为（不走 `acquire`、不进冷却、不与东财族同实例）⇔ 老族参数一个没动。
    """
    from app.providers import akshare_provider as akp
    from app.utils import limiter

    obs = limiter.get_limiter("akshare-obs")
    em = limiter.get_limiter("eastmoney")
    check("#27：观测族与东财族是两个不同实例（共用＝把「不占东财桶」悄悄改掉）",
          obs is not em and akp.AK_OBS_LIMITER is obs and akp.EM_LIMITER is em,
          f"{id(obs)}/{id(em)}")
    declared = limiter.PROFILES["akshare-obs"]
    check("#27：观测族参数逐项等于 PROFILES（调参仍只有一个来源，CR9-18 同条纪律）",
          {k: getattr(obs, k) for k in declared} == declared, str(obs.state()))

    before = obs.state()
    probe = "__cr9_27_probe"
    for _ in range(200):
        obs.observe(probe)
    st = obs.state()
    check("#27：observe 只加 seen，granted/denied 一个都不动（没走 acquire ⇒ 不可能拦）",
          st["granted"] == before["granted"] and st["denied"] == before["denied"]
          and obs._seen.get(probe) == 200, str(st))
    check("🔁 #27：连记 200 次之后观测族仍不进冷却（纯计数，不产生任何拒绝路径）",
          obs.in_cooldown() is False and obs.cooldown_remaining() == 0.0, str(st))
    em_declared = limiter.PROFILES["eastmoney"]
    check("🔁 #27：东财族六个参数逐项仍等于 PROFILES（新族没挪动真桶）",
          {k: getattr(em, k) for k in em_declared} == em_declared, str(em.state()))

    # 计数真的装在调用点上：本地 lambda ⇒ 零出网，但走的是生产那条 `_ak_request`
    name = "ak.__cr9_27_callsite"
    seen_before = akp.AK_OBS_LIMITER.state()["seenTotal"]
    got = akp._ak_request(lambda: "ok", 5.0, name)
    st2 = akp.AK_OBS_LIMITER.state()
    check("#27：`_ak_request` 记了一笔且返回值原样通过（观测不改行为）",
          got == "ok" and st2["seenTotal"] == seen_before + 1
          and akp.AK_OBS_LIMITER._seen.get(name) == 1, str(st2))
    try:
        akp._ak_request(lambda: (_ for _ in ()).throw(RuntimeError("boom")), 5.0, f"{name}-fail")
        raised = False
    except akp.ProviderError:
        raised = True
    check("🔁 #27：上游抛错仍按原样变 ProviderError（观测位没把它吞成成功）", raised, "")

    names = [s["name"] for s in limiter.snapshot_all()]
    check("#27：/health 的读数面按字典序带出两族（纯观测也得一条 curl 读得到）",
          names == sorted(names) and "eastmoney" in names and "akshare-obs" in names, str(names))

    for k in (probe, name, f"{name}-fail"):
        obs._seen.pop(k, None)
    check("#27：探针样本已清（观测位不得把自己的计数留在别人读到的地方）",
          probe not in obs.state()["seen"] and name not in obs.state()["seen"], str(obs.state()))


# ---------- 列表来源元信息（CR9-31） ----------


def test_list_products_meta() -> None:
    """列表类内部主备切换必须声明来源，否则降级对消费侧不可见（R16）。

    实证（09-27）：东财冷却时 `/products?type=bond` 返回 327 只，响应里只有
    type/count/products——与"上游真只有 327 只"长得一模一样，web 侧缩水保护
    只能写"疑似"。现在 provider 用 `(items, meta)` 形态自己说清楚。
    """
    import akshare as ak
    import pandas as pd

    import app.providers.akshare_provider as akp
    from app.providers.base import ProviderError, list_products_with_meta

    orig = {n: getattr(ak, n) for n in ("bond_zh_cov", "bond_zh_hs_cov_spot")}
    orig_limiter = (akp.EM_LIMITER.acquire, akp.EM_LIMITER.on_success, akp.EM_LIMITER.on_failure)
    akp.EM_LIMITER.acquire = lambda *a, **k: True  # type: ignore[assignment]
    akp.EM_LIMITER.on_success = lambda: None  # type: ignore[assignment]
    akp.EM_LIMITER.on_failure = lambda: None  # type: ignore[assignment]

    em_df = pd.DataFrame(
        {"债券代码": ["113050", "123285"], "债券简称": ["N价值", "润禾转02"]}
    )
    sina_df = pd.DataFrame({"symbol": ["sh113050", "sz123285"], "name": ["价值转债", "润禾转债"]})

    class _Plain:  # 默认契约：只回 list，不带元信息
        source = "plain-src"

        def list_products(self, type_: str):
            return [{"code": "00700"}]

    try:
        items, meta = list_products_with_meta(_Plain(), "hk")
        check("CR9-31：裸 list 契约不变，meta 回落 provider.source",
              items == [{"code": "00700"}] and meta == {"source": "plain-src"}, str(meta))

        # ① 主源（东财）成功 → 声明 akshare，且不得带 degraded 标记
        ak.bond_zh_cov = lambda: em_df
        ak.bond_zh_hs_cov_spot = lambda: sina_df
        items, meta = list_products_with_meta(akp._akshare, "bond")
        check("CR9-31：东财主源 count 与 schema 不变",
              len(items) == 2 and items[0]["type"] == "bond" and "可转债" in items[0]["tags"],
              str(items[:1]))
        check("CR9-31：主源不谎称降级",
              meta.get("source") == "akshare" and "degraded" not in meta, str(meta))

        # ② 主源失败 → 备源必须自报来源 + degraded + note（含本次条数与原始错误）
        def _boom():
            raise RuntimeError("bond_zh_cov timeout")

        ak.bond_zh_cov = _boom
        items, meta = list_products_with_meta(akp._akshare, "bond")
        note = meta.get("note") or ""
        check("CR9-31🔁：备源来自 320 只快照（2 条样例）", len(items) == 2, str(items[:1]))
        check("CR9-31🔁：备源显式声明 source/degraded",
              meta.get("source") == "sina-bond-cov-spot" and meta.get("degraded") is True,
              str(meta))
        check("CR9-31🔁：note 说得出降级原因原文与本次覆盖面",
              "bond_zh_cov timeout" in note and "本次 2 只" in note and "cov_spot" in note,
              note[:200])
        check("CR9-31🔁：备源 exchange 仍按新浪前缀解析（CR-17 口径未破）",
              [x["exchange"] for x in items] == ["SH", "SZ"], str(items))

        # ③ 两源皆空 → 仍按原契约抛 ProviderError（不静默返回空列表）
        ak.bond_zh_hs_cov_spot = lambda: pd.DataFrame({"symbol": [], "name": []})
        try:
            list_products_with_meta(akp._akshare, "bond")
            check("CR9-31🔁：两源皆空仍抛 ProviderError", False, "没抛错")
        except ProviderError as e:
            check("CR9-31🔁：两源皆空仍抛 ProviderError", "empty from all sources" in str(e), str(e))
    finally:
        for n, f in orig.items():
            setattr(ak, n, f)
        akp.EM_LIMITER.acquire, akp.EM_LIMITER.on_success, akp.EM_LIMITER.on_failure = orig_limiter


# ---------- `/products` 端点的 meta 透传（CR9-68／#40 丙） ----------


def test_products_endpoint_passthrough_meta() -> None:
    """provider 声明的那四个键，必须**整包**走出 HTTP 边界——这一跳此前零断言。

    为什么单开一组（10-06 断言强度审计登记的 #40 (c)）：`intentionalSubset` 等四个键此前被断的
    两处（`test_cr9_59_us_list.py:244-245`、本文件 `:400-401`）**都停在 provider／
    `list_products_with_meta` 那一层**，而 `app/main.py` 用 `**meta` 把它们透传出去那一跳，
    只有 ③／⑤ 真网窗口才读得到。⇒ 将来谁把 meta 收成白名单（`{"source": meta.get(...)}`），
    ①② 都静默，而后果正是 CR9-63 要防的那件事＝**us 永远停在旧名单**（web 读不到声明 ⇒
    缩水闸每一天都挡回同一份名单）。同族的 `/quotes` 已由 CR9-67 补了三句真调用，这一条补齐。

    零出网：`list_products_with_meta` 整个换成假对象，只断端点自己那一跳。
    """
    import app.main as m
    from app.providers.base import ProviderError

    items = [{"code": "AAPL"}, {"code": "NVDA"}]
    orig = m.list_products_with_meta
    try:
        # ① 四键齐的一轮（＝us 那种"有意子集"的真实形状）
        m.list_products_with_meta = lambda provider, type_: (  # type: ignore[assignment]
            items,
            {"source": "sina-us-list", "degraded": True, "note": "只取前排 1 页", "intentionalSubset": True},
        )
        body = m.products(type="us")
        check("CR9-68：四个 meta 键逐项在响应体里，且值与 provider 给的一字不差",
              body.get("source") == "sina-us-list" and body.get("degraded") is True
              and body.get("note") == "只取前排 1 页" and body.get("intentionalSubset") is True,
              str(body)[:200])
        check("CR9-68：既有三键形态不变（加键不是换契约，`count` 仍是 `len(items)`）",
              body.get("type") == "us" and body.get("count") == 2 and body.get("products") == items,
              str(body)[:160])

        # ② 🔁 主源态：provider **不给** degraded/note ⇒ 端点也不许凭空造出来
        m.list_products_with_meta = lambda provider, type_: (  # type: ignore[assignment]
            items, {"source": "akshare"}
        )
        body2 = m.products(type="stock")
        check("CR9-68🔁：provider 没声明降级 ⇒ `degraded`/`note`/`intentionalSubset` 不许被造出来",
              "degraded" not in body2 and "note" not in body2 and "intentionalSubset" not in body2,
              str(sorted(body2))[:200])

        # ③ 🔁 显式的假值与 None 必须原样出去：`if v` 那种"过滤空值"的写法会吃掉它们，
        #    而 web 侧读的正是 `degraded === true`／`snapshotAt ?? updatedAt` 这类"假也要在"的判据
        m.list_products_with_meta = lambda provider, type_: (  # type: ignore[assignment]
            items,
            {"source": "akshare", "degraded": False, "note": None, "intentionalSubset": False},
        )
        body3 = m.products(type="bond")
        check("CR9-68🔁：`degraded=False`／`note=None`／`intentionalSubset=False` 三个显式假值原样透传"
              "（键必须在，不能被「空值过滤」顺手删掉）",
              body3.get("degraded") is False and "note" in body3 and body3.get("note") is None
              and body3.get("intentionalSubset") is False, str(sorted(body3))[:200])

        # ④ 既有的两道映射仍在透传之前生效（未注册类型 400／上游失败 502）
        from fastapi import HTTPException

        try:
            m.products(type="bogus")
            check("CR9-68🔁：未注册类型仍 400（白名单闸在取数与透传之前）", False, "没抛 HTTPException")
        except HTTPException as e:
            check("CR9-68🔁：未注册类型仍 400（白名单闸在取数与透传之前）",
                  e.status_code == 400, str(e.status_code))
        m.list_products_with_meta = lambda provider, type_: (_ for _ in ()).throw(  # type: ignore[assignment]
            ProviderError("empty from all sources")
        )
        try:
            m.products(type="fund")
            check("CR9-68🔁：上游 ProviderError 仍映射 502（不是带着半包 meta 返回 200）", False, "没抛")
        except HTTPException as e:
            check("CR9-68🔁：上游 ProviderError 仍映射 502（不是带着半包 meta 返回 200）",
                  e.status_code == 502, str(e.status_code))
    finally:
        m.list_products_with_meta = orig  # type: ignore[assignment]


# ---------- A 股名单名字清洗（#25 乙口径②） ----------


def test_stock_name_status_prefix() -> None:
    """交易状态前缀不是名字的一部分（10-03 主人拍板 #25 乙口径②）。

    东财 `f14` 在除息日同样带 `XD`，新浪 `hs_a` 带得更频繁；而 `Product.name` 是
    整表覆盖写入的 ⇒ 不洗的话同一个代码的库内权威名会随"这一批由哪家上游供数"来回变，
    搜索/详情页跟着抖。更糟的是 `name` 还喂 `_pinyin_pair()` ⇒ 拼音串会变成
    `XDanhuifeng`（实测值），前缀字母被拼进检索键与 FTS。
    刻意**不剥** `ST`/`*ST`：CR8-8 的既有口径是"只滤退市，ST/*ST 与北交所保留"
    （主人 09-30 定的字，`web/lib/hotspots.ts`）。
    """
    import app.providers.akshare_provider as akp

    strip = akp.strip_status_prefix
    check(
        "乙②：XD/DR/XR/N/C 五种状态前缀剥掉",
        [strip(x) for x in ("XD安徽凤", "DR贵州茅台", "XR中国平安", "N英诺", "C英诺")]
        == ["安徽凤", "贵州茅台", "中国平安", "英诺", "英诺"],
    )
    check("乙②🔁：ST/*ST 刻意不剥（CR8-8 保留口径不被踩）",
          strip("*ST华融") == "*ST华融" and strip("ST必康") == "ST必康")
    check("乙②🔁：「退市」原样保留 ⇒ 仍被 CR8-8 的 includes('退市') 滤掉",
          strip("退市金钰") == "退市金钰" and "退市" in strip("退市金钰"))
    check("乙②🔁：不误啃拉丁真名／不整条清空",
          strip("TCL科技") == "TCL科技" and strip("XD") == "XD" and strip("") == "")
    check("乙②：幂等（已是干净名再过一次不变）",
          strip(strip("XD安徽凤")) == "安徽凤")

    # 端到端：东财主路径的产出面（零出网——直接喂 stub 的东财响应）
    payload = {
        "data": {
            "total": 4,
            "diff": [
                {"f12": "920000", "f14": "XD安徽凤"},   # 新浪探针里的字面样本（bj 前缀）
                {"f12": "600086", "f14": "退市金钰"},
                {"f12": "000016", "f14": "*ST华融"},
                {"f12": "301399", "f14": "N英诺"},
            ],
        }
    }
    orig_get = akp._em_get
    akp._em_get = lambda path, params: payload  # type: ignore[assignment]
    try:
        items = akp._akshare._list_stocks_em()
        check("乙②🔁：入库名是洗过的权威名，行序与条数不变",
              [x["name"] for x in items] == ["安徽凤", "退市金钰", "*ST华融", "英诺"],
              str(items))
        check("乙②🔁：拼音由洗过的名字生成（不是 XDanhuifeng/XDahf）",
              items[0]["pinyin"] == "anhuifeng" and items[0]["pinyinInitials"] == "ahf",
              str(items[0]))
        check("乙②：schema 面一处不多一处不少（含 tags 本来就是 []，口径③）",
              all(
                  x
                  == {
                      "type": "stock",
                      "code": x["code"],
                      "name": x["name"],
                      "pinyin": x["pinyin"],
                      "pinyinInitials": x["pinyinInitials"],
                      "exchange": x["exchange"],
                      "tags": [],
                  }
                  for x in items
              )
              and [x["exchange"] for x in items] == ["BJ", "SH", "SZ", "SZ"],
              str(items[:1]),
            )
    finally:
        akp._em_get = orig_get  # type: ignore[assignment]


# ---------- A 股名单主备切换（#25 乙第 3 步） ----------


def test_stock_list_backup_source() -> None:
    """`_list_stocks()` 自带主备切换，且降级必须按 CR9-31 把覆盖面差异自己说清楚。

    立项依据（10-03 实测）：东财 `clist/get` 对三个 host、`pz=200`/`pz=10000` 一律
    `RemoteDisconnected` ⇒ 列表链路硬不可用，`Product.stock` 停在 09-12 已 21 天；
    两份全量对比给出差集归因：东财多出的 343 只**全是已摘牌/退市类代码**（含「退市」61、
    `ST`/`*ST` 112），新浪独有 1 只（`920202`），且新浪含北交所 348 只＝与主源同市场面。
    """
    import pandas as pd

    import app.providers.akshare_provider as akp
    from app.providers.base import ProviderError, list_products_with_meta

    em_payload = {
        "data": {
            "total": 1,
            "diff": [{"f12": "600519", "f14": "贵州茅台"}],
        }
    }
    sina_df = pd.DataFrame(
        {
            "代码": ["sh600028", "sz000012", "bj920000", "sh600519"],
            "名称": ["XD中国石", "南 玻Ａ", "XD安徽凤", "贵州茅台"],
        }
    )

    orig_get = akp._em_get
    import akshare as ak

    orig_spot = ak.stock_zh_a_spot
    sina_calls = []

    def _sina_stub():
        sina_calls.append(1)
        return sina_df

    ak.stock_zh_a_spot = _sina_stub  # type: ignore[assignment]
    try:
        # ① 主源正常 → 出网源声明为 akshare，**且一次都不碰备源**
        akp._em_get = lambda path, params: em_payload  # type: ignore[assignment]
        items, meta = list_products_with_meta(akp._akshare, "stock")
        check("乙③：主源态 schema 与条数不变", len(items) == 1 and items[0]["code"] == "600519", str(items))
        check("乙③：主源态 source=akshare 且不谎称降级",
              meta.get("source") == "akshare" and "degraded" not in meta and "note" not in meta, str(meta))
        check("乙③🔁：主源成功时备源一次都没被调用（不是「每次都先问一遍新浪」）",
              sina_calls == [], str(sina_calls))

        # ② 主源失败 → 降级到新浪快照，名字/交易所/拼音都按备源形态重建
        def _em_down(path, params):
            raise ProviderError("eastmoney request failed on all hosts: RemoteDisconnected")

        akp._em_get = _em_down  # type: ignore[assignment]
        items, meta = list_products_with_meta(akp._akshare, "stock")
        note = meta.get("note") or ""
        check("乙③🔁：备源去掉了 symbol 前缀、交易所按前缀显式解析（CR-17 同口径）",
              [x["code"] for x in items] == ["600028", "000012", "920000", "600519"]
              and [x["exchange"] for x in items] == ["SH", "SZ", "BJ", "SH"],
              str(items))
        check("乙③🔁：口径①——备源含北交所（bj 行存在，不是把 920 段丢掉）",
              sum(1 for x in items if x["exchange"] == "BJ") == 1, str(items))
        check("乙③🔁：备源名字同样过清洗（XD 不进库）＋拼音按干净名生成",
              items[2]["name"] == "安徽凤" and items[2]["pinyin"] == "anhuifeng", str(items[2]))
        check("乙③🔁：备源 source/degraded 声明到位",
              meta.get("source") == "sina-a-share-spot" and meta.get("degraded") is True, str(meta))
        check("乙③🔁：上游劣化这条路径**不带**『有意子集』声明（#35／CR9-63 的放行通道没被写宽）",
              "intentionalSubset" not in meta, str(meta)[:120])
        check("乙③🔁：note 说得出主源错误原文＋本次条数",
              "RemoteDisconnected" in note and f"本次 {len(items)} 只" in note, note[:200])
        check("乙③🔁：note 说得出两处真实代价（摘牌代码不会带来／新浪短名≤5 字符与 -U 后缀）",
              "已摘牌" in note and "短名" in note and "-U" in note, note[:260])

        # ②b 同一份数据换成**英文列名**也必须解析得动：本机 akshare 的
        # `stock_zh_a_spot` 给中文列名（代码=带 sh/sz/bj 前缀的 symbol），而同版本的
        # `bond_zh_hs_cov_spot` 给英文列名——**不能按"akshare 都用英文列名"推**，
        # 10-03 就是按英文键取 `code` 拿到 5571 行却一个 code 都没存下来。
        ak.stock_zh_a_spot = lambda: pd.DataFrame({  # type: ignore[assignment]
            "symbol": ["sh600028", "bj920000"],
            "name": ["XD中国石", "XD安徽凤"],
        })
        items_en, meta_en = list_products_with_meta(akp._akshare, "stock")
        check("乙③🔁：英文列名形态（symbol/name）同样解析——不押注本机那套中文列名",
              [x["code"] for x in items_en] == ["600028", "920000"]
              and [x["exchange"] for x in items_en] == ["SH", "BJ"]
              and items_en[1]["name"] == "安徽凤"
              and meta_en.get("degraded") is True,
              str(items_en))

        # ③ 两源皆失败 → 按既有契约抛 ProviderError，不静默交空表（C1 空载荷保护在上游）
        ak.stock_zh_a_spot = lambda: (_ for _ in ()).throw(RuntimeError("sina hs_a timeout"))  # type: ignore[assignment]
        try:
            list_products_with_meta(akp._akshare, "stock")
            check("乙③🔁：两源皆失败抛 ProviderError", False, "没抛错")
        except ProviderError as e:
            check("乙③🔁：两源皆失败抛 ProviderError", "stock list unavailable" in str(e), str(e)[:160])

        # ④ 备源回来了但一行都没有 → 同样抛，不能让"0 只"伪装成一次成功同步
        ak.stock_zh_a_spot = lambda: pd.DataFrame({"代码": [], "名称": []})  # type: ignore[assignment]
        try:
            list_products_with_meta(akp._akshare, "stock")
            check("乙③🔁：备源空表也抛（不静默产出 0 只）", False, "没抛错")
        except ProviderError as e:
            check("乙③🔁：备源空表也抛（不静默产出 0 只）", "empty from all sources" in str(e), str(e)[:160])
    finally:
        akp._em_get = orig_get  # type: ignore[assignment]
        ak.stock_zh_a_spot = orig_spot  # type: ignore[assignment]


# ---------- 符号映射 ----------


def test_symbol_mapping() -> None:
    check("腾讯符号：600519→sh", _symbol("600519") == "sh600519")
    check("腾讯符号：159915→sz", _symbol("159915") == "sz159915")
    check("腾讯符号：113710→sh（沪转债）", _symbol("113710") == "sh113710")
    check("腾讯符号：123285→sz（深转债）", _symbol("123285") == "sz123285")
    check("腾讯符号：920001→bj", _symbol("920001") == "bj920001")
    check("新浪符号：159915→sz", _etf_symbol("159915") == "sz159915")
    check("新浪符号：510300→sh", _etf_symbol("510300") == "sh510300")
    check("新浪符号：场外基金不支持", _etf_symbol("110022") is None)
    # CR-17：新浪转债 symbol → 交易所显式解析（不依赖数字前缀推断）
    check("CR-17：sh113050→SH", _sina_symbol_exchange("sh113050") == "SH")
    check("CR-17：sz123285→SZ", _sina_symbol_exchange("sz123285") == "SZ")
    check("CR-17：未知前缀→空", _sina_symbol_exchange("xx000000") == "")


# ---------- 主备链 ----------


class _FailingProvider(BaseProvider):
    source = "failp"

    def get_quote(self, type_: str, code: str) -> dict:
        raise ProviderError("boom")

    def get_kline(self, type_, code, start=None, end=None, interval="1d") -> dict:
        raise ProviderError("boom")


class _GoodProvider(BaseProvider):
    source = "goodp"

    def get_quote(self, type_: str, code: str) -> dict:
        return {"source": self.source, "price": 1.0}

    def get_kline(self, type_, code, start=None, end=None, interval="1d") -> dict:
        return {"source": self.source, "candles": [1, 2]}


def test_chain() -> None:
    register(["__chain_a"], _FailingProvider())
    register_chain(["__chain_a"], _GoodProvider(), position=1)
    chain = [p.source for p in get_provider_chain("__chain_a")]
    check("链路顺序：主源在前、备源在后", chain == ["failp", "goodp"], str(chain))

    from app.main import _chain_call

    register(["__chain_b"], _FailingProvider())
    register_chain(["__chain_b"], _GoodProvider(), position=1)
    result = _chain_call("__chain_b", lambda p: p.get_quote("__chain_b", "X"))
    check("链路：主源失败自动降级备源", result.get("source") == "goodp", str(result))
    check("链路：降级响应带 note 标注",
          "已降级至" in str(result.get("note")), str(result.get("note")))

    register(["__chain_c"], _FailingProvider())
    raised = False
    try:
        _chain_call("__chain_c", lambda p: p.get_quote("__chain_c", "X"))
    except ProviderError:
        raised = True
    check("链路：全部失败抛 ProviderError（页面降级说明）", raised)


# ---------- 备源解析（离线 monkeypatch） ----------


def test_tencent_parsers() -> None:
    import app.providers.tencent_provider as tp

    # K 线解析
    class KResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "sz159915": {
                        "qfqday": [
                            ["2026-09-11", "3.323", "3.341", "3.354", "3.280", "19052972"]
                        ]
                    }
                }
            }

    orig = tp.requests.get
    tp.requests.get = lambda *a, **k: KResp()
    try:
        out = TencentProvider().get_kline("fund", "159915", "20260701", "20260912")
    finally:
        tp.requests.get = orig
    c = out["candles"][0]
    check("腾讯 K 线：source/candles 解析正确",
          out["source"] == "tencent" and c["open"] == 3.323 and c["close"] == 3.341
          and c["high"] == 3.354 and c["low"] == 3.280,
          str(c))
    # CR9-29（2026-09-26）：腾讯日 K 每行恰 6 字段、无成交额（实测）。原行为是"键不存在"
    # ⇒ 同一端点在主源/备源下形态不同，消费端只能靠猜。现契约：字段恒在 + 值 null + note 说明。
    check("CR9-29🔁：amount 键恒在且为 null（不再静默缺字段）", "amount" in c and c["amount"] is None, str(c))
    check("CR9-29🔁：响应 note 显式声明成交额不可用", "成交额" in str(out.get("note")), str(out.get("note")))

    # 行情解析（程序化构造，字段位标 30/31/32/33/34）
    fields = ["51", "创业板ETF易方达", "159915", "3.341", "3.358", "3.323", "19052972", "9905270", "9147702"]
    fields += [str(i) for i in range(20)]
    fields += ["3.341/19052972/6320257883", "20260911150000", "-0.017", "-0.51", "3.354", "3.280"]
    payload = 'v_sz159915="' + "~".join(fields) + '";'

    class QResp:
        content = payload.encode("gbk")

        def raise_for_status(self):
            pass

    tp.requests.get = lambda *a, **k: QResp()
    try:
        q = TencentProvider().get_quote("fund", "159915")
    finally:
        tp.requests.get = orig
    check("腾讯行情：价格/涨跌幅/高低解析正确",
          q["price"] == 3.341 and q["changePct"] == -0.51
          and q["high"] == 3.354 and q["low"] == 3.280,
          str({k: q[k] for k in ("price", "changePct", "high", "low")}))
    # CR9-7：原断言为 `== "20260911150000"`，那等于把"备源时间戳原样透传"锁成契约。
    # 现断言归一后的 ISO 形态（若回退 _ts_iso，本条精确失败）。
    check("腾讯行情：时间字段归一为 ISO（CR9-7）",
          q["timestamp"] == "2026-09-11T15:00:00", str(q["timestamp"]))
    check("腾讯行情：备源也带币种（CR9-6，A股=CNY）", q.get("currency") == "CNY", str(q.get("currency")))


# ---------- CR5-1：CoinGecko 失败负缓存（修复静默失效的回归防线） ----------


def test_crypto_failure_negative_cache() -> None:
    """CR5-1（2026-09-17 review）：失败路径必须与成功路径对称记账。

    背景：`_markets_fail_ts` 此前只在 __init__ 与**成功**路径置 0，失败路径从不写入，
    导致守卫 `now - fail_ts < CG_FAIL_COOLDOWN` 恒假 → 负缓存是死代码，
    CoinGecko 不可达时每个 crypto 请求仍完整重试约 41s。
    """
    import app.providers.crypto_provider as cp

    provider = cp.CoinGeckoProvider()
    calls = {"n": 0}

    def _boom(path, params):
        calls["n"] += 1
        raise ProviderError("coingecko unreachable (simulated)")

    orig_request = provider._request
    orig_sleep = cp.time.sleep
    orig_time = cp.time.time
    provider._request = _boom
    cp.time.sleep = lambda *_: None  # 避免测试真的 sleep
    try:
        # 第一次：真实尝试并失败
        raised1 = False
        try:
            provider.get_quote("crypto", "BTC")
        except ProviderError:
            raised1 = True
        check("CR5-1：首次失败如实抛错", raised1)
        check("CR5-1：首次失败确实发起了外部请求", calls["n"] == 1, str(calls))

        # 第二次：必须命中负缓存，**不得**再发起外部请求
        raised2 = False
        msg = ""
        try:
            provider.get_quote("crypto", "BTC")
        except ProviderError as e:
            raised2 = True
            msg = str(e)
        check("CR5-1：冷却期内再次调用仍抛降级错误", raised2)
        check("CR5-1：冷却期内不再发起外部请求（负缓存生效）", calls["n"] == 1, str(calls))
        check("CR5-1：降级说明含冷却提示", "cooling down" in msg, msg)

        # 越过冷却窗口后应可恢复重试
        cp.time.time = lambda: 1e12  # 远大于 _markets_fail_ts
        provider._request = lambda path, params: [
            {"symbol": "btc", "name": "Bitcoin", "current_price": 1.0}
        ]
        quote = provider.get_quote("crypto", "BTC")
        check("CR5-1：冷却窗口过后可恢复", quote.get("code") == "BTC", str(quote))
    finally:
        provider._request = orig_request
        cp.time.sleep = orig_sleep
        cp.time.time = orig_time


# ---------- CR6-P1-3：K 线脏行（null OHLC）契约统一 ----------


def test_kline_null_ohlc_filtered() -> None:
    """CR6-P1-3（2026-09-18 review）：akshare/tencent 必须剔除 OHLC 缺失的行。

    KlineDaily.open/high/low/close 为 NOT NULL，单行 null 会让 web 侧整批
    upsert 失败、该标的 K 线持续不可用。以 sina 为契约基准，任一 OHLC
    为 None 即跳过该行（其余行保留）。
    """
    import app.providers.akshare_provider as akp
    import app.providers.tencent_provider as tp

    # --- akshare/eastmoney：一行正常 + 一行 open 为 "-"（→ None）---
    # 格式：日期,开,收,高,低,量,额,...
    good = "2026-09-11,10.0,10.5,10.8,9.9,1000,10500,1.0,5.0,0.5,1.0"
    bad = "2026-09-12,-,10.5,10.8,9.9,1000,10500,1.0,5.0,0.5,1.0"
    orig_em = akp._em_request
    akp._em_request = lambda fn: [good, bad]
    try:
        out = akp.AkshareProvider().get_kline("stock", "600000", "20260911", "20260912")
    finally:
        akp._em_request = orig_em
    dates = [c["date"] for c in out["candles"]]
    check("CR6-P1-3：akshare 剔除 null OHLC 行（保留正常行）",
          dates == ["2026-09-11"], str(dates))

    # --- tencent：一行正常 + 一行 high 为 "-"（非数值）---
    class KResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "sz159915": {
                        "qfqday": [
                            ["2026-09-11", "3.323", "3.341", "3.354", "3.280", "100"],
                            ["2026-09-12", "3.400", "3.410", "-", "3.390", "100"],
                        ]
                    }
                }
            }

    orig_get = tp.requests.get
    tp.requests.get = lambda *a, **k: KResp()
    try:
        tout = tp.TencentProvider().get_kline("fund", "159915", "20260911", "20260912")
    finally:
        tp.requests.get = orig_get
    tdates = [c["date"] for c in tout["candles"]]
    check("CR6-P1-3：tencent 剔除 null OHLC 行（保留正常行）",
          tdates == ["2026-09-11"], str(tdates))


# ---------- CR-19：场外基金净值表单失败负缓存 ----------


def test_fund_nav_failure_negative_cache() -> None:
    """CR-19（本轮 code review）：失败路径必须与成功路径对称记账。

    此前 `_fund_nav_table` 失败时不写任何冷却时间戳 → 限流期每个场外基金请求
    都会整表重拉（60s 看门狗），反复捶打天天基金。修复后失败写 `_fund_nav_fail_ts`，
    冷却期内直接降级不再发起外部请求。
    """
    import app.providers.akshare_provider as akp

    provider = akp.AkshareProvider()
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("nav table blocked (simulated)")

    orig = akp._ak_request
    akp._ak_request = _boom
    try:
        # 第一次：真实尝试并失败
        raised1 = False
        try:
            provider._fund_nav_table()
        except ProviderError:
            raised1 = True
        check("CR-19：净值表首次失败如实抛错", raised1)
        check("CR-19：首次失败确实发起外部请求", calls["n"] == 1, str(calls))

        # 第二次：命中失败冷却，不再发起外部请求
        raised2 = False
        msg = ""
        try:
            provider._fund_nav_table()
        except ProviderError as e:
            raised2 = True
            msg = str(e)
        check("CR-19：冷却期内仍抛降级错误", raised2)
        check("CR-19：冷却期内不再发起外部请求（负缓存生效）", calls["n"] == 1, str(calls))
        check("CR-19：降级说明含冷却提示", "cooling down" in msg, msg)
    finally:
        akp._ak_request = orig


def test_fund_nav_empty_table_and_missing_columns() -> None:
    """C2（CR7-8，2026-09-25）：空表/列缺失必须显式降级，不得"成功但空"。

    此前：① `_fund_nav_table` 拿到空 df 照样写缓存 30min（"成功但空"），
    期间**所有**场外基金静默无净值；② `_fund_nav_quotes` 定位不到净值列时
    `return {}` 无 note 无冷却。修复后两者都抛 ProviderError 进失败窗口。
    """
    import pandas as pd

    import app.providers.akshare_provider as akp

    provider = akp.AkshareProvider()
    # 复位实例缓存（该 provider 实例可能与其它测试共享模块级单例）
    provider._fund_nav = None
    provider._fund_nav_ts = 0.0
    provider._fund_nav_fail_ts = 0.0

    orig = akp._ak_request

    # ① 空 df → 抛 ProviderError 且记失败冷却
    akp._ak_request = lambda *a, **k: pd.DataFrame()
    try:
        raised = False
        try:
            provider._fund_nav_table()
        except ProviderError as e:
            raised = "empty" in str(e)
        check("C2🔁：空表如实抛错（不写成功缓存）", raised)
        check(
            "C2🔁：空表计入失败冷却",
            provider._fund_nav_fail_ts > 0,
            str(provider._fund_nav_fail_ts),
        )
        # 冷却期内再次调用不发外部请求
        calls = {"n": 0}

        def _count(*a, **k):
            calls["n"] += 1
            return pd.DataFrame()

        akp._ak_request = _count
        try:
            provider._fund_nav_table()
            check("C2🔁：空表冷却期内不再请求", False, "未抛错")
        except ProviderError:
            check("C2🔁：空表冷却期内不再请求", calls["n"] == 0, str(calls))
    finally:
        akp._ak_request = orig
        provider._fund_nav = None
        provider._fund_nav_ts = 0.0
        provider._fund_nav_fail_ts = 0.0

    # ② 列缺失（上游改列名）→ _fund_nav_quotes 抛 ProviderError 而非 return {}
    ok_df = pd.DataFrame(
        {
            "基金代码": ["012414"],
            "基金简称": ["测试基金"],
            "2026-09-24-单位净值": [1.2345],
            "日增长率": [0.12],
        }
    )
    provider._fund_nav = ok_df
    provider._fund_nav_ts = time.time() + 10**9  # 缓存命中，跳过外部请求
    try:
        quotes = provider._fund_nav_quotes(["012414"])
        check("C2🔁：列齐全时正常产出", quotes.get("012414", {}).get("price") == 1.2345, str(quotes)[:80])

        bad_df = ok_df.rename(columns={"2026-09-24-单位净值": "单位净值"})  # 去掉日期前缀
        provider._fund_nav = bad_df
        raised = False
        msg = ""
        try:
            provider._fund_nav_quotes(["012414"])
        except ProviderError as e:
            raised = True
            msg = str(e)
        check("C2🔁：净值列缺失 → ProviderError（不再 return {}）", raised, msg[:120])
        check("C2🔁：错误说明含列名诊断", "columns missing" in msg and "日增长率" in msg, msg[:160])
    finally:
        provider._fund_nav = None
        provider._fund_nav_ts = 0.0
        provider._fund_nav_fail_ts = 0.0


def test_abandoned_watchdog_count() -> None:
    """CR-22：超时放弃的看门狗线程应被计数（观测用）。"""
    import time as _t

    from app.utils import timeout as to

    before = to.abandoned_count()
    # 一个必然超时的调用：fn 睡 2s，超时 0.1s
    value, err = to.run_with_timeout(lambda: _t.sleep(2.0) or "done", 0.1, "cr22-slow")
    check("CR-22：超时返回 (None, TimeoutError)", value is None and isinstance(err, TimeoutError))
    check("CR-22：放弃线程计数 +1", to.abandoned_count() == before + 1, str(to.abandoned_count()))
    # 正常完成的调用不计入
    v2, e2 = to.run_with_timeout(lambda: "ok", 1.0, "cr22-fast")
    check("CR-22：正常完成不计入", v2 == "ok" and e2 is None and to.abandoned_count() == before + 1)


def test_abandoned_count_race_narrow_window() -> None:
    """D2（CR7-12，2026-09-25）：窄窗口竞态——超时放弃后线程立刻自然结束。

    此前时序：主线程 join 超时 → 锁外置 box["_abandoned"]=True → 拿锁 +1；
    runner 恰在"置标志前"走到 finally 读标志（无值）→ 不递减 → 计数虚高 +1。
    修复后置标志/递减同锁互斥，且主线程拿锁后二次确认 is_alive()。
    压测 N 次"超时阈值极贴边"的调用（fn 快速完成但 join 更快到期），
    断言计数最终精确回落——修复前此断言会偶发虚高。
    """
    import time as _t

    from app.utils import timeout as to

    before = to.abandoned_count()
    # fn 立即完成，join 用极短超时——制造"主线程判超时 vs 线程实际已完成"的贴边窗口
    for i in range(50):
        to.run_with_timeout(lambda: i, 0.0005, f"race-{i}")
    # 等 runner 们全部走完 finally
    _t.sleep(0.5)
    after = to.abandoned_count()
    check(
        "D2🔁：贴边竞态 50 次后计数精确（无虚增）",
        after == before,
        f"before={before} after={after}（虚增 {after - before}）",
    )


def test_fund_holdings_missing_column_and_beijing_dates() -> None:
    """CR9-17 / CR9-16（2026-09-26）：持仓表缺列的降级形态 + 日期一律走北京时间。

    CR9-17：`get_fund_holdings` 里 `df["季度"]` 原本落在 try 之外，上游一改列名就是裸
    `KeyError` → HTTP 500（C2 同族：外部数据的列缺失必须显式降级，不许冒泡）。
    CR9-16：分钟线"当日"窗口与持仓/报告的年份枚举都用过本地 `date.today()`（§B 禁用），
    这里把 `beijing_today` 钉成一个与本机不同的日期来断口径——若代码仍走本地时区必挂。
    """
    import types

    import pandas as pd

    import app.providers.akshare_provider as akp

    provider = akp.AkshareProvider()
    orig_ak_req = akp._ak_request

    good = pd.DataFrame(
        [{"季度": "2026年1季度", "股票代码": "600519", "股票名称": "贵州茅台", "占净值比例": 5.1}]
    )
    no_col = pd.DataFrame([{"股票简称": "某股票", "占净值比例": 1.0}])

    # ① 缺「季度」列 → ProviderError（含列名诊断），且绝不是 KeyError
    akp._ak_request = lambda *a, **k: no_col
    try:
        kind = "none"
        msg = ""
        try:
            provider.get_fund_holdings("012414")
        except ProviderError as e:
            kind, msg = "ProviderError", str(e)
        except Exception as e:  # noqa: BLE001
            kind, msg = type(e).__name__, str(e)
        check("CR9-17🔁：缺列不冒泡成 KeyError", kind == "ProviderError", f"{kind}: {msg[:120]}")
        # 注意：不能只断 "季度" in msg —— 裸 KeyError 的文本本身就是 "'季度'"，
        # 那样这条断言在坏状态下也是绿的（回退实证抓到过）。必须断"显式降级"的措辞。
        check("CR9-17🔁：降级说明为显式缺列诊断", "缺列" in msg and "季度" in msg, msg[:160])
        check("CR9-17🔁：降级说明带实际列名可诊断", "实际列" in msg, msg[:160])
    finally:
        akp._ak_request = orig_ak_req

    # ② 正向对照：列齐全必须照常产出（证明 ① 不是恒假的桩）
    akp._ak_request = lambda *a, **k: good
    try:
        out = provider.get_fund_holdings("012414")
        check(
            "CR9-17🔁：列齐全时正常产出持仓（正向对照）",
            out.get("quarter") == "2026年1季度" and len(out.get("holdings") or []) == 1,
            str(out)[:160],
        )
    finally:
        akp._ak_request = orig_ak_req

    # ③ CR9-16：1m 的 beg/end 必须是北京日期（把 beijing_today 钉成非本机日期）
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": {"klines": ["2026-03-31 09:30,1.0,2.0,0.5,1.5,100,20000"]}}

    def _fake_get(url, params=None, **kw):
        captured["params"] = params
        return _Resp()

    orig_requests = akp.requests
    orig_em_request = akp._em_request
    orig_today = akp.beijing_today
    akp.requests = types.SimpleNamespace(get=_fake_get)
    # 绕开源族令牌桶：本用例只验日期口径，不该被限速器状态左右
    akp._em_request = lambda fn, *a, **k: fn()
    akp.beijing_today = lambda: "2026-03-31"
    try:
        out = provider.get_kline("stock", "600519", interval="1m")
        p = captured.get("params") or {}
        check(
            "CR9-16🔁：1m 请求的 beg/end = 北京日期紧凑串",
            p.get("beg") == "20260331" and p.get("end") == "20260331",
            str(p)[:160],
        )
        check("CR9-16🔁：klt=1 且分时解析出 1 根", p.get("klt") == "1" and len(out.get("candles") or []) == 1, str(out)[:160])
    finally:
        akp.requests = orig_requests
        akp._em_request = orig_em_request
        akp.beijing_today = orig_today

    # ④ CR9-16：持仓年份枚举走北京时区年（本机年 + 上一年），不再引用 date.today()
    import inspect

    src = inspect.getsource(akp.AkshareProvider.get_fund_holdings)
    check("CR9-16🔁：get_fund_holdings 源码内不再出现 date.today()", "date.today()" not in src, src[:120])
    check("CR9-16🔁：改用 beijing_now().year", "beijing_now().year" in src)


if __name__ == "__main__":
    test_limiter()
    test_limiter_profile_single_source()
    test_akshare_out_of_bucket_observation()
    test_list_products_meta()
    test_products_endpoint_passthrough_meta()
    test_stock_name_status_prefix()
    test_stock_list_backup_source()
    test_symbol_mapping()
    test_chain()
    test_tencent_parsers()
    test_crypto_failure_negative_cache()
    test_kline_null_ohlc_filtered()
    test_fund_nav_failure_negative_cache()
    test_fund_nav_empty_table_and_missing_columns()
    test_fund_holdings_missing_column_and_beijing_dates()
    test_abandoned_watchdog_count()
    test_abandoned_count_race_narrow_window()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
