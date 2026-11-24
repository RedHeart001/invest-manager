"""CR10-44 离线回归：同族熔断连坐与 fund 无备源腿（2026-11-23）。

背景（11-23 自然轮实测）：stock 主源在 `02:00:03` 传输层失败，eastmoney 族熔断打开；
随后 fund 在 `tookMs=4` 内被本地拒绝（一发真实请求都没发），bond 的新浪备源又因
328 < 1,068×70% 被缩水闸拒绝。fund 是唯一没有等价备源的列表腿，因此最脆弱。

本套件只证明机制，不改闸门、不出网：
- L0：两次传输失败 ⇒ eastmoney 冷却 ⇒ 下一条腿本地被拒；冷却到期恢复；成功回报清零。
- L0：`akshare-obs` 族不受 eastmoney 冷却影响，且生产参数不设熔断。
- L0：`_ak_request` 只走 `akshare-obs`，不碰 eastmoney。
- L2-A：`_list_funds` 走 `_ak_request`，不再走 `_em_ak_request`；失败仍抛 ProviderError。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr10_44_breaker_cascade.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# 离线单测不得把仓库 runtime 当测试产物落点（与 limiter.state_path 的约定一致）。
_TMPDIR = tempfile.mkdtemp(prefix="cr10-44-limiter-")
os.environ["LIMITER_STATE_FILE"] = os.path.join(_TMPDIR, "limiter-state.json")

import app.providers.akshare_provider as ap  # noqa: E402
import app.utils.limiter as limiter  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402
from app.utils.limiter import FamilyLimiter  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


class _FakeClock:
    """只替 `limiter.time`：让 180s 冷却在单测里可推进，不真睡。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += float(seconds)

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class _ClockPatch:
    def __enter__(self) -> _FakeClock:
        self.clock = _FakeClock()
        self.orig = limiter.time
        limiter.time = self.clock  # type: ignore[assignment]
        return self.clock

    def __exit__(self, *exc) -> None:
        limiter.time = self.orig  # type: ignore[assignment]


class _LimiterSpy:
    """只记录调用，不排队、不落盘。"""

    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.observe_calls: list[str] = []
        self.acquire_calls: list[float] = []
        self.successes = 0
        self.failures = 0

    def observe(self, name: str) -> None:
        self.observe_calls.append(name)

    def acquire(self, timeout: float = 20.0) -> bool:
        self.acquire_calls.append(timeout)
        return self.allow

    def on_success(self) -> None:
        self.successes += 1

    def on_failure(self) -> None:
        self.failures += 1


class _FakeFundDF:
    """`_list_funds` 只用到 `.iterrows()`；空名行用于钉“跳过”语义。"""

    def iterrows(self):
        return iter(
            [
                (
                    0,
                    {
                        "基金代码": "000001",
                        "基金简称": "测试基金",
                        "拼音缩写": "CSJJ",
                        "基金类型": "混合型",
                    },
                ),
                (
                    1,
                    {
                        "基金代码": "000002",
                        "基金简称": "",
                        "拼音缩写": "",
                        "基金类型": "股票型",
                    },
                ),
            ]
        )


def test_eastmoney_breaker_cascades() -> None:
    with _ClockPatch() as clock:
        lim = FamilyLimiter(
            "unit-eastmoney",
            min_interval=0.0,
            burst=1000,
            rate_per_min=100000,
            failure_threshold=2,
            cooldown_base=180.0,
            cooldown_max=900.0,
        )
        orig = ap.EM_LIMITER
        ap.EM_LIMITER = lim  # type: ignore[assignment]
        try:
            def _boom():
                raise RuntimeError("transport boom")

            for _ in range(2):
                try:
                    ap._em_request(_boom)
                except RuntimeError:
                    pass

            check("L0①：两次传输失败后 eastmoney 族进入冷却", lim.in_cooldown(), str(lim.state()))

            called = {"n": 0}

            def _next_leg():
                called["n"] += 1
                return {"ok": True}

            msg = ""
            try:
                ap._em_request(_next_leg)
            except ProviderError as e:
                msg = str(e)

            check(
                "L0②：冷却期内下一条腿在本地被拒（文案不变）",
                msg == "eastmoney cooling down (rate-limited)",
                msg,
            )
            check("L0③：被拒时一发真实请求都没发（fund 4ms 形状）", called["n"] == 0, str(called))
            check("L0④：拒绝计入 denied", lim.state()["denied"] >= 1, str(lim.state()))

            clock.advance(181.0)
            check("L0⑤：冷却到期后同一条腿恢复取额度", ap._em_request(_next_leg) == {"ok": True})
            check(
                "L0⑥：成功回报清零连续失败与冷却",
                not lim.in_cooldown() and lim.state()["consecutiveFailures"] == 0,
                str(lim.state()),
            )
        finally:
            ap.EM_LIMITER = orig  # type: ignore[assignment]


