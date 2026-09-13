"""主备源链调用公共实现（B4：main.py 与 mcp_server.py 各有一份近重复实现）。

与 R15/M8 一致：按注册链依次尝试，任一家成功即返回并标注降级状态；
全部失败时抛 ProviderError，由调用方决定 HTTP 映射（502/501）或降级响应。
"""

from __future__ import annotations

from .base import ProviderError, ProviderNotSupported, get_provider_chain


def chain_call(type_: str, fn, unsupported_detail: str | None = None) -> dict:
    """按主备源链依次尝试。

    - `fn(provider)` 返回该源的结果（dict 或任意值）
    - 次源及以上成功时，在结果 dict 的 `note` 字段追加降级标注
    - 全部失败时抛 ProviderError
    - 类型未注册时抛 ProviderError（由调用方转成 400）
    """
    try:
        providers = get_provider_chain(type_)
    except KeyError:
        raise ProviderError(unsupported_detail or f"unsupported type: {type_}") from None
    errors: list[str] = []
    for idx, provider in enumerate(providers):
        try:
            result = fn(provider)
        except (ProviderError, ProviderNotSupported) as e:
            errors.append(f"{provider.source}: {e}")
            continue
        if idx > 0 and isinstance(result, dict):
            degrade_note = f"主源不可用，已降级至 {provider.source}（{errors[0]}）"
            result["note"] = (
                f"{result['note']}；{degrade_note}" if result.get("note") else degrade_note
            )
        return result
    raise ProviderError(
        "all sources failed: " + "; ".join(errors) if errors else "no provider"
    )
