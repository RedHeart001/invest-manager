"""LLM 客户端（OpenAI 兼容端点，P3 热点结构化用）。

配置全部来自环境变量（PLAN 配置项）：LLM_BASE_URL / LLM_API_KEY / LLM_MODEL。
未配置或不可达时返回 None —— 调用方走关键词规则回退（R10 优雅降级）。
"""

from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger("llm")

TIMEOUT = 60


def _cfg() -> tuple[str, str, str] | None:
    key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL")
    if not key or not model:
        return None
    base = os.environ.get("LLM_BASE_URL")
    if not base:
        # 与 web 端 llm.ts 对齐：BASE_URL 缺省时按模型名推断常见供应商
        m = model.lower()
        if "deepseek" in m:
            base = "https://api.deepseek.com"
        elif "glm" in m:
            base = "https://open.bigmodel.cn/api/paas/v4"
    if not base:
        return None
    return (base.rstrip("/"), key, model)


def configured() -> bool:
    return _cfg() is not None


def chat_json(system: str, user: str) -> dict | list | None:
    """请求 JSON 输出；失败返回 None（不抛异常，调用方降级）。"""
    cfg = _cfg()
    if not cfg:
        return None

    base, key, model = cfg
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            f"{base}/chat/completions",
            json=payload,
            headers=headers,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        content = (((r.json() or {}).get("choices") or [{}])[0].get("message") or {}).get(
            "content", ""
        )
        return _parse_json(content)
    except Exception as e:  # noqa: BLE001 网络/协议/限流
        log.warning("llm chat failed: %s: %s", type(e).__name__, str(e)[:200])
        return None


def _parse_json(content: str) -> dict | list | None:
    """容错解析：直接 parse → 提取 ```json 块 → 首个 {...} / [...] 片段。"""
    if not content:
        return None
    for candidate in (content, _fenced(content), _first_block(content)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _fenced(text: str) -> str | None:
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    return m.group(1).strip() if m else None


def _first_block(text: str) -> str | None:
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    return m.group(0) if m else None
