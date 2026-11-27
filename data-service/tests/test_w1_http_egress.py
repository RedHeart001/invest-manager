"""W1 离线单测（2026-11-27）：按源族的出网策略必须「写死在代码里」，不依赖 NO_PROXY 写全。

背景（11-27 探针实测，两次都是同一枚代理）：
- `push2.eastmoney.com` 直连 200／3518ms，套代理直接 `ProxyError` ⇒ 国内源**必须**直连；
- CoinGecko／Tavily 两种形态都通，代理没有明确收益、也没有明确损失；
- 容器里 `NO_PROXY` 由 compose 传入（`.env` 只有 `127.0.0.1,localhost,::1`），
  而 `main.py` 的 `NO_PROXY=*` 是 `setdefault` ⇒ **不能**拿它当唯一防线。

所以本套件钉的是三件事：

  ① `direct_proxies()` 必须返回 `{"http": None, "https": None}` 而**不是**空字典——
     这是本仓唯一一处「看着能简化、实际会静默失效」的写法。requests 的
     `merge_environment_settings` 对 env 代理用的是 `proxies.setdefault(k, v)`，
     只有键**已存在**才能压住；空字典会被 env 原样填回来。这里用**真 env ＋ 真
     merge_environment_settings** 反锁（不去 mock requests 的内部函数）。
  ② 海外源未配代理时 `overseas_proxies()` 返回 `None`（不是空字典、不是虚构地址），
     行为与改造前一致。
  ③ 结构锁：`app/` 下每一个 `requests.<method>(...)` 调用点都必须显式带 `proxies=`，
     豁免项逐条写理由；国内源族那几处必须真的是 `direct_proxies()`。

运行方式（无需任何服务在跑；零出网——所有断言都在发请求之前）：
    PYTHONPATH=. .venv/Scripts/python tests/test_w1_http_egress.py
"""

import ast
import os
import pathlib
import sys
import tempfile

# 本机 `tempfile.gettempdir()` 会解析到仓库根（%TEMP% 对子进程不可写），
# 那样每次 `mkdtemp()` 都往仓库里丢一个目录。这里显式指到 `.tmp/`（已 gitignore）。
_REPO = pathlib.Path(__file__).resolve().parents[2]
_TMP = _REPO / ".tmp"
_TMP.mkdir(exist_ok=True)
tempfile.tempdir = str(_TMP)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402

from app.utils import http as http_util  # noqa: E402

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

_PASS = 0
_FAIL = 0


