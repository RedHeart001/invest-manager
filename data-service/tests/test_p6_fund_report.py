"""P6 离线单测：基金定期报告数据解析契约（不依赖东财可用性）。

运行方式：
    .venv/Scripts/python tests/test_p6_fund_report.py

背景：spike（2026-09-13）确认 `fund_announcement_report_em` 按日期**升序**返回
（升序取 head 会拿到 2013 年老数据，P5 曾因此在财务摘要上踩坑），
本测试用合成数据锁定"倒序取最新 + 定期报告过滤"的契约。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from app.providers.akshare_provider import AkshareProvider  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# 模拟 akshare：公告按日期升序（与真实接口一致）
ANNOUNCEMENTS = pd.DataFrame(
    [
        {"基金代码": "110022", "公告标题": "易方达消费行业股票型证券投资基金2013年半年度报告", "基金名称": "易方达消费行业股票", "公告日期": "2013-08-28", "报告ID": "A1"},
        {"基金代码": "110022", "公告标题": "易方达消费行业股票型证券投资基金2013年第3季度报告", "基金名称": "易方达消费行业股票", "公告日期": "2013-10-25", "报告ID": "A2"},
        {"基金代码": "110022", "公告标题": "易方达基金管理有限公司旗下基金资产净值公告", "基金名称": "易方达消费行业股票", "公告日期": "2026-01-02", "报告ID": "A3"},
        {"基金代码": "110022", "公告标题": "易方达消费行业股票型证券投资基金2026年第2季度报告", "基金名称": "易方达消费行业股票", "公告日期": "2026-07-18", "报告ID": "A4"},
        {"基金代码": "110022", "公告标题": "易方达消费行业股票型证券投资基金2026年半年度报告", "基金名称": "易方达消费行业股票", "公告日期": "2026-08-28", "报告ID": "A5"},
    ]
)

INDUSTRY = pd.DataFrame(
    [
        {"序号": 1, "行业类别": "制造业", "占净值比例": 87.08, "市值": 1.3e6, "截止时间": "2025-12-31"},
        {"序号": 2, "行业类别": "农林牧渔业", "占净值比例": 3.18, "市值": 4.7e4, "截止时间": "2025-12-31"},
        {"序号": 3, "行业类别": "信息传输软件业", "占净值比例": 12.6, "市值": 8.9e3, "截止时间": "2025-12-31"},
        {"序号": 4, "行业类别": "合计", "占净值比例": None, "市值": None, "截止时间": "2025-12-31"},
    ]
)


class FakeAk:
    def __init__(self, ann, ind, fail_ann=False, fail_ind=False):
        self._ann, self._ind = ann, ind
        self._fail_ann, self._fail_ind = fail_ann, fail_ind
        self.calls: list[str] = []

    def fund_announcement_report_em(self, symbol: str):
        self.calls.append(f"ann:{symbol}")
        if self._fail_ann:
            raise RuntimeError("em blocked")
        return self._ann

    def fund_portfolio_industry_allocation_em(self, symbol: str, date: str):
        self.calls.append(f"ind:{symbol}:{date}")
        if self._fail_ind:
            raise RuntimeError("em blocked")
        return self._ind


def install(monkeypatch_ak: FakeAk) -> None:
    sys.modules["akshare"] = monkeypatch_ak  # type: ignore[assignment]


def fresh_provider() -> AkshareProvider:
    p = AkshareProvider()
    # 绕开源族限速器（本测试关注解析契约，不关注限流）
    import app.providers.akshare_provider as mod

    mod.EM_LIMITER.acquire = lambda timeout=20.0: True  # type: ignore[assignment]
    mod.EM_LIMITER.on_success = lambda: None  # type: ignore[assignment]
    mod.EM_LIMITER.on_failure = lambda: None  # type: ignore[assignment]
    return p


# ---------- 正常路径 ----------

install(FakeAk(ANNOUNCEMENTS, INDUSTRY))
prov = fresh_provider()
data = prov.get_fund_report("110022")

check("返回 code 与 source", data["code"] == "110022" and "fund-report" in data["source"], str(data.get("source")))
check("报告清单非空", len(data["reports"]) > 0, f"n={len(data['reports'])}")

titles = [r["title"] for r in data["reports"]]
dates = [r["date"] for r in data["reports"]]
check("日期倒序（最新在前）", dates == sorted(dates, reverse=True), str(dates))
check(
    "只保留定期报告（过滤净值公告）",
    all(any(k in t for k in ("季度报告", "半年度报告", "年度报告")) for t in titles),
    str(titles),
)
check("最新一条为 2026 年半年度报告", "2026年半年度报告" in titles[0], titles[0] if titles else "")
check("报告清单上限 8 条", len(data["reports"]) <= 8, f"n={len(data['reports'])}")

ind = data["industry"]
check("行业配置非空", bool(ind), str(ind))
check("行业配置截至日正确", ind and ind["asOf"] == "2025-12-31", str(ind.get("asOf") if ind else None))
check("行业按占比降序", ind and [i["weight"] for i in ind["items"]] == sorted([i["weight"] for i in ind["items"]], reverse=True), str(ind.get("items") if ind else None))
check("合计行（占比缺失）被剔除", ind and all(i["name"] != "合计" for i in ind["items"]))
check("行业配置上限 10 项", ind and len(ind["items"]) <= 10, f"n={len(ind['items']) if ind else 0}")

# 缓存：二次调用不再打外部源
before = len(sys.modules["akshare"].calls)
prov.get_fund_report("110022")
check("6 小时缓存生效（二次调用零外部请求）", len(sys.modules["akshare"].calls) == before, f"calls={sys.modules['akshare'].calls[before:]}")

# ---------- 降级路径 ----------

install(FakeAk(ANNOUNCEMENTS, INDUSTRY, fail_ann=True))
prov2 = fresh_provider()
data2 = prov2.get_fund_report("110022")
check("报告清单失败不阻塞行业配置", len(data2["reports"]) == 0 and bool(data2["industry"]), str(list(data2.keys())))

install(FakeAk(ANNOUNCEMENTS, INDUSTRY, fail_ind=True))
prov3 = fresh_provider()
data3 = prov3.get_fund_report("110022")
check("行业配置失败不阻塞报告清单", len(data3["reports"]) > 0 and data3["industry"] is None)

install(FakeAk(ANNOUNCEMENTS, INDUSTRY, fail_ann=True, fail_ind=True))
prov4 = fresh_provider()
try:
    prov4.get_fund_report("110022")
    check("全部失败 → ProviderError（页面显式缺口）", False, "未抛错")
except ProviderError as e:
    check("全部失败 → ProviderError（页面显式缺口）", "fund report failed" in str(e), str(e)[:80])

failed = [r for r in results if not r[1]]
print(f"\n== 基金定期报告解析单测：{len(results) - len(failed)}/{len(results)} 通过 ==")
if failed:
    for name, _, detail in failed:
        print(f"  - {name} {detail}")
    sys.exit(1)
