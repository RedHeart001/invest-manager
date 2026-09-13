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
        """
        raise ProviderNotSupported(f"{self.source} does not support list_products")

    def get_quotes(self, type_: str, codes: list[str]) -> dict[str, dict]:
        """批量实时行情（供搜索结果价格富集）。返回 {code: quote}。"""
        raise ProviderNotSupported(f"{self.source} does not support get_quotes")


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
