"""CR9-108 离线单测：转债→正股映射（#75 的只读腿）。**零出网**。

运行方式：
    .venv/Scripts/python tests/test_cr9_108_bond_map.py

为什么全用替身（10-16）：这一枚真跑＝akshare 内部按 `pageSize=500` 逐页循环 ≈4 个 HTTP、
占东财桶 1 枚令牌，而本刀要证的只是**解析与缓存契约**（那两列读不读得出／读不出时说的是
哪一句／TTL 有没有生效／失败有没有被缓存）。上游可用性由一次到场 `--live` 证明，归人工。

⚠️ `LIMITER_STATE_FILE` 在 import 之前就指到临时目录：本文件后半段要 `import app.main`
测路由形状，落盘纪律与 `test_cr9_92_realtime.py:22`／`test_p2_m8.py:354` 同一条——不指走
就会把测试计数倒进仓库那份 `runtime/limiter-state.json`（那是 CR9-97 那枚闸唯一的读数面）。
"""

import os
import sys
import tempfile

_STATE = os.path.join(tempfile.mkdtemp(prefix="cr9108-limiter-"), "limiter-state.json")
os.environ["LIMITER_STATE_FILE"] = _STATE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd  # noqa: E402

import app.main as m  # noqa: E402
import app.providers.akshare_provider as mod  # noqa: E402
from app.providers.akshare_provider import AkshareProvider  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


# 10-13 那枚探针实测到的形状（`windowC-bondmap-1013c.out` 的 samplePairs 字面）：
# [["127118","001380"],["118077","688150"],["123288","301149"]] ⇒ 代码是保住前导零的字符串。
COV = pd.DataFrame(
    [
        {"债券代码": "110002", "债券简称": "东山转债", "正股代码": "300001", "正股简称": "特锐德"},
        {"债券代码": "127118", "债券简称": "广信转债", "正股代码": "001380", "正股简称": "捷荣技术"},
        {"债券代码": "113009", "债券简称": "量化升位", "正股代码": 600519.0, "正股简称": "贵州茅台"},
        {"债券代码": "118077", "债券简称": "短码该行", "正股代码": 1380.0, "正股简称": "缺零的那只"},
    ]
)
# 在册但整列都答不出（空／NaN）——这一形必须与"代码不在册"分开说
BLANK = pd.DataFrame(
    [
        {"债券代码": "110002", "债券简称": "东山转债", "正股代码": "", "正股简称": "特锐德"},
        {"债券代码": "113009", "债券简称": "NaN 行", "正股代码": None, "正股简称": None},
    ]
)


class FakeAk:
    def __init__(self, df, fail=False):
        self._df, self._fail = df, fail
        self.calls: list[str] = []

    def bond_zh_cov(self):
        self.calls.append("bond_zh_cov")
        if self._fail:
            raise RuntimeError("em blocked")
        return self._df


def install(fake: FakeAk) -> FakeAk:
    sys.modules["akshare"] = fake  # type: ignore[assignment]
    return fake


def fresh_provider() -> AkshareProvider:
    p = AkshareProvider()
    # 本测试关注解析与缓存契约，不关注限流：把源族限速器绕开（与 test_p6_fund_report 同写法）
    mod.EM_LIMITER.acquire = lambda timeout=20.0: True  # type: ignore[assignment]
    mod.EM_LIMITER.on_success = lambda: None  # type: ignore[assignment]
    mod.EM_LIMITER.on_failure = lambda: None  # type: ignore[assignment]
    return p


def grab(fn):
    try:
        fn()
        return None
    except ProviderError as e:
        return str(e)


# ---------- 正常路径 ----------

fake = install(FakeAk(COV))
prov = fresh_provider()
d = prov.get_bond_underlying("110002")

check(
    "正股代码与简称读得出（#75 这一刀的判别枚：那两列此前在 :1134 被丢掉）",
    d["stockCode"] == "300001" and d["stockName"] == "特锐德",
    str(d),
)
check(
    "转债名＋整张表行数一起带出（mapSize 是机器可读的覆盖位，不进屏）",
    d["bondName"] == "东山转债" and d["mapSize"] == 4,
    str(d),
)
check("source 说的是真出网那一家", d["source"] == "akshare-bond-zh-cov", d["source"])

