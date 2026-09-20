"""Provider 层：按产品类型路由到具体数据源，输出统一内部 schema。

统一 schema（对应 PLAN.md「Provider 层（统一行情 API）」）：
- quote:    {type, code, name, price, change, changePct, open, high, low,
             prevClose, volume, amount, timestamp, source}
- kline:    {type, code, interval, source, candles: [{date, open, high, low,
             close, volume, amount}]}
- product:  {type, code, name, pinyin, pinyinInitials, exchange, tags}

行情注册表与列表注册表分离：同一类型可由不同 provider 提供（如基金
有列表但行情待 P2 接入）。
"""

from .base import (
    BaseProvider,
    ProviderError,
    ProviderNotSupported,
    get_list_provider,
    get_provider,
    get_provider_chain,
    register_chain,
)
from . import akshare_provider  # noqa: F401  导入即注册（主源）
from . import tencent_provider  # noqa: F401  备源：A股/场内基金 行情+日K
from . import sina_provider  # noqa: F401  备源：场内基金日K（新浪）
from . import sina_bond_provider  # noqa: F401  备源：转债实时行情（新浪 cov_spot 快照）
from . import hk_provider  # noqa: F401  港股 provider（G6/批次 D）
from . import crypto_provider  # noqa: F401
from . import openbb_provider  # noqa: F401  美股 provider（yfinance 后端，P5/M6）
