"""数值转换公共工具（B4：akshare_provider / tencent_provider 各有一份重复实现）。"""

from __future__ import annotations


def to_float(value, default=None):
    """防御式数值转换：数据源接口偶有 '-' / NaN / None。

    NaN 视同缺失（否则会以非 null 形式漏进响应，产出非法 JSON 的 NaN，
    并会让"缺失=剔除"类过滤失效——P6 实测踩到）。
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return default if f != f else f  # noqa: PLR0124 —— NaN 自比较
