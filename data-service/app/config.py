"""配置加载（PLAN 配置项）。

优先级：真实进程环境变量 > data-service/.env > ../web/.env（本地开发便利，
用户在 web/.env 里配置 key 时无需重复维护）。

键名别名：`TAVILY_API_KEY` 与 `SEARCH_API_KEY` 互为别名（两者任一存在即可），
统一导出为 SEARCH_API_KEY 供 pipeline 使用；值支持带引号（自动剥离）。
"""

from __future__ import annotations

import os
from pathlib import Path

_LOADED = False

_ENV_FILES = [
    Path(__file__).resolve().parent.parent / ".env",  # data-service/.env
    Path(__file__).resolve().parent.parent.parent / "web" / ".env",  # ../web/.env
]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if not key:
        return None
    return key, value


def load_env() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for path in _ENV_FILES:
        if not path.exists():
            continue
        try:
            for raw in path.read_text(encoding="utf-8-sig").splitlines():
                parsed = _parse_env_line(raw)
                if not parsed:
                    continue
                key, value = parsed
                # 真实环境变量优先，不覆盖
                os.environ.setdefault(key, value)
        except Exception:  # noqa: BLE001 配置文件问题不阻塞服务
            continue

    # 键名别名统一
    if not os.environ.get("SEARCH_API_KEY") and os.environ.get("TAVILY_API_KEY"):
        os.environ["SEARCH_API_KEY"] = os.environ["TAVILY_API_KEY"]


def search_api_key() -> str | None:
    load_env()
    return os.environ.get("SEARCH_API_KEY") or None
