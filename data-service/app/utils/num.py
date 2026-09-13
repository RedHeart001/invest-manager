"""数值转换公共工具（B4：akshare_provider / tencent_provider 各有一份重复实现）。"""

from __future__ import annotations

import math


def to_float(value, default=None):
    """防御式数值转换：数据源接口偶有 '-' / NaN / None / inf。

    非有限值（NaN、±Inf）一律视同缺失——否则会以非 null 形式漏进响应：
    产出非法 JSON（Starlette 序列化用 allow_nan=False，会抛 ValueError 变 500），
    并让"缺失=剔除"类过滤失效（P6 / 2026-09-13 review 两次踩到）。
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default
