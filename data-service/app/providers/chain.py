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


# ---------- R13：双源交叉验证（G3 / 批次 D） ----------


def verify_metric(
    type_: str,
    fn,
    field: str = "price",
    threshold_pct: float = 0.5,
    max_extra_sources: int = 1,
) -> dict:
    """取主源结果后，再用备用源取同一指标做交叉验证（R13）。

    - `fn(provider)` 返回该源的行情 dict（与 chain_call 同约定）
    - 仅在链上**存在备用源**时才追加请求（最多 max_extra_sources 个），
      避免默认放大外部请求量（与 R15 限流保护平衡）
    - 差异超阈值（相对偏差 %）时在结果 `note` 显式标注来源与偏差；
      差异在阈值内时标注"双源一致"
    - 备源不可用不影响主源结果（只记录说明）

    注意：本函数是**按需**调用（由 /quote/verified 端点驱动），
    不叠加到每次普通 /quote ——否则会成倍放大对限流敏感的数据源请求。
    """
    try:
        providers = get_provider_chain(type_)
    except KeyError:
        raise ProviderError(f"unsupported type: {type_}") from None

    if not providers:
        raise ProviderError("no provider")

    # 主源（沿用 chain_call 的降级语义）
    result = chain_call(type_, fn)
    primary_source = result.get("source")
    primary_val = result.get(field)

    notes: list[str] = []
    checked = 0
    for provider in providers:
        if checked >= max_extra_sources:
            break
        if provider.source == primary_source:
            continue
        checked += 1
        try:
            other = fn(provider)
        except (ProviderError, ProviderNotSupported) as e:
            notes.append(f"交叉验证源 {provider.source} 不可用（{e}）")
            continue
        other_val = other.get(field)
        if primary_val is None or other_val is None:
            notes.append(f"交叉验证源 {provider.source} 缺 {field}，无法比对")
            continue
        try:
            diff = abs(float(primary_val) - float(other_val))
            base = abs(float(primary_val)) or 1.0
            diff_pct = diff / base * 100
        except (TypeError, ValueError):
            notes.append(f"交叉验证源 {provider.source} 数值不可比对")
            continue
        if diff_pct > threshold_pct:
            notes.append(
                f"⚠ 双源偏差 {diff_pct:.2f}%（{primary_source}: {primary_val} vs "
                f"{provider.source}: {other_val}，阈值 {threshold_pct}%）"
            )
        else:
            notes.append(
                f"双源一致（{primary_source} vs {provider.source}，偏差 {diff_pct:.3f}%）"
            )

    if notes:
        merged = "；".join(notes)
        result["note"] = f"{result['note']}；{merged}" if result.get("note") else merged
    result["crossChecked"] = checked > 0
    return result
