"""CR10-7 离线单测：ds→web 的两条写腿必须自己带上 `x-write-token`。

背景（2026-11-02 现查）：P4 落了 web 侧的 `lib/guard.ts`（`WRITE_TOKEN` 一配就校验
`POST /api/sync` 与 `POST /api/market/refresh?type=all`），但发送侧当时没动——本文件
那两处 `requests.post` 都是裸调用。于是"配 env"这个动作本身的后果是：当晚 02:00 两条腿
全 401，而 `run_now`（`:581`）在认领那一刻就把当日 marker 落了（CR9-94），读点只有启动
补跑一处 ⇒ **这一天不会再自动补跑**。这就是 CR9-51 开 `INGEST_TOKEN` 时踩过的同族契约：
**守卫开启时调用方必须同批改**，否则开关一开就是把生产腿打掉。

判据形状（成对＋牙齿，C34）：
  ① 配值 ⇒ **两条腿**各带一次同一枚头（只改一处＝半落地，本断言按 URL 分档各断一次）；
  ② 🔁 未配 ⇒ 两条腿都没有这枚头（与 `guard.ts` 的 `?? ""` 放行同形＝本机默认态零行为变）；
  ③ 空串 ⇒ 与未配同形（`WRITE_TOKEN=` 不是"用空串去校验"）；
  ④ 值不落进状态位与落盘文件（泄漏面）；
  ⑤ 牙齿：只读的那次 `GET /api/health` 进度回读**不带头**（暴露面就是两条腿，不多一处）。

运行方式（无需任何服务在跑，零出网）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr10_7_write_token_header.py
"""

import json
import os
import sys
import tempfile