calls_after_first = len(fake.calls)
d_zero = prov.get_bond_underlying("127118")
check("两半样本·前导零：字符串 001380 原样保住", d_zero["stockCode"] == "001380", str(d_zero))
d_float = prov.get_bond_underlying("113009")
check("两半样本·float 升位：600519.0 剥掉 .0 仍是 6 位", d_float["stockCode"] == "600519", str(d_float))
check(
    "短码不冒充真代码：1380.0 归一后不足 6 位 ⇒ 读不出（摘掉 \\d{6} 那枚闸这一条就翻绿成假答案）",
    "读不出" in (grab(lambda: prov.get_bond_underlying("118077")) or ""),
    grab(lambda: prov.get_bond_underlying("118077")),
)
check(
    "TTL 24 小时生效：同进程换代码不重拉全表（这一枚是唯一省额度的闸）",
    len(fake.calls) == calls_after_first,
    f"calls={fake.calls}",
)

# ---------- 两种"答不出"要分开说 ----------

err_missing = grab(lambda: prov.get_bond_underlying("999999"))
check(
    "不在册的那一枚说的是『不在册』，并带出映射共多少只",
    err_missing is not None and "not in convertible map" in err_missing and "映射共 4 只" in err_missing,
    str(err_missing),
)
check("不在册 ≠ 在册但缺列（两句话不能混）", err_missing is not None and "读不出" not in err_missing, str(err_missing))

fake_blank = install(FakeAk(BLANK))
prov_blank = fresh_provider()
err_blank = grab(lambda: prov_blank.get_bond_underlying("110002"))
check(
    "在册但那一列空 ⇒ 答『读不出』，且不许读成『这只转债没有正股』",
    err_blank is not None and "读不出" in err_blank and "110002" in err_blank,
    str(err_blank),
)
err_blank2 = grab(lambda: prov_blank.get_bond_underlying("113009"))
check("NaN 那一行同样答不出（空与 NaN 两种写法共用一个口径）", err_blank2 is not None and "读不出" in err_blank2, str(err_blank2))
check("整表都读不出时也只拉一次（24h TTL 对这张空表一样生效）", len(fake_blank.calls) == 1, f"calls={fake_blank.calls}")

# ---------- 失败路径 ----------

fake_fail = install(FakeAk(COV, fail=True))
prov_fail = fresh_provider()
err_fail = grab(lambda: prov_fail.get_bond_underlying("110002"))
check("上游失败 ⇒ ProviderError 且原因在字面里", err_fail is not None and "em blocked" in err_fail, str(err_fail))
grab(lambda: prov_fail.get_bond_underlying("110002"))
check(
    "失败不写缓存：下一跳还会真重试（不把空表供 24 小时＝静默缺货一整天）",
    len(fake_fail.calls) == 2,
    f"calls={fake_fail.calls}",
)

# ---------- 路由形状（R10：200＋degraded＋note，不 404、不 500） ----------


class StubProvider:
    def __init__(self, payload=None, err=None):
        self._payload, self._err = payload, err

    def get_bond_underlying(self, code: str) -> dict:
        if self._err is not None:
            raise ProviderError(self._err)
        return {**self._payload, "code": code}


m._primary = lambda type_: StubProvider(err="bond code not in convertible map: 999999（映射共 4 只）")  # type: ignore[assignment]
r_bad = m.bond_underlying("999999")
check(
    "路由降级支＝200 形态：degraded/note 原文/code 回显，且 stockCode 显式为 None",
    r_bad["degraded"] is True
    and "not in convertible map" in r_bad["note"]
    and r_bad["code"] == "999999"
    and r_bad["stockCode"] is None,
    str(r_bad),
)

m._primary = lambda type_: StubProvider(payload={  # type: ignore[assignment]
    "bondName": "东山转债",
    "stockCode": "300001",
    "stockName": "特锐德",
    "mapSize": 1060,
    "source": "akshare-bond-zh-cov",
})
r_ok = m.bond_underlying("110002")
check(
    "路由成功支＝degraded False＋note None＋mapSize 原样带出",
    r_ok["degraded"] is False and r_ok["note"] is None and r_ok["mapSize"] == 1060,
    str(r_ok),
)
check(
    "两半样本·路由：答得出时不许出现 note 文本",
    "not in convertible map" not in str(r_ok),
    str(r_ok),
)

check(
    "零出网的身份证：本文件的 `akshare` 全程是替身（真模块不可能被这些路径调到）",
    type(sys.modules["akshare"]).__name__ == "FakeAk",
    str(type(sys.modules["akshare"])),
)

failed = [r for r in results if not r[1]]
print(f"\n== 转债→正股映射离线单测：{len(results) - len(failed)}/{len(results)} 通过 ==")
if failed:
    for name, _, detail in failed:
        print(f"  - {name} {detail}")
    sys.exit(1)
