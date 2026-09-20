"""CR6-P2-1 离线单测：Python 侧 LRU 容量上限与淘汰语义。

运行方式（无需服务在跑）：
    .venv/Scripts/python tests/test_cr6_lru.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.lru import Lru, env_capacity

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def test_capacity_and_eviction() -> None:
    lru: Lru[str, int] = Lru(3)
    for k in ("a", "b", "c"):
        lru[k] = 1
    check("容量上限：未超上限时 size 正确", len(lru) == 3, str(len(lru)))
    lru["d"] = 1
    check("容量上限：超上限后 size 不超上限", len(lru) == 3, str(len(lru)))
    check("容量上限：淘汰最旧项（a 被淘汰）", "a" not in lru, str(list(lru.keys())))


def test_access_promotes() -> None:
    lru: Lru[str, int] = Lru(2)
    lru["a"] = 1
    lru["b"] = 2
    _ = lru.get("a")  # 访问 a → 提升为最近使用
    lru["c"] = 3  # 应淘汰 b（而非 a）
    check("访问提升：get 后 a 保留", "a" in lru, str(list(lru.keys())))
    check("访问提升：最旧的 b 被淘汰", "b" not in lru, str(list(lru.keys())))


def test_get_default_and_none_value() -> None:
    lru: Lru[str, object] = Lru(2)
    check("get 缺失返回 default", lru.get("x", "d") == "d")
    lru["n"] = None  # 存储值本身为 None
    check("get 区分“存了 None”与“缺失”", lru.get("n", "d") is None)


def test_delete_clear_and_env() -> None:
    lru: Lru[str, int] = Lru(2)
    lru["a"] = 1
    lru.delete("a")
    check("delete 生效", "a" not in lru)
    lru["b"] = 1
    lru.clear()
    check("clear 生效", len(lru) == 0)
    check("env_capacity：缺省回落", env_capacity("CR6_NOPE_ENV", 7) == 7)
    os.environ["CR6_TEST_CAP"] = "12"
    check("env_capacity：读 env", env_capacity("CR6_TEST_CAP", 7) == 12)
    os.environ["CR6_TEST_CAP"] = "bad"
    check("env_capacity：非法值回落", env_capacity("CR6_TEST_CAP", 7) == 7)
    os.environ["CR6_TEST_CAP"] = "0"
    check("env_capacity：非正数回落", env_capacity("CR6_TEST_CAP", 7) == 7)
    del os.environ["CR6_TEST_CAP"]


def test_provider_caches_bounded() -> None:
    """akshare/sina 的缓存实例必须是 Lru 且有上限（防止回退到无界 dict）。"""
    from app.providers.akshare_provider import AkshareProvider
    from app.providers.sina_provider import SinaProvider

    ak = AkshareProvider()
    check("akshare _news_cache 为 Lru", isinstance(ak._news_cache, Lru))
    check("akshare _fund_report_cache 为 Lru", isinstance(ak._fund_report_cache, Lru))
    check("akshare _news_cache 有上限", ak._news_cache.capacity == 512, str(ak._news_cache.capacity))

    sina = SinaProvider()
    check("sina _cache 为 Lru", isinstance(sina._cache, Lru))
    check("sina _cache 有上限", sina._cache.capacity == 256, str(sina._cache.capacity))


if __name__ == "__main__":
    test_capacity_and_eviction()
    test_access_promotes()
    test_get_default_and_none_value()
    test_delete_clear_and_env()
    test_provider_caches_bounded()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