def check(name: str, cond, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ok   {name}")
    else:
        _FAIL += 1
        print(f"  FAIL {name}{('  — ' + str(detail)) if detail else ''}")


# ---------- env 开关（本套件要动真 env，用上下文管理器保证还原） ----------


class _Env:
    def __init__(self, **values):
        self.values = values
        self.saved: dict = {}

    def __enter__(self):
        for k, v in self.values.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        http_util.reset_overseas_session()
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        http_util.reset_overseas_session()
        return False


PROXY = "http://127.0.0.1:7897"


# ---------- ① 空字典压不住 env 代理（真 env ＋ 真 merge_environment_settings） ----------


def test_empty_dict_does_not_suppress_env_proxy() -> None:
    print("[1] 空字典压不住 env 代理 —— 这就是 direct_proxies() 必须给键值为 None 的理由")
    url = "https://api.coingecko.com/api/v3/ping"
    with _Env(HTTPS_PROXY=PROXY, HTTP_PROXY=PROXY, NO_PROXY=None, no_proxy=None):
        s = requests.Session()
        refilled = s.merge_environment_settings(url, {}, None, True, None)["proxies"]
        check(
            "🔁 反锁：传空字典 ⇒ env 代理被 setdefault 原样填回来（化简成 {} 就是静默失效）",
            bool(refilled) and "7897" in str(refilled),
            dict(refilled),
        )
        merged = s.merge_environment_settings(url, http_util.direct_proxies(), None, True, None)["proxies"]
        check("真 direct_proxies() ⇒ 合并结果为空 ⇒ 这次请求真的直连", dict(merged) == {}, dict(merged))
        s.close()


def test_direct_proxies_shape() -> None:
    print("[2] direct_proxies() 的形状与「新鲜副本」契约")
    got = http_util.direct_proxies()
    check("键是两个且值都是 None（不是空字典、不是空串）", got == {"http": None, "https": None}, got)
    got["http"] = "http://tampered:1"
    check(
        "🔁 每次返回新副本（调用方改了不会污染下一次调用）",
        http_util.direct_proxies() == {"http": None, "https": None},
        http_util.direct_proxies(),
    )


# ---------- ② 海外源：未配 ⇒ None（行为与改造前一致） ----------


def test_overseas_proxies_when_unconfigured() -> None:
    print("[3] 海外源未配置代理 ⇒ None（不虚构地址、不返回空字典）")
    with _Env(HTTPS_PROXY=None, HTTP_PROXY=None, https_proxy=None, http_proxy=None):
        check("未配置 ⇒ None", http_util.overseas_proxies() is None, http_util.overseas_proxies())


def test_overseas_proxies_reads_both_cases() -> None:
    print("[4] 海外代理读取：HTTPS 优先；小写别名按平台的 env 语义处理")
    # ⚠️ Windows 的 `os.environ` 是**大小写不敏感**的（键会被规范化成大写）⇒ 同一段代码里
    # 既设 `HTTPS_PROXY` 又"清掉" `https_proxy`，后者会把前者一起删掉。所以这里刻意分成
    # 两段互不重叠的 env，而不是写一句在 Windows 上恒假的断言。
    with _Env(HTTPS_PROXY="http://h:1", HTTP_PROXY="http://p:2"):
        check(
            "HTTPS_PROXY 优先于 HTTP_PROXY",
            http_util.overseas_proxies() == {"http": "http://h:1", "https": "http://h:1"},
            http_util.overseas_proxies(),
        )
    with _Env(HTTPS_PROXY=None, HTTP_PROXY=None):
        if os.name == "nt":
            # 这一档在本机测不了"只有小写键"的形态（两侧是同一个键）。申报清楚而不是跳过：
            # 真正的容器是 Linux，那条路径由下面的 POSIX 分支作证。
            os.environ["http_proxy"] = "http://low:3"
            check(
                "Windows：两种写法是同一个键（所以改造前那两处读小写的行为在本机不可分辨）",
                "HTTP_PROXY" in os.environ and "http_proxy" not in {k for k in os.environ if k.islower()}
                or os.environ.get("HTTP_PROXY") == "http://low:3",
                os.environ.get("HTTP_PROXY"),
            )
            check(
                "Windows：只设小写写法也仍然读得到（env 规范化替我们兜住了）",
                http_util.overseas_proxies() == {"http": "http://low:3", "https": "http://low:3"},
                http_util.overseas_proxies(),
            )
        else:
            os.environ["http_proxy"] = "http://low:3"
            check(
                "POSIX：只有小写 http_proxy 时也认（容器里就是这一形态）",
                http_util.overseas_proxies() == {"http": "http://low:3", "https": "http://low:3"},
                http_util.overseas_proxies(),
            )


# ---------- 会话构造：trust_env 与显式 proxies 两件都要设 ----------


def test_overseas_session_bypasses_no_proxy_star() -> None:
    print("[5] 海外会话：trust_env=False ⇒ 即便 NO_PROXY=* 也仍走显式代理")
    url = "https://api.tavily.com/search"
    with _Env(HTTPS_PROXY=PROXY, HTTP_PROXY=None, NO_PROXY="*", no_proxy="*"):
        s = http_util.overseas_session()
        check("trust_env 已关（这是绕开 NO_PROXY=* 的那一半）", s.trust_env is False, s.trust_env)
        merged = s.merge_environment_settings(url, {}, None, True, None)["proxies"]
        check(
            "显式代理在 NO_PROXY=* 之下仍然生效（select_proxy 会因 * 绕过 env，只剩会话自带那份）",
            merged.get("https") == PROXY,
            dict(merged),
        )
        check("同一枚会话被复用（不是每次新建连接池）", http_util.overseas_session() is s)


def test_overseas_session_without_proxy_stays_direct() -> None:
    print("[6] 🔁 反向：未配代理时海外会话不设 proxies ⇒ 与改造前行为一致")
    with _Env(HTTPS_PROXY=None, HTTP_PROXY=None, https_proxy=None, http_proxy=None,
              NO_PROXY="*", no_proxy="*"):
        s = http_util.overseas_session()
        merged = s.merge_environment_settings("https://api.coingecko.com/x", {}, None, True, None)["proxies"]
        check("没配就不带代理（不虚构一个地址出来）", dict(merged) == {}, dict(merged))


def test_reset_overseas_session() -> None:
    print("[7] reset_overseas_session() 丢掉缓存会话（配置变更／测试用）")
    with _Env(HTTPS_PROXY=PROXY, HTTP_PROXY=None):
        first = http_util.overseas_session()
        http_util.reset_overseas_session()
        second = http_util.overseas_session()
        check("重置后是新对象", second is not first)
        check("新对象仍带同一个代理", second.proxies.get("https") == PROXY, dict(second.proxies))


def test_direct_session_follows_caller_module() -> None:
    print("[8b] 🔁 会话工厂必须跟着调用方模块里的那个 `requests` 走（否则离线套件的替身被绕过）")
    import types

    made: list = []

    class _FakeSession:
        def __init__(self):
            self.trust_env = True
            self.proxies: dict = {}
            made.append(self)

        def close(self):
            pass

    fake = types.SimpleNamespace(Session=_FakeSession)
    s = http_util.direct_session(fake)
    check("用调用方给的模块建会话（不是 `utils/http.py` 里那个真 requests）",
          isinstance(s, _FakeSession) and len(made) == 1, type(s).__name__)
    check("替身会话同样被钉成直连", s.trust_env is False and s.proxies == {"http": None, "https": None},
          (s.trust_env, s.proxies))

    # 反锁：三个真调用点都显式传了自己模块的 requests。少传一个，那条"零出网"的翻页用例
    # 就会真的打到新浪（test_cr9_59 首跑即如此：一路要到 923 页的预算才报错）。
    for rel, fn in (
        ("providers/akshare_provider.py", "collect_us_snapshot"),
        ("us_list_job.py", "_collect_once"),
    ):
        body = _body_of((APP_DIR / rel).read_text(encoding="utf-8"), fn)
        check(f"🔁 {rel}::{fn} 传了 `direct_session(requests)`", "direct_session(requests)" in body,
              body[:120].replace("\n", " "))
    for rel in ("providers/akshare_provider.py", "us_list_job.py"):
        text = (APP_DIR / rel).read_text(encoding="utf-8")
        check(f"🔁 {rel} 里没有裸 `direct_session()`（漏传模块即可绕过替身）",
              "direct_session()" not in text,
              [ln for ln in text.splitlines() if "direct_session()" in ln][:2])


def test_direct_session_is_fresh_and_pinned() -> None:
    print("[8] direct_session()：每次新对象（翻页「换一枚会话重试」那条恢复路径靠它）、且钉死直连")
    with _Env(HTTPS_PROXY=PROXY, HTTP_PROXY=PROXY, NO_PROXY="127.0.0.1,localhost,::1"):
        a = http_util.direct_session()
        b = http_util.direct_session()
        check("两次调用是两个对象", a is not b)
        check("trust_env=False", a.trust_env is False and b.trust_env is False)
        merged = a.merge_environment_settings(
            "https://push2.eastmoney.com/api/qt/stock/get", {}, None, True, None
        )["proxies"]
        check(
            "🔁 反锁：env 里有代理、NO_PROXY 又不含东财 ⇒ 合并结果仍为空（直连真的成立）",
            dict(merged) == {},
            dict(merged),
        )
        a.close()
        b.close()


# ---------- ③ 结构锁：每一个 requests 调用点都得自己声明 ----------


#: 豁免项（逐条写理由；新增豁免必须同时写理由，否则这把锁会被「顺手加一行」变成常绿）
EXEMPT = {
    ("hotspot/llm_client.py", "chat_json"): (
        "LLM 端点（api.deepseek.com）不属于 W1 的两个源族：走 env 语义（配了代理就代理、"
        "没配就直连）。11-27 16:30 自然轮已在当前配置下实测通过，改它会动 W5 已验收的路径。"
    ),
}


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "request"}


