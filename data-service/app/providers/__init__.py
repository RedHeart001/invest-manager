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

# ⚠ 注册语义（CR7-14-④，2026-09-24 实证核对）：
# akshare `register(["stock","fund","bond"])` 只进 _QUOTE_REGISTRY（主源注册表）；
# openbb `register_chain(["us"], position=0)` 只进 _CHAIN_REGISTRY——**"us" 不在
# _QUOTE_REGISTRY 里**。因此：
# - `get_provider("us")` 抛 KeyError（base.py:66 只查 _QUOTE_REGISTRY）；
# - `get_provider_chain("us")` 正常返回 [yfinance]（主源缺失时 chain 只含备源，
#   base.py:72 的语义——position=0 在 chain 里仍被当普通成员，不等于主源注册）。
# 代码若有"单源直取"场景对 us/hk 须走 get_provider_chain，勿用 get_provider。
# hk 同理：hk_provider 用 register_chain 注册（get_provider_chain("hk") =
# ['akshare-hk', 'tencent']），get_provider("hk") 同样 KeyError。
