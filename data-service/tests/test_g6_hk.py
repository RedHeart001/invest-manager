"""G6 离线单测：港股 provider 注册、解析契约与多 host 降级（不依赖网络）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.providers import get_list_provider, get_provider_chain  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def test_registration() -> None:
    chain = [p.source for p in get_provider_chain("hk")]
    check("G6：hk 行情链已注册", "akshare-hk" in chain, str(chain))
    check("G6：hk 列表 provider 已注册", get_list_provider("hk").source == "akshare-hk")


def test_quote_and_list_parsing() -> None:
    """行情（快路径 stock/get）+ 批量（ulist）+ 列表（分页）解析契约。"""
    import app.providers.hk_provider as hp

    # --- 单股行情：mock _em_json 返回 stock/get 结构 ---
    class _P:
        def __init__(self):
            self.calls = []

    def _fake_em_json(hosts, path, params):
        if path.endswith("/stock/get"):
            return {"data": {
                "f57": "00700", "f58": "腾讯控股", "f43": 419.0, "f169": -7.0,
                "f170": -1.64, "f46": 428.0, "f44": 430.4, "f45": 419.0,
                "f60": 426.0, "f47": 28796138.0, "f48": 1.2e10, "f116": 4e12,
            }}
        if path.endswith("/ulist.np/get"):
            return {"data": {"diff": [
                {"f12": "00700", "f14": "腾讯控股", "f2": 419.0, "f3": -1.64, "f4": -7.0},
                {"f12": "09988", "f14": "阿里巴巴-W", "f2": 80.0, "f3": -1.23, "f4": -1.0},
            ]}}
        if path.endswith("/clist/get"):
            pn = params.get("pn", "1")
            if pn == "1":
                return {"data": {"total": 3, "diff": [{"f12": "89988", "f14": "阿里巴巴-WR"}]}}
            return {"data": {"total": 3, "diff": [
                {"f12": "00700", "f14": "腾讯控股"},
                {"f12": "09988", "f14": "阿里巴巴-W"},
            ]}}
        raise AssertionError(path)

    p = hp.HkProvider()
    p._em_json = _fake_em_json  # type: ignore[assignment]

    q = p.get_quote("hk", "00700")
    check("G6：单股行情字段映射正确（stock/get）",
          q["price"] == 419.0 and q["changePct"] == -1.64 and q["prevClose"] == 426.0 and q["name"] == "腾讯控股",
          str({k: q[k] for k in ("price", "changePct", "prevClose", "name")}))
    check("G6：行情标注币种 HKD", q.get("currency") == "HKD")
    check("G6：source 标注 akshare-hk", q.get("source") == "akshare-hk")

    qs = p.get_quotes("hk", ["00700", "09988"])
    check("G6：批量行情 2/2（ulist）", len(qs) == 2 and qs["09988"]["price"] == 80.0, str(list(qs.keys())))

    prods = p.list_products("hk")
    check("G6：列表分页合并（1+2=3 条）", len(prods) == 3, str(len(prods)))
    check("G6：列表字段齐备（exchange/pinyin）",
          all(x["exchange"] == "HK" and x["pinyinInitials"] for x in prods) and {x["code"] for x in prods} == {"89988", "00700", "09988"},
          str([x["code"] for x in prods]))
    check("G6：列表 type=hk", all(x["type"] == "hk" for x in prods))


def test_quote_does_not_trigger_list_paging() -> None:
    """关键设计约束（2026-09-20 修正）：行情路径**不得**触发全量列表分页。
    早期版本 get_quote 复用列表快照 → 查单个港股需拉 4700 条（约 4 分钟）。"""
    import app.providers.hk_provider as hp

    seen_paths: list[str] = []

    def _fake_em_json(hosts, path, params):
        seen_paths.append(path)
        return {"data": {"f57": "00700", "f58": "腾讯控股", "f43": 419.0}}

    p = hp.HkProvider()
    p._em_json = _fake_em_json  # type: ignore[assignment]
    p.get_quote("hk", "00700")

    check("G6：行情只打 stock/get，不打 clist/get（性能红线）",
          seen_paths == ["/api/qt/stock/get"], str(seen_paths))


def test_multi_host_failover() -> None:
    """G6 修复（2026-09-20 实测）：akshare 硬编码 72.push2 不可达，
    故改为直连 + 多 host 降级。验证：首节点失败 → 自动切次节点成功。"""
    import app.providers.hk_provider as hp

    p = hp.HkProvider()
    calls: list[str] = []

    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    def _fake_get(url, **kw):
        calls.append(url)
        if "push2delay" not in url and "/7." not in url:
            # 模拟首个可降级节点（push2）被 RemoteDisconnected
            raise ConnectionError("Remote end closed connection without response")
        return _Resp({"data": {"f57": "00700", "f58": "腾讯控股", "f43": 419.0}})

    orig_get = hp.requests.get
    hp.requests.get = _fake_get
    try:
        q = p.get_quote("hk", "00700")
    finally:
        hp.requests.get = orig_get

    check("G6：多 host 降级——首节点失败后切换成功", q["price"] == 419.0 and q["name"] == "腾讯控股", str(q))
    check("G6：确实尝试了多个 host", len(calls) >= 2, f"calls={len(calls)}")

    # 全部节点失败 → 抛 ProviderError（不静默返回空）
    def _all_fail(url, **kw):
        raise ConnectionError("Remote end closed connection without response")

    hp.requests.get = _all_fail
    try:
        raised = False
        try:
            hp.HkProvider().get_quote("hk", "00700")
        except Exception as e:  # noqa: BLE001
            raised = type(e).__name__ == "ProviderError"
        check("G6：全节点失败 → ProviderError（显式降级）", raised)
    finally:
        hp.requests.get = orig_get


def test_type_guard() -> None:
    import app.providers.hk_provider as hp
    from app.providers.base import ProviderNotSupported

    p = hp.HkProvider()
    raised = False
    try:
        p.get_quote("stock", "600519")
    except ProviderNotSupported:
        raised = True
    check("G6：错误类型抛 ProviderNotSupported", raised)


# ---------- G6 备源：腾讯港股（符号映射 + 解析 + 链路） ----------


def test_tencent_hk_symbol_mapping() -> None:
    """港股 5 位数字与 A股 6 位冲突，必须按类型显式分派（PLAN M8 认知）。"""
    from app.providers.tencent_provider import _hk_symbol, _symbol, _symbol_for

    # 港股符号
    check("腾讯港股符号：00700 → hk00700", _hk_symbol("00700") == "hk00700", str(_hk_symbol("00700")))
    check("腾讯港股符号：89988 → hk89988", _hk_symbol("89988") == "hk89988", str(_hk_symbol("89988")))
    check("腾讯港股符号：700 补零 → hk00700", _hk_symbol("700") == "hk00700", str(_hk_symbol("700")))
    check("腾讯港股符号：6 位非港股 → None", _hk_symbol("600519") is None, str(_hk_symbol("600519")))
    check("腾讯港股符号：非数字 → None", _hk_symbol("AAPL") is None, str(_hk_symbol("AAPL")))

    # 分派：hk 走港股，其它走 A股（A股规则零改动）
    check("分派 hk：00700 → hk00700", _symbol_for("hk", "00700") == "hk00700")
    check("分派 stock：600519 → sh600519（不受影响）", _symbol_for("stock", "600519") == "sh600519")
    check("分派 fund：159915 → sz159915（不受影响）", _symbol_for("fund", "159915") == "sz159915")
    # 关键回归：若无类型分派，00700 会被误判为深市
    check("对照：_symbol 对 00700 的误判（证明必须分派）", _symbol("00700") == "sz00700", str(_symbol("00700")))


def test_tencent_hk_quote_and_kline_parsing() -> None:
    """腾讯港股行情/K线解析（合成数据锁定契约，字段位置与 A股一致）。"""
    import app.providers.tencent_provider as tp

    # 行情：字段位 [1]名称 [3]现价 [4]昨收 [5]今开 [30]时间 [31]涨跌 [32]涨跌幅 [33]高 [34]低
    # 构造：index 0-6 前置 7 项，再补 index 7-29（23 项），最后 index 30-34（5 项）
    fields = ["100", "腾讯控股", "00700", "419.000", "426.000", "428.000", "28796138.0"]
    fields += [str(i) for i in range(23)]  # index 7..29
    fields += ["2026/09/18 16:08:32", "-7.000", "-1.64", "430.400", "419.000"]  # index 30..34
    payload = 'v_hk00700="' + "~".join(fields) + '";'
    assert len(fields) == 35, len(fields)

    class _QResp:
        content = payload.encode("gbk")

        def raise_for_status(self):
            pass

    orig = tp.requests.get
    tp.requests.get = lambda *a, **k: _QResp()
    try:
        q = tp.TencentProvider().get_quote("hk", "00700")
    finally:
        tp.requests.get = orig
    check("G6 备源：港股行情解析正确",
          q["price"] == 419.0 and q["changePct"] == -1.64 and q["prevClose"] == 426.0
          and q["high"] == 430.4 and q["low"] == 419.0 and q["name"] == "腾讯控股",
          str({k: q[k] for k in ("price", "changePct", "prevClose", "high", "low", "name")}))
    check("G6 备源：港股行情 source=tencent", q.get("source") == "tencent", str(q.get("source")))

    # K线：data.hk00700.day = [[日期,开,收,高,低,量], ...]
    class _KResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"hk00700": {"day": [
                ["2026-09-18", "428.000", "419.000", "430.400", "419.000", "28796138.000"],
                ["2026-09-17", "432.000", "426.000", "434.000", "425.000", "15000000.000"],
            ]}}}

    tp.requests.get = lambda *a, **k: _KResp()
    try:
        k = tp.TencentProvider().get_kline("hk", "00700", "20260901", "20260920")
    finally:
        tp.requests.get = orig
    c0 = k["candles"][0]
    check("G6 备源：港股K线解析正确（开/收/高/低）",
          c0["open"] == 428.0 and c0["close"] == 419.0 and c0["high"] == 430.4 and c0["low"] == 419.0,
          str(c0))
    check("G6 备源：港股K线 2 根且日期正确", len(k["candles"]) == 2 and c0["date"] == "2026-09-18", str(len(k["candles"])))


def test_hk_chain_order() -> None:
    """链路顺序：东财主源在前、腾讯备源在后。"""
    chain = [p.source for p in get_provider_chain("hk")]
    check("G6：hk 链顺序 = 东财主源 + 腾讯备源", chain == ["akshare-hk", "tencent"], str(chain))


if __name__ == "__main__":
    test_registration()
    test_quote_and_list_parsing()
    test_quote_does_not_trigger_list_paging()
    test_multi_host_failover()
    test_type_guard()
    test_tencent_hk_symbol_mapping()
    test_tencent_hk_quote_and_kline_parsing()
    test_hk_chain_order()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