def _call_sites() -> list:
    """`app/` 下所有 `requests.<method>(...)` 调用点：`(相对路径, 外层函数名, 节点)`。"""
    out: list = []
    for p in sorted(APP_DIR.rglob("*.py")):
        rel = p.relative_to(APP_DIR).as_posix()
        tree = ast.parse(p.read_text(encoding="utf-8"))
        stack: list = []

        def _walk(node, stack=stack):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stack.append(node.name)
                for child in ast.iter_child_nodes(node):
                    _walk(child)
                stack.pop()
                return
            if isinstance(node, ast.Call):
                f = node.func
                # 只算**真发请求**的方法：`requests.Session()` 不是出网点。
                if (
                    isinstance(f, ast.Attribute)
                    and f.attr in HTTP_METHODS
                    and isinstance(f.value, ast.Name)
                    and f.value.id == "requests"
                ):
                    out.append((rel, stack[-1] if stack else "<module>", node))
            for child in ast.iter_child_nodes(node):
                _walk(child)

        _walk(tree)
    return out


def test_every_requests_call_declares_proxies() -> None:
    print("[9] 结构锁：app/ 下每个 requests.<method>( 都显式带 proxies=（豁免项逐条列理由）")
    sites = _call_sites()
    check("扫描确实找到了调用点（空集合＝这把锁恒绿）", len(sites) >= 15, len(sites))
    missing = []
    for rel, fn, node in sites:
        kws = {a.arg for a in node.keywords if a.arg}
        if "proxies" in kws:
            continue
        if (rel, fn) in EXEMPT:
            continue
        missing.append(f"{rel}:{node.lineno} ({fn})")
    check("没有漏声明的调用点", not missing, "; ".join(missing))
    unused = [k for k in EXEMPT if not any((r, f) == k for r, f, _ in sites)]
    check(
        "🔁 豁免表没有失效项（被豁免的调用点还在；删了要一起摘，否则表会越积越像常绿）",
        not unused,
        unused,
    )


