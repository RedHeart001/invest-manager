"""微型 LRU 缓存（CR6-P2-1）：给进程内缓存统一容量上限，防止长期运行内存无界增长。

语义对齐 web 侧 `web/lib/lru.ts`：基于 dict 的插入序（Python 3.7+ 保证），
访问/写入即视为"最近使用"（移到末尾），超容量时淘汰最旧条目。

为何不用 functools.lru_cache：本项目的缓存值是"带 TTL 的元组"，且需要按 key
显式失效/覆盖，OrderedDict 语义更直接。容量上限可经 env 覆盖。
"""

from __future__ import annotations

import os
from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")
_MISSING = object()


def env_capacity(name: str, default: int) -> int:
    """从环境变量读容量上限（非法值回落到默认，不抛错）。"""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        n = int(raw)
    except ValueError:
        return default
    return n if n > 0 else default


class Lru(Generic[K, V]):
    """容量上限的 LRU 映射。接口保持与 dict 相近，便于替换既有无界 dict。"""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("Lru capacity must be > 0")
        self._capacity = capacity
        self._map: OrderedDict[K, V] = OrderedDict()

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        return len(self._map)

    def __contains__(self, key: K) -> bool:
        return key in self._map

    def get(self, key: K, default=None):
        v = self._map.get(key, _MISSING)
        if v is _MISSING:
            return default
        # 访问即提升到末尾（最近使用）
        self._map.move_to_end(key)
        return v

    def set(self, key: K, value: V) -> None:
        if key in self._map:
            self._map.move_to_end(key)
        self._map[key] = value
        while len(self._map) > self._capacity:
            self._map.popitem(last=False)  # 淘汰最旧

    # 便于把 `cache[k] = v` 的写法平滑替换为 `cache[k] = v`（保持下标语法）
    def __setitem__(self, key: K, value: V) -> None:
        self.set(key, value)

    def __getitem__(self, key: K) -> V:
        v = self._map[key]
        self._map.move_to_end(key)
        return v

    def delete(self, key: K) -> None:
        self._map.pop(key, None)

    def clear(self) -> None:
        self._map.clear()

    def keys(self):
        return self._map.keys()