def test_akshare_obs_survives_eastmoney_cooldown() -> None:
    with _ClockPatch():
        em = FamilyLimiter(
            "unit-eastmoney",
            min_interval=0.0,
            burst=1000,
            rate_per_min=100000,
            failure_threshold=2,
            cooldown_base=180.0,
        )
        obs = FamilyLimiter("unit-akshare-obs", **limiter.PROFILES["akshare-obs"])

        for _ in range(2):
            em.on_failure()

        check(
            "L0⑦：eastmoney 冷却时 akshare-obs 仍可取额度",
            em.in_cooldown() and obs.acquire(timeout=0),
            f"{em.state()} / {obs.state()}",
        )

        for _ in range(10):
            obs.on_failure()

        check(
            "L0⑧：akshare-obs 连续失败不进入冷却（该族不设熔断）",
            not obs.in_cooldown(),
            str(obs.state()),
        )
        check(
            "L0⑨：生产参数仍不设熔断",
            limiter.PROFILES["akshare-obs"]["failure_threshold"] >= 10**9
            and limiter.PROFILES["akshare-obs"]["cooldown_base"] == 0.0,
            str(limiter.PROFILES["akshare-obs"]),
        )


def test_ak_request_uses_obs_family() -> None:
    em = _LimiterSpy()
    obs = _LimiterSpy()
    orig_em, orig_obs = ap.EM_LIMITER, ap.AK_OBS_LIMITER
    ap.EM_LIMITER = em  # type: ignore[assignment]
    ap.AK_OBS_LIMITER = obs  # type: ignore[assignment]
    try:
        out = ap._ak_request(lambda: "ok", 1.0, "ak.fund_name_em")
        check("L0⑩：_ak_request 原样返回", out == "ok", str(out))
        check(
            "L0⑪：_ak_request 先 observe 再 acquire（akshare-obs）",
            obs.observe_calls == ["ak.fund_name_em"]
            and obs.acquire_calls == [ap.AK_ACQUIRE_TIMEOUT_S],
            f"{obs.observe_calls} / {obs.acquire_calls}",
        )
        check(
            "L0⑫：_ak_request 不碰 eastmoney 族",
            em.observe_calls == [] and em.acquire_calls == [],
            f"{em.observe_calls} / {em.acquire_calls}",
        )
        check(
            "L0⑬：成功回报走 akshare-obs",
            obs.successes == 1 and em.successes == 0,
            f"{obs.successes} / {em.successes}",
        )
    finally:
        ap.EM_LIMITER, ap.AK_OBS_LIMITER = orig_em, orig_obs  # type: ignore[assignment]


def test_list_funds_uses_ak_request() -> None:
    ak_calls: list[tuple[float, str]] = []
    em_calls: list[tuple[float, str]] = []

    def _fake_ak(fn, seconds: float = 30.0, name: str = "akshare"):
        ak_calls.append((seconds, name))
        return _FakeFundDF()

    def _fake_em(fn, seconds: float = 30.0, name: str = "akshare"):
        em_calls.append((seconds, name))
        return _FakeFundDF()

    orig_ak, orig_em = ap._ak_request, ap._em_ak_request
    ap._ak_request = _fake_ak  # type: ignore[assignment]
    ap._em_ak_request = _fake_em  # type: ignore[assignment]
    try:
        products = ap.AkshareProvider()._list_funds()
    finally:
        ap._ak_request, ap._em_ak_request = orig_ak, orig_em  # type: ignore[assignment]

    check(
        "L2-A①：fund 名单走 _ak_request",
        ak_calls == [(90.0, "ak.fund_name_em")],
        str(ak_calls),
    )
    check("L2-A②：fund 名单不再走 _em_ak_request", em_calls == [], str(em_calls))
    check(
        "L2-A③：行映射保持（空名跳过）",
        len(products) == 1
        and products[0]["type"] == "fund"
        and products[0]["code"] == "000001"
        and products[0]["pinyinInitials"] == "CSJJ",
        str(products),
    )


def test_list_funds_failure_is_provider_error() -> None:
    def _fail(*args, **kwargs):
        raise ProviderError("ak.fund_name_em failed: boom")

    orig = ap._ak_request
    ap._ak_request = _fail  # type: ignore[assignment]
    msg = ""
    try:
        try:
            ap.AkshareProvider()._list_funds()
        except ProviderError as e:
            msg = str(e)
    finally:
        ap._ak_request = orig  # type: ignore[assignment]

    check(
        "L2-A④：失败仍抛 ProviderError（不吞成空列表）",
        msg.startswith("akshare fund list failed:"),
        msg,
    )


def main() -> int:
    test_eastmoney_breaker_cascades()
    test_akshare_obs_survives_eastmoney_cooldown()
    test_ak_request_uses_obs_family()
    test_list_funds_uses_ak_request()
    test_list_funds_failure_is_provider_error()
    passed = sum(1 for _n, ok, _d in results if ok)
    fails = [x for x in results if not x[1]]
    for name, _ok, detail in fails:
        print(f"[FAIL] {name}  <- {detail[:160]}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    shutil.rmtree(_TMPDIR, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