def _body_of(text: str, fn: str) -> str:
    marker = f"def {fn}("
    idx = text.find(marker)
    if idx < 0:
        return ""
    tail = text[idx + len(marker):]
    end = len(tail)
    for nxt in ("\ndef ", "\nclass ", "\nasync def "):
        j = tail.find(nxt)
        if j != -1:
            end = min(end, j)
    return tail[:end]


def test_domestic_sources_are_pinned_direct() -> None:
    print("[10] 国内源族逐处钉死直连（东财／新浪／腾讯／容器内回调）")
    expected = [
        ("providers/akshare_provider.py", "_em_get"),
        ("providers/akshare_provider.py", "_fetch_kline_all"),
        ("providers/tencent_provider.py", "fetch_quote_fields"),
        ("providers/tencent_provider.py", "fetch_minute_payload"),
        ("providers/tencent_provider.py", "get_kline"),
        ("providers/hk_provider.py", "_fetch"),
        ("providers/hk_provider.py", "_sina_hk_page"),
        ("realtime.py", "_price_leg"),
        ("research/adapter.py", "collect_kline_with_phases"),
        ("research/tasks.py", "_emit_ingest"),
        ("hotspot/pipeline.py", "emit_ingest"),
        ("hotspot/scheduler.py", "_catch_up_decide"),
        ("sync_scheduler.py", "_refresh_progress"),
        ("sync_scheduler.py", "_refresh_leg"),
        ("sync_scheduler.py", "_execute_types"),
        ("us_list_job.py", "_post_publish"),
        ("us_list_job.py", "_post_refresh"),
    ]
    cache = {rel: (APP_DIR / rel).read_text(encoding="utf-8") for rel, _ in expected}
    for rel, fn in expected:
        body = _body_of(cache[rel], fn)
        check(f"{rel}::{fn} 存在且用 direct_proxies() 直连",
              "direct_proxies()" in body, body[:120].replace("\n", " "))


