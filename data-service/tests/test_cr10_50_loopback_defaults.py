# -*- coding: utf-8 -*-
"""CR10-50 离线单测：开发态回调基址默认值必须用 127.0.0.1，不得退回 localhost。

为什么会有这把锁（2026-11-26 本机实测）：
- `dns.lookup('localhost', {all:true})` 返回 `[::1, 127.0.0.1]`，IPv6 在前；
- 开发态 web 只监听 `127.0.0.1:3000`（`::1` 无监听）；
- 因此 Python 的 `urllib`／`requests` 会先连 `::1` 被拒、再回落 IPv4：
  实测 `http://localhost:3000/api/health` 每次 2029–2048ms，
  而 `http://127.0.0.1:3000/api/health` 为 15–37ms。
- Node 的 `fetch` 走 Happy Eyeballs，实测不受害（15–23ms）；但两侧共用同一套
  "默认值"语义，一起钉住，免得日后被改回去。

边界（本测试不覆盖）：
- 不改 `main.py` 的 CORS `allow_origins`：那是浏览器 `Origin` 头语义，真实值就是
  `http://localhost:3000`；改成 127.0.0.1 会拒掉同源请求。
- 不改 compose 的显式服务名（`http://web:3000`、`http://data-service:8000`）：
  容器内走 compose DNS 的 IPv4 名，本来就不受影响。

运行（零出网、零 SQLite）：
    PYTHONPATH=. .venv/Scripts/python tests/test_cr10_50_loopback_defaults.py
"""

import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"

# 允许出现 localhost 的例外，逐条写清理由（新增例外必须同时写理由）。
ALLOWED_LOCALHOST = {
    # CORS allow_origins 是浏览器 Origin 头：真实值就是 localhost:3000。
    "main.py",
}

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ok   {name}")
    else:
        _FAIL += 1
        print(f"  FAIL {name}{('  ' + detail) if detail else ''}")


def _py_files() -> list[pathlib.Path]:
    return sorted(p for p in APP_DIR.rglob("*.py") if p.is_file())


def test_no_localhost_callback_defaults() -> None:
    print("[1] app/ 下不得把 http://localhost 当回调默认值（CORS 例外另测）")
    offenders = []
    for path in _py_files():
        rel = path.relative_to(APP_DIR).as_posix()
        if rel in ALLOWED_LOCALHOST:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "http://localhost" in line:
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    check("无 localhost 回调默认值", offenders == [], "\n".join(offenders))


def test_callback_defaults_are_loopback_ipv4() -> None:
    print("[2] 取默认值的点必须显式 127.0.0.1")
    expected = {
        "sync_scheduler.py": "http://127.0.0.1:3000",
        "us_list_job.py": "http://127.0.0.1:3000",
        "hotspot/pipeline.py": "http://127.0.0.1:3000",
        "hotspot/scheduler.py": "http://127.0.0.1:3000",
        "research/adapter.py": "http://127.0.0.1:3000",
        "research/tasks.py": "http://127.0.0.1:3000",
    }
    for rel, want in expected.items():
        text = (APP_DIR / rel).read_text(encoding="utf-8")
        check(f"{rel} 含 {want}", want in text)


def test_mcp_server_falls_back_to_loopback_ipv4() -> None:
    print("[3] MCP 的 WEB_API_BASE 回退链末位也不得是 localhost")
    text = (APP_DIR / "mcp_server.py").read_text(encoding="utf-8")
    check('回退末位 127.0.0.1', 'or "http://127.0.0.1:3000"' in text)
    check("无 localhost", "http://localhost:3000" not in text)


def test_cors_allow_origins_keeps_localhost() -> None:
    print("[4] CORS 例外是刻意的：Origin 头就是 localhost:3000")
    text = (APP_DIR / "main.py").read_text(encoding="utf-8")
    check(
        "allow_origins 仍为 localhost:3000",
        'allow_origins=["http://localhost:3000"]' in text,
        "改成 127.0.0.1 会拒掉浏览器的真实同源请求",
    )


def test_sync_scheduler_default_is_actually_used() -> None:
    print("[5] 行为锁：_web_base() 在未设 WEB_BASE_URL 时返回 127.0.0.1")

    saved = os.environ.pop("WEB_BASE_URL", None)
    try:
        from app import sync_scheduler  # noqa: PLC0415

        check(
            "sync_scheduler._web_base()",
            sync_scheduler._web_base() == "http://127.0.0.1:3000",
            sync_scheduler._web_base(),
        )
        os.environ["WEB_BASE_URL"] = "http://web:3000"
        check(
            "显式 WEB_BASE_URL 优先",
            sync_scheduler._web_base() == "http://web:3000",
            sync_scheduler._web_base(),
        )
    finally:
        os.environ.pop("WEB_BASE_URL", None)
        if saved is not None:
            os.environ["WEB_BASE_URL"] = saved


def test_docstring_explains_why() -> None:
    print("[6] 改动处留有“为什么”，避免后人当风格问题改回去")
    for rel in ("sync_scheduler.py", "us_list_job.py"):
        text = (APP_DIR / rel).read_text(encoding="utf-8")
        check(f"{rel} 解释 ::1 回落", "::1" in text or "IPv4" in text)


def main() -> int:
    test_no_localhost_callback_defaults()
    test_callback_defaults_are_loopback_ipv4()
    test_mcp_server_falls_back_to_loopback_ipv4()
    test_cors_allow_origins_keeps_localhost()
    test_sync_scheduler_default_is_actually_used()
    test_docstring_explains_why()
    total = _PASS + _FAIL
    # 门禁 scripts/gate.mjs 只认 `== ... N/M 通过 ==` 这一形（见 SUITE_SUMMARY）。
    print(f"\n== 结果：{_PASS}/{total} 通过 ==")
    if _FAIL:
        print(f"失败 {_FAIL} 项")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