# CR9-94 同族纪律：先于 app 的任何 import 把 marker 指进临时目录。本套件直调 `_execute`
# （它经 `_mark_outcome` 落 sync-state.json），不指走就会把假轮的日期写进真文件 ⇒
# 当天之后任何一次合法补跑被静默挡掉。
os.environ["SYNC_STATE_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="cr107-syncstate-"), "sync-state.json"
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402

import app.sync_scheduler as ss  # noqa: E402

results: list[tuple[str, bool, str]] = []

TEST_TOKEN = "unit-test-token-abc123"  # 测试常量，不是任何一侧的真凭据


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


class _Resp:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeWeb:
    """按 URL 分派的假 web，把每次调用的 headers 记下来（headers 才是本套件的判据对象）。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url, timeout=None, headers=None, **kw):
        self.calls.append({"url": url, "timeout": timeout, "headers": dict(headers or {})})
        if "market/refresh" in url:
            return _Resp({"tookMs": 10, "results": []})
        return _Resp({"ok": True, "tookMs": 1, "results": []})

    def get(self, url, timeout=None, **kw):
        # 进度回读走 GET：给它一份非 200，逼出失败路径也不影响本套件的判据
        self.calls.append({"url": url, "timeout": timeout, "headers": None, "method": "GET"})
        return _Resp({"status": "ok", "db": "ok"}, status=503)


def _run_two_legs(token: str | None) -> list[dict]:
    """配着 `token` 跑一整轮（同步腿＋链式刷新腿），返回假 web 记下的调用序列。"""
    fake = _FakeWeb()
    orig_post, orig_get = requests.post, requests.get
    saved_state = dict(ss._state)
    saved_token = os.environ.get("WRITE_TOKEN")
    if token is None:
        os.environ.pop("WRITE_TOKEN", None)
    else:
        os.environ["WRITE_TOKEN"] = token
    requests.post, requests.get = fake.post, fake.get  # type: ignore[assignment]
    try:
        ss._state["running"] = True  # _execute 假定调用方已认领
        ss._execute("unit-test")
        return fake.calls
    finally:
        requests.post, requests.get = orig_post, orig_get  # type: ignore[assignment]
        ss._state.clear()
        ss._state.update(saved_state)
        if saved_token is None:
            os.environ.pop("WRITE_TOKEN", None)
        else:
            os.environ["WRITE_TOKEN"] = saved_token


def _leg(call: dict) -> str:
    return "refresh" if "market/refresh" in call["url"] else "sync"


def test_both_legs_carry_the_token() -> None:
    """① 配值 ⇒ 两条腿各带一次同一枚头（半落地＝只改一处，这里按 URL 分档各断一次）。"""
    calls = _run_two_legs(TEST_TOKEN)
    legs = {_leg(c): c for c in calls}
    check("CR10-7①：一轮里两条腿都发了（sync＋refresh，缺任何一条这格就空）",
          set(legs) == {"sync", "refresh"}, str(list(legs)))
    for name in ("sync", "refresh"):
        c = legs.get(name) or {}
        check(f"CR10-7①：{name} 腿带 x-write-token 且等于 env 值",
              (c.get("headers") or {}).get("x-write-token") == TEST_TOKEN,
              str(c.get("headers")))
    check("CR10-7①：头名与 web 侧 `guard.ts` 读的那枚一致（不是 Authorization）",
          all("x-write-token" in (c.get("headers") or {}) for c in calls), str(calls)[:200])


def test_unset_sends_no_header() -> None:
    """② 🔁 反向：未配 ⇒ 两条腿都不带头（本机默认态＝行为一字不变）。"""
    calls = _run_two_legs(None)
    check("CR10-7②🔁：未配 WRITE_TOKEN ⇒ 两条腿的 headers 里都没有这枚键",
          all("x-write-token" not in (c.get("headers") or {}) for c in calls),
          str([c.get("headers") for c in calls])[:200])
    check("CR10-7②：且不是拿空串去冒充带头（headers 就是空 dict）",
          all((c.get("headers") or {}) == {} for c in calls),
          str([c.get("headers") for c in calls])[:200])


def test_empty_value_is_same_as_unset() -> None:
    """③ 空串＝未配：`WRITE_TOKEN=` 不得发出 `x-write-token: ""`（web 那侧 `?? ""` 是放行）。"""
    calls = _run_two_legs("")
    check("CR10-7③：空串与未配同形 ⇒ 不发出这枚头",
          all("x-write-token" not in (c.get("headers") or {}) for c in calls),
          str([c.get("headers") for c in calls])[:200])


def test_token_does_not_leak_into_state() -> None:
    """④ 值只进请求头：状态位与落盘的 sync-state.json 里都不许出现它。"""
    _run_two_legs(TEST_TOKEN)
    saved_state = dict(ss._state)
    try:
        ss._state["running"] = True
        status_json = json.dumps(ss.status(), ensure_ascii=False)
    finally:
        ss._state.clear()
        ss._state.update(saved_state)
    check("CR10-7④：/sync/status 的载荷里没有这枚值（curl 读得到状态、读不到凭据）",
          TEST_TOKEN not in status_json, status_json[:200])
    try:
        with open(os.environ["SYNC_STATE_FILE"], encoding="utf-8") as f:
            on_disk = f.read()
    except OSError:
        on_disk = ""
    check("CR10-7④：落盘的 sync-state.json 里也没有（假轮的 marker 也一起被这条看着）",
          TEST_TOKEN not in on_disk, on_disk[:200])


def test_read_only_progress_get_carries_no_token() -> None:
    """⑤ 牙齿：暴露面只有两条写腿——那次只读 GET 不带头（观测不许多一处凭据面）。"""
    fake = _FakeWeb()
    orig_post, orig_get = requests.post, requests.get
    saved_token = os.environ.get("WRITE_TOKEN")
    os.environ["WRITE_TOKEN"] = TEST_TOKEN
    requests.post, requests.get = fake.post, fake.get  # type: ignore[assignment]
    try:
        ss._refresh_progress()  # #33 甲那条：刷新腿失败时去问一次 web 的进度状态位
    finally:
        requests.post, requests.get = orig_post, orig_get  # type: ignore[assignment]
        if saved_token is None:
            os.environ.pop("WRITE_TOKEN", None)
        else:
            os.environ["WRITE_TOKEN"] = saved_token
    gets = [c for c in fake.calls if c.get("method") == "GET"]
    check("CR10-7⑤🔁：GET /api/health 一次且不带头（它对着的是只读端点）",
          len(gets) == 1 and not gets[0]["headers"], str(gets)[:200])


def main() -> int:
    test_both_legs_carry_the_token()
    test_unset_sends_no_header()
    test_empty_value_is_same_as_unset()
    test_token_does_not_leak_into_state()
    test_read_only_progress_get_carries_no_token()
    passed = sum(1 for _n, ok, _d in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"[FAIL] {name}  <- {detail}")
    print(f"===== {passed}/{len(results)} 通过 =====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