def _env_proxy_readers() -> list:
    """真去读 env 代理的模块（AST 判据：调用 `os.environ.get` / `environ[...]` 且实参是代理名）。

    为什么不用 `"HTTPS_PROXY" in text`：`crypto_provider.py` 的模块 docstring 里就有这两个
    词（解释 R12 策略），字符串匹配会把一段历史说明判成"自己又读了一份 env"。
    """
    names = {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"}
    out: list = []
    for p in sorted(APP_DIR.rglob("*.py")):
        rel = p.relative_to(APP_DIR).as_posix()
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            is_get = (
                isinstance(f, ast.Attribute)
                and f.attr == "get"
                and isinstance(f.value, ast.Attribute)
                and f.value.attr == "environ"
            )
            if is_get and node.args and isinstance(node.args[0], ast.Constant):
                if node.args[0].value in names:
                    out.append(f"{rel}:{node.lineno}")
            # `os.environ["HTTPS_PROXY"]`
            if (
                isinstance(f, ast.Attribute)
                and f.attr == "__getitem__"
                and isinstance(f.value, ast.Attribute)
                and f.value.attr == "environ"
            ):
                out.append(f"{rel}:{node.lineno}")
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.slice, ast.Constant)
                and node.slice.value in names
            ):
                out.append(f"{rel}:{node.lineno}")
    return out


def test_overseas_sources_use_overseas_path() -> None:
    print("[11] 海外源四处：显式代理 ＋ trust_env=False 会话（不是裸 requests）")
    cases = [
        ("providers/crypto_provider.py", "CoinGecko"),
        ("providers/hk_provider.py", "HKEX"),
        ("providers/openbb_provider.py", "yfinance/OpenBB"),
        ("hotspot/pipeline.py", "Tavily"),
    ]
    readers = _env_proxy_readers()
    allowed = {"utils/http.py"}
    stray = [r for r in readers if r.split(":")[0] not in allowed]
    check(
        "代理 env 只有 `utils/http.py` 一处读（其余模块全是薄别名／直接调用）",
        not stray,
        stray,
    )
    for rel, label in cases:
        text = (APP_DIR / rel).read_text(encoding="utf-8")
        check(f"{label}：overseas_proxies 进到请求里", "overseas_proxies" in text, rel)
        check(
            f"{label}：overseas_session 进到请求里（NO_PROXY=* 之下只剩它能让代理生效）",
            "overseas_session" in text,
            rel,
        )
        check(
            f"{label}：没有自己再读一份 env 代理",
            not [r for r in readers if r.startswith(rel + ":")],
            [r for r in readers if r.startswith(rel + ":")],
        )


def test_no_global_proxy_mutation() -> None:
    print("[12] 没有人在运行期改全局代理 env（那会变成「全局代理」，正是本次要防的形态）")
    proxy_writes = []
    no_proxy_writes = []
    for p in sorted(APP_DIR.rglob("*.py")):
        rel = p.relative_to(APP_DIR).as_posix()
        text = p.read_text(encoding="utf-8")
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
            forms = (
                f'environ["{name}"] =',
                f"environ['{name}'] =",
                f'setdefault("{name}"',
                f"setdefault('{name}'",
            )
            for form in forms:
                if form in text:
                    bucket = no_proxy_writes if name.upper() == "NO_PROXY" else proxy_writes
                    bucket.append(f"{rel} -> {form}")
    check("没有代码给 HTTP_PROXY／HTTPS_PROXY 赋值", not proxy_writes, proxy_writes)
    check(
        "NO_PROXY 的写点只有 main.py／mcp_server.py 的 setdefault（不覆盖 compose 传入值）",
        all(o.split(" -> ")[0] in ("main.py", "mcp_server.py") for o in no_proxy_writes),
        no_proxy_writes,
    )


def test_compose_still_passes_proxy_env() -> None:
    print("[13] compose 仍把三个代理变量透传给 data-service（代码直连 ＋ env 可配，两件都在）")
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    ds_block = compose.split("data-service:", 1)[-1]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        check(f"data-service 段里有 {key}", key in ds_block)


def main() -> int:
    test_empty_dict_does_not_suppress_env_proxy()
    test_direct_proxies_shape()
    test_overseas_proxies_when_unconfigured()
    test_overseas_proxies_reads_both_cases()
    test_overseas_session_bypasses_no_proxy_star()
    test_overseas_session_without_proxy_stays_direct()
    test_reset_overseas_session()
    test_direct_session_is_fresh_and_pinned()
    test_direct_session_follows_caller_module()
    test_every_requests_call_declares_proxies()
    test_domestic_sources_are_pinned_direct()
    test_overseas_sources_use_overseas_path()
    test_no_global_proxy_mutation()
    test_compose_still_passes_proxy_env()
    total = _PASS + _FAIL
    print(f"\n== 结果：{_PASS}/{total} 通过 ==")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
