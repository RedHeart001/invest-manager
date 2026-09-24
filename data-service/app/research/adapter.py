"""M5 vendor_adapter：深度研究引擎的数据采集层。

PLAN 明确：TradingAgents/研究引擎不直接接外部源，全部经"统一数据层"取数。
实现方式（进程内直调 provider 链 + HTTP 回读 web 统一 API 的组合）：
- 行情 quote：进程内 provider 链（与 /quote 同一条链，R15 多源降级自动生效）
- K 线 + 阶段划分：HTTP 回读 web `/api/kline`（阶段划分由 P2 同源算法在 BFF
  侧计算并随响应返回——研报与详情页归因同源，补强要求）
- 新闻：us → openbb_provider（yfinance news）；A股 → akshare_provider.get_news
- 全维度 try/except 降级：采集失败的维度记入 gaps，研报中显式标注（R10/R12）
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from ..providers import ProviderError, get_provider_chain

log = logging.getLogger("research.adapter")

WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "http://localhost:3000")
TZ = ZoneInfo("Asia/Shanghai")


# web /api/kline 的 normalizeRange 只认带连字符的 ISO 日期（`^\d{4}-\d{2}-\d{2}$`），
# 紧凑 8 位会被判为"格式非法"并静默回落 90 天（CR7-2，契约见 CONSTRAINTS §B）。
# 注意：akshare/cninfo 侧的日期参数仍须紧凑 8 位，不走本函数（见 ak_stock_disclosures）。
def _iso_days_ago(days: int) -> str:
    dt = datetime.now(TZ) - timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


def _today_iso() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


# L3/O10：并发采集上限——看门狗超时后泄漏线程无法强杀（会活到上游恢复），
# 用信号量限制同时在场的采集线程数，防止上游持续挂起时线程无限累积
COLLECT_MAX_CONCURRENCY = int(os.environ.get("RESEARCH_MAX_COLLECT_THREADS", "4"))
# 名额等待上限：信号量耗尽（上游持续挂起占满名额）时不得永久阻塞，超时即降级
COLLECT_ACQUIRE_TIMEOUT = float(os.environ.get("RESEARCH_COLLECT_ACQUIRE_TIMEOUT", "60"))
_collect_slots = threading.Semaphore(COLLECT_MAX_CONCURRENCY)
_collect_live = 0  # 当前存活（含已放弃等待）的采集线程数，仅观测用
_collect_inflight = 0  # 已派发未释放的名额


def collect_stats() -> dict:
    """采集线程可观测信息（进 /research/status）。"""
    return {
        "maxConcurrency": COLLECT_MAX_CONCURRENCY,
        "live": _collect_live,
        "inFlight": _collect_inflight,
        "osThreads": threading.active_count(),
    }


def _run_with_timeout(fn, timeout_s: float):
    """带并发上限与看门狗超时的采集执行。

    返回 (result, None) 或 (None, 超时/错误说明)。超时后原线程仍在后台
    （占用一个信号量名额直到自然结束），但主流程不再等待。
    """
    global _collect_live, _collect_inflight

    box: dict = {"result": None}

    def _target():
        global _collect_live, _collect_inflight
        try:
            box["result"] = fn()
        except Exception as e:  # noqa: BLE001
            box["result"] = e
        finally:
            _collect_slots.release()
            _collect_inflight = max(0, _collect_inflight - 1)
            _collect_live = max(0, _collect_live - 1)

    # 名额等待有上限（修复：此前无限等待，名额被上游挂起的线程占满即永久阻塞）
    if not _collect_slots.acquire(timeout=COLLECT_ACQUIRE_TIMEOUT):
        return None, f"采集名额等待超时（>{int(COLLECT_ACQUIRE_TIMEOUT)}s，上游持续挂起），本次采集降级"
    _collect_live += 1
    _collect_inflight += 1
    t = threading.Thread(target=_target, daemon=True, name="research-collect")
    try:
        t.start()
    except Exception as e:  # noqa: BLE001 CR4：start 失败须回滚名额与计数（否则 4 次即耗尽）
        _collect_inflight = max(0, _collect_inflight - 1)
        _collect_live = max(0, _collect_live - 1)
        _collect_slots.release()
        return None, f"采集线程启动失败：{type(e).__name__}"
    t.join(timeout=timeout_s)
    if t.is_alive():
        return None, f"执行超时（>{int(timeout_s)}s，上游可能挂起）"
    r = box["result"]
    if isinstance(r, Exception):
        return None, f"{type(r).__name__}: {str(r)[:120]}"
    return r, None


def collect_market(type_: str, code: str) -> dict:
    """实时行情（进程内 provider 链，含 R15 降级；套看门狗防上游挂起）。"""
    try:
        chain = get_provider_chain(type_)
    except KeyError:
        return {"ok": False, "note": f"不支持的类型：{type_}"}
    errors: list[str] = []
    for p in chain:
        (q, err) = _run_with_timeout(lambda p=p: p.get_quote(type_, code), 60.0)
        if err:
            errors.append(f"{p.source}: {err}")
            continue
        return {"ok": True, "data": q, "source": p.source, "note": None}
    return {"ok": False, "note": "；".join(errors)[:200]}


def collect_kline_with_phases(type_: str, code: str, days: int = 120) -> dict:
    """K 线 + 阶段划分（HTTP 回读 web /api/kline，阶段与详情页同源）。"""
    (body, err) = _run_with_timeout(
        lambda: requests.get(
            f"{WEB_BASE_URL}/api/kline",
            params={"type": type_, "code": code, "start": _iso_days_ago(days), "end": _today_iso()},
            timeout=60,
        ),
        75.0,
    )
    if err:
        return {"ok": False, "note": f"K 线回读失败：{err}"}
    try:
        body.raise_for_status()
        data = body.json() or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "note": f"K 线回读解析失败：{e}"}
    candles = data.get("candles") or []
    if not candles:
        return {"ok": False, "note": str(data.get("note") or "无 K 线数据")}
    return {
        "ok": True,
        "data": {
            "candles": candles[-60:],  # 喂给 LLM 的量控制
            "phases": data.get("phases") or [],
            "source": data.get("source"),
        },
        "source": data.get("source"),
        "note": None,
    }


def collect_fundamentals(type_: str, code: str) -> dict:
    """基本面：财务摘要（同花顺主源 → 东财备源），取最近 4 个报告期关键指标。

    A 方案（2026-09-13）：补齐研报"基本面"维度的真实数据——此前该角色
    只能依赖 LLM 训练记忆，存在幻觉邻近风险（用户评估指出的核心问题）。
    """
    if type_ not in ("stock", "us"):
        return {"ok": False, "note": f"基本面数据暂不支持类型：{type_}"}

    import akshare as ak

    def _from_ths():
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if df is None or len(df) == 0:
            raise RuntimeError("ths empty")
        # 接口按报告期升序返回（1998 年在前）——必须取最新 4 期（降序）
        df = df.sort_values(df.columns[0], ascending=False).head(4)
        rows = []
        for _, r in df.iterrows():
            item = {"报告期": str(r.iloc[0])[:10]}
            for col in df.columns[1:]:
                v = r[col]
                s = str(v) if v is not None else ""
                if s in ("False", "None", "--", ""):
                    continue
                item[str(col)] = s
            rows.append(item)
        # 恢复时间正序（老 → 新），便于 LLM 阅读趋势
        rows.reverse()
        return rows

    def _from_em():
        df = ak.stock_financial_abstract(symbol=code)
        if df is None or len(df) == 0:
            raise RuntimeError("em empty")
        # 结构：选项/指标/20260630/... 长表 → 取前 4 个日期列的关键指标
        date_cols = [c for c in df.columns if str(c).isdigit()][:4]
        rows = []
        for dc in date_cols:
            item = {"报告期": str(dc)}
            for _, r in df.iterrows():
                metric = str(r.get("指标", "")).strip()
                v = r.get(dc)
                s = str(v) if v is not None else ""
                if metric and s not in ("None", "--", ""):
                    item[metric] = s
            rows.append(item)
        return rows

    for tag, fn in (("ths", _from_ths), ("em", _from_em)):
        (result, err) = _run_with_timeout(fn, 45.0)
        if err:
            log.warning("fundamentals %s failed: %s", tag, err)
            continue
        # 压缩：只保留关键指标（LLM token 经济）
        compact = []
        for row in result:
            keep = {
                k: row[k]
                for k in row
                if k == "报告期"
                or any(
                    kw in k
                    for kw in ("净利润", "营收", "收入", "每股收益", "毛利率", "净利率", "净资产收益率", "负债", "流动")
                )
            }
            compact.append(keep)
        if compact:
            return {
                "ok": True,
                "data": {"periods": compact, "source": tag},
                "source": f"fundamentals-{tag}",
                "note": None,
            }
    return {"ok": False, "note": "财务摘要同花顺/东财均不可用"}


def collect_news(type_: str, code: str, limit: int = 8) -> dict:
    """新闻：us 走 yfinance news；其余走 akshare provider（A股新闻源）。

    akshare 内部请求可能无 timeout（EM 限流时被挂死）——套看门狗超时强制放弃。
    """
    errors: list[str] = []

    def _try_chain(chain_type: str) -> dict | None:
        try:
            chain = get_provider_chain(chain_type)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            return None
        for p in chain:
            get_news = getattr(p, "get_news", None)
            if get_news is None:
                continue
            (result, err) = _run_with_timeout(lambda p=p: get_news(code), 45.0)
            if err:
                errors.append(f"{p.source}: {err}")
                continue
            # 契约兼容（代码审查修复）：provider.get_news 返回 list[dict]，
            # 此前按 dict 取 result["items"] → 一旦 A 股主源（akshare）真正返回
            # 新闻就抛 AttributeError，整个研报任务被打挂、巨潮备源成死代码。
            if isinstance(result, dict):
                items = result.get("items") or []
                source = result.get("source") or p.source
            else:
                items = list(result or [])
                source = p.source
            if not items:
                errors.append(f"{p.source}: empty")
                continue
            return {
                "ok": True,
                "data": items[:limit],
                "source": source,
                "note": None,
            }
        return None

    if type_ == "us":
        out = _try_chain("us")
        if out:
            return out
        return {"ok": False, "note": "；".join(errors)[:200] or "美股新闻源不可用"}

    # A股：个股新闻（东财，经 R15 限速/熔断）
    out = _try_chain("stock")
    if out:
        return out
    errors.append("个股新闻不可用")

    # 备源：巨潮公告（证监会指定披露平台，非东财域名；类型为公告而非新闻）
    (ann, err) = _run_with_timeout(lambda: ak_stock_disclosures(code), 45.0)
    if err:
        errors.append(f"巨潮公告: {err}")
        return {"ok": False, "note": "；".join(errors)[:200] or "新闻与公告源均不可用"}
    if ann:
        return {
            "ok": True,
            "data": ann,
            "source": "cninfo-公告",
            "note": "个股新闻源不可用，已降级为巨潮官方公告（类型为公告而非新闻）",
        }
    return {"ok": False, "note": "；".join(errors)[:200] or "新闻与公告源均不可用"}


def ak_stock_disclosures(code: str, limit: int = 8) -> list[dict]:
    """巨潮资讯公告（证监会指定披露平台）。"""
    import akshare as ak

    end = datetime.now(TZ)
    start = end - timedelta(days=60)
    df = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=code,
        market="沪深京",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if df is None or len(df) == 0:
        raise RuntimeError("cninfo empty")
    out = []
    for _, r in df.head(limit).iterrows():
        title = str(r.get("公告标题", "") or "").strip()
        if not title:
            continue
        out.append(
            {
                "title": title,
                "summary": "",  # 公告无摘要，标题即信息
                "url": str(r.get("公告链接", "") or ""),
                "time": str(r.get("公告时间", "") or ""),
            }
        )
    if not out:
        raise RuntimeError("cninfo unparsable")
    return out


def collect_all(type_: str, code: str) -> tuple[dict, list[str]]:
    """采集全部维度，返回 (payload, gaps)。payload 各维度独立 ok/note。"""
    market = collect_market(type_, code)
    kline = collect_kline_with_phases(type_, code)
    news = collect_news(type_, code)
    fundamentals = collect_fundamentals(type_, code)
    payload = {"market": market, "kline": kline, "news": news, "fundamentals": fundamentals}
    gaps: list[str] = []
    for dim, res in payload.items():
        if not res.get("ok"):
            gaps.append(f"{dim}：{res.get('note', '不可用')}")
    return payload, gaps


def research_date() -> str:
    # CR-06：统一北京时间口径
    from ..utils.timeutil import beijing_today

    return beijing_today()
