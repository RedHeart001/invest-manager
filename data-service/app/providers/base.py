from abc import ABC, abstractmethod


class ProviderError(Exception):
    """外部数据源调用失败（网络/接口变动/代码不存在等）。"""


class ProviderNotSupported(ProviderError):
    """该 provider 尚未实现此能力（如某类型的行情）。"""


class BaseProvider(ABC):
    """数据源适配器基类。子类实现统一 schema 的 quote/kline，可选实现 list_products。"""

    source: str = "unknown"

    @abstractmethod
    def get_quote(self, type_: str, code: str) -> dict: ...

    @abstractmethod
    def get_kline(
        self,
        type_: str,
        code: str,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
    ) -> dict: ...

    def list_products(self, type_: str) -> list[dict]:
        """全量产品列表（供 P1 同步）。

        统一 schema：{type, code, name, pinyin, pinyinInitials, exchange, tags}

        内部**自带主备切换**的 provider 可改返 `(items, meta)` 元组声明真正的出网源
        与降级说明——见 `list_products_with_meta`（CR9-31）。
        """
        raise ProviderNotSupported(f"{self.source} does not support list_products")

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        """批量实时行情（供搜索结果价格富集）。返回 {code: quote}。"""
        raise ProviderNotSupported(f"{self.source} does not support get_quotes")

    def touches_eastmoney(self, type_: str, codes: list[str]) -> bool:
        """这一批代码按**本 provider 的路由**会不会打东财 ulist 通道（丙／CR9-67）。

        默认 `False`：腾讯／新浪／新浪转债／yfinance／CoinGecko 都不走东财。
        为什么由 provider 自己说而不是让调用方按类型名猜——判据（哪些代码走哪条通道）
        本来就住在 `get_quotes` 里，两张表分开放迟早各说各话。
        """
        return False


_QUOTE_REGISTRY: dict[str, BaseProvider] = {}
_LIST_REGISTRY: dict[str, BaseProvider] = {}
# 备源链（R15/M8）：type → [(position, provider), ...]，按 position 升序排列
_CHAIN_REGISTRY: dict[str, list[tuple[int, BaseProvider]]] = {}


def register(types: list[str], provider: BaseProvider) -> None:
    """注册实时行情（quote/kline）主源能力。"""
    for t in types:
        _QUOTE_REGISTRY[t] = provider


def register_list(types: list[str], provider: BaseProvider) -> None:
    """注册产品列表能力（可与行情能力来自不同 provider）。"""
    for t in types:
        _LIST_REGISTRY[t] = provider


def register_chain(types: list[str], provider: BaseProvider, position: int = 1) -> None:
    """把 provider 挂到指定类型的备源位（position ≥1；主源为 0，来自 register）。"""
    for t in types:
        _CHAIN_REGISTRY.setdefault(t, []).append((position, provider))


def get_provider(type_: str) -> BaseProvider:
    if type_ not in _QUOTE_REGISTRY:
        raise KeyError(type_)
    return _QUOTE_REGISTRY[type_]


def get_provider_chain(type_: str) -> list[BaseProvider]:
    """主源 + 备源的有序链（R15/M8）。主源缺失时只返回备源。"""
    chain: list[BaseProvider] = []
    primary = _QUOTE_REGISTRY.get(type_)
    if primary is not None:
        chain.append(primary)
    backups = sorted(_CHAIN_REGISTRY.get(type_, []), key=lambda x: x[0])
    chain.extend(p for _, p in backups)
    if not chain:
        raise KeyError(type_)
    return chain


def get_list_provider(type_: str) -> BaseProvider:
    if type_ not in _LIST_REGISTRY:
        raise KeyError(type_)
    return _LIST_REGISTRY[type_]


def list_products_with_meta(
    provider: BaseProvider, type_: str
) -> tuple[list[dict], dict]:
    """取全量列表，并拿到"这批数据实际来自哪个上游"（CR9-31，R16）。

    默认契约不变：provider 返回 `list[dict]` ⇒ 元信息只有 provider 自己的 `source`。
    **内部自带主备切换**的 provider 返回 `(items, meta)` ⇒ 由它自己声明真正的出网源
    与降级说明。为什么必须显式声明（09-27 实证）：东财冷却时 `?type=bond` 的列表
    1059→327 只，而响应里没有任何字段说得出"这 327 只是备源快照、覆盖面天然如此"，
    降级对消费侧完全不可见——同一件事在行情链路上早就由 `chain_call` 写进 `note`
    （`chain.py:31-35`），列表链路此前是漏的。
    """
    raw = provider.list_products(type_)
    if isinstance(raw, tuple):
        items, meta = raw
        return items, {"source": provider.source, **(meta or {})}
    return raw, {"source": provider.source}
