"""出网路径的唯一收敛点（W1，2026-11-27）。

背景：本机是"海外源要代理、国内源必须直连"的混合出网环境。

- 国内源（东财 CDN、新浪、腾讯）一旦被代理，实测直接从可用变成 `ProxyError`
  （2026-11-27 探针：`push2.eastmoney.com` 直连 200／3518ms，套同一枚代理则
  `ProxyError`）。东财还是 IP 级滚动限流的，路径错了整条腿就废。
- 海外源（CoinGecko、Tavily、yfinance、HKEX）反过来：直连会间歇 `SSLEOFError(8)`，
  代理能救一部分。

因此**不能**设全局代理，必须按源族分别声明。但"声明"不能靠调用方各自读
`os.environ`：容器里 `NO_PROXY` 由 compose 传入，默认值不含 `web`/`data-service`
（`.env` 里只有 `127.0.0.1,localhost,::1`），一旦填了 `HTTPS_PROXY`，连
`POST http://web:3000/api/sync` 这种容器间调用都会被拦。所以内部调用也走直连。

两个出口，语义互斥、都不依赖 `NO_PROXY` 是否写得全：

- `direct_proxies()` → `{"http": None, "https": None}`。**不是空字典**：requests 的
  `merge_environment_settings` 对 env 代理用的是 `proxies.setdefault(k, v)`，
  只有键**已存在**（值为 None）才能压住环境代理；`{}` 会被 env 原样填回来。
  这是本模块唯一一处"看起来能简化、实际会静默失效"的写法，`test_w1_http_egress.py`
  用真 env + 真 merge 反锁住它。
- `overseas_proxies()` → 配了就有、没配就是 `None`（此时与改造前行为一致，不虚构地址）。

海外请求还须配 `trust_env=False` 的独立 Session（`overseas_session()`）：`main.py`
默认把 `NO_PROXY` 设为 `*` 保护国内源，而 requests 的 `select_proxy` 会因此
绕过一切 env 代理 ⇒ 只有显式传 `proxies=` 才真正生效。
"""

from __future__ import annotations

import os

import requests

#: 压住环境代理的哨兵。见模块 docstring：空字典不管用，必须是"键存在且值为 None"。
_DIRECT = {"http": None, "https": None}


def direct_proxies() -> dict:
    """强制直连用的 `proxies=` 实参（国内源与容器内调用）。"""
    return dict(_DIRECT)


def _env_proxy() -> str:
    """海外代理地址；未配置返回空串。

    先 HTTPS 后 HTTP（与改造前 `crypto_provider._proxies` / `openbb_provider._proxies`
    一致），大写下划线形式与常见的小写形式都认。
    """
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or ""
    )


def overseas_proxies() -> dict | None:
    """海外源的 `proxies=` 实参；未配置返回 `None`（而不是空字典）。

    返回 `None` 是有意的：调用方据此判断"这次没配代理"，与"配了但值不可用"要能分开。
    """
    px = _env_proxy()
    return {"http": px, "https": px} if px else None


_overseas_session: requests.Session | None = None


def overseas_session() -> requests.Session:
    """`trust_env=False` 的共享会话：绕开全局 `NO_PROXY=*`，让显式代理真正生效。

    与 `crypto_provider._overseas_session` / `openbb_provider._overseas_session`
    改造前行为一致（那两处原本各自持有一份），现在收敛到这里。
    """
    global _overseas_session
    if _overseas_session is None:
        s = requests.Session()
        s.trust_env = False
        px = overseas_proxies()
        if px:
            s.proxies = px
        _overseas_session = s
    return _overseas_session


def reset_overseas_session() -> None:
    """丢弃缓存会话（测试与配置变更后重建用；生产路径不调用）。"""
    global _overseas_session
    if _overseas_session is not None:
        try:
            _overseas_session.close()
        except Exception:  # noqa: BLE001 关闭失败不影响功能
            pass
    _overseas_session = None


def direct_session(requests_module=None) -> requests.Session:
    """**新建**一枚强制直连的会话（国内源翻页用；不复用、由调用方 close）。

    为什么不复用共享会话：翻页链路有"发现异常就换一枚新会话重试"的既有语义
    （`us_list_job` / `_list_us_stocks` 的集中修复轮），共享一枚会把那条恢复路径
    变成空操作。`trust_env=False` 与 `proxies` 两件都要设——前者挡 env 里的
    `NO_PROXY` 之类，后者挡 env 里的代理本身。

    `requests_module`：**必须**由调用方传入自己模块里的那个 `requests`。
    离线套件换的是 `akp.requests` / `us_list_job.requests`（模块级名字），而本函数
    在 `utils/http.py` 里，直接用这里的 `requests` 就等于绕过替身 ⇒ 那些号称"零出网"
    的翻页用例会真的打到新浪（`test_cr9_59` 首跑即如此：一路要到 923 页的预算）。
    所以会话工厂也跟着被替换掉的那个名字走。
    """
    mod = requests if requests_module is None else requests_module
    s = mod.Session()
    s.trust_env = False
    s.proxies = direct_proxies()
    return s
