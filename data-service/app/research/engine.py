"""M5 深度研究引擎（B 计划：自研多角色 LLM 链）。

PLAN 允许：TradingAgents spike 失败时启动 B 计划（自研简化多智能体）。
本实现为单进程多角色链：
  技术分析师 / 基本面分析师 / 新闻情绪分析师 → 多空辩论 → 研究经理（评级+摘要+风控）

- LLM 复用 hotspot.llm_client（OpenAI 兼容，DeepSeek/GLM）
- 熔断（P5 补强）：LLM 调用次数上限 + 任务总超时 → 标记 failed
- 话语体系（R11/R15）：一律"可能相关"，输出含免责声明；引用 P2 同源阶段数据
- 每个角色输入 = vendor_adapter 采集的真实数据（JSON 压缩），无数据维度显式缺口
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from ..config import load_env
from ..hotspot import llm_client
from . import adapter

load_env()  # 确保 LLM_* 就位（任何入口进程一致）

log = logging.getLogger("research.engine")

# 熔断阈值支持 env 覆盖（P5 增补验证：超限 failed 路径可实测）
MAX_LLM_CALLS = int(os.environ.get("RESEARCH_MAX_LLM_CALLS", "12"))
TASK_TIMEOUT_S = int(os.environ.get("RESEARCH_TASK_TIMEOUT_S", "480"))

RATING_ENUM = ("乐观", "中性", "谨慎", "悲观")


class _Budget:
    """LLM 调用预算与任务截止时间（熔断）。"""

    def __init__(self) -> None:
        self.calls = 0
        self.deadline = time.monotonic() + TASK_TIMEOUT_S

    def allow(self) -> bool:
        return self.calls < MAX_LLM_CALLS and time.monotonic() < self.deadline

    def timed_out(self) -> bool:
        return time.monotonic() > self.deadline


def _ask(budget: _Budget, system: str, user: str, timeout: int = 120):
    """带熔断的 LLM JSON 调用；超限/失败返回 None。"""
    if not budget.allow():
        return None
    budget.calls += 1
    return llm_client.chat_json(system, user, timeout=timeout)


def _compact_market(market: dict) -> str:
    if not market.get("ok"):
        return "（行情不可用）"
    d = market["data"]
    return json.dumps(
        {k: d.get(k) for k in ("price", "changePct", "open", "high", "low", "prevClose", "currency", "source")},
        ensure_ascii=False,
    )


def _compact_kline(kline: dict) -> str:
    if not kline.get("ok"):
        return "（K 线不可用）"
    d = kline["data"]
    phases = json.dumps(d.get("phases", []), ensure_ascii=False)[:1200]
    recent = json.dumps(d.get("candles", [])[-10:], ensure_ascii=False)
    return f"阶段划分（P2 同源算法）：{phases}\n最近交易日：{recent}"


def _compact_fundamentals(fund: dict) -> str:
    if not fund.get("ok"):
        return "（财务数据不可用）"
    periods = (fund["data"] or {}).get("periods") or []
    return json.dumps(periods[:4], ensure_ascii=False)[:1500]


def _compact_news(news: dict) -> str:
    if not news.get("ok"):
        return "（新闻不可用）"
    src = news.get("source", "")
    kind = "公告（官方披露）" if "cninfo" in src else "新闻"
    items = [
        {"类型": kind, "title": it.get("title", ""), "summary": (it.get("summary") or "")[:100]}
        for it in (news["data"] or [])[:8]
    ]
    return f"来源：{src}\n" + json.dumps(items, ensure_ascii=False)


def run_research(type_: str, code: str, name: str, on_progress=None) -> dict:
    """执行一次深度研究，返回研报 dict（含 meta.llmCalls/degraded/gaps）。"""

    class _Progress:
        def __init__(self) -> None:
            self.steps: list[str] = []

        def __call__(self, text: str) -> None:
            self.steps.append(text)
            if on_progress:
                try:
                    on_progress(list(self.steps))  # 无锁快照（GIL 下赋值原子）
                except Exception:  # noqa: BLE001
                    pass

    progress = _Progress()
    budget = _Budget()

    progress("采集行情 / K 线 / 新闻 / 财务数据（统一数据层）")
    payload, gaps = adapter.collect_all(type_, code)

    if budget.timed_out():
        return {"ok": False, "error": "任务超时（采集阶段）", "llmCalls": 0}

    analysts: list[dict] = []

    # ---- 角色 1：技术分析师 ----
    progress("技术分析师分析中")
    r1 = _ask(
        budget,
        "你是技术分析师。基于阶段划分与最近行情数据，输出 JSON："
        '{"view":"看多/看空/中性","points":["要点1","要点2","要点3"]}。'
        "要点需引用具体数据（幅度/百分比/日期）。语气客观谨慎。",
        f"标的：{name}（{code}）\n实时行情：{_compact_market(payload['market'])}\n"
        f"K线与阶段：{_compact_kline(payload['kline'])}",
    )
    if isinstance(r1, dict) and r1.get("view"):
        analysts.append({"role": "技术分析师", "dataBased": True, **r1})

    # ---- 角色 2：基本面分析师（A 方案：真实财务数据喂入） ----
    progress("基本面分析师分析中")
    fund_available = payload["fundamentals"].get("ok")
    r2 = _ask(
        budget,
        "你是基本面分析师。基于提供的财务摘要数据（最近 4 个报告期）分析，输出 JSON："
        '{"view":"看多/看空/中性/无法判断","points":["要点1","要点2","要点3"],'
        '"dataBased":true或false}。'
        "规则：有财务数据时必须引用具体数字与报告期，不得引用你的训练记忆中的公司信息；"
        "无财务数据时 view 必须为「无法判断」，points 说明缺了什么数据，"
        "禁止给出方向性结论，禁止编造任何财务数字。",
        f"标的：{name}（{code}）\n实时行情：{_compact_market(payload['market'])}\n"
        f"财务摘要（最近4期）：{_compact_fundamentals(payload['fundamentals'])}\n"
        f"可用新闻：{_compact_news(payload['news'])}",
    )
    if isinstance(r2, dict) and r2.get("view"):
        analysts.append(
            {
                "role": "基本面分析师",
                "dataBased": bool(r2.get("dataBased")) and fund_available,
                **{k: v for k, v in r2.items() if k != "dataBased"},
            }
        )

    # ---- 角色 3：新闻情绪分析师 ----
    progress("新闻情绪分析师分析中")
    news_available = payload["news"].get("ok")
    r3 = _ask(
        budget,
        "你是新闻/公告情绪分析师。基于提供的新闻或公告列表评估短期市场情绪，输出 JSON："
        '{"view":"看多/看空/中性/无法判断","points":["要点1","要点2","要点3"],'
        '"dataBased":true或false}。'
        "规则：列表为空或不可用时 view 必须为「无法判断」且不得给出方向性判断；"
        "有内容时论点必须引用具体标题，不得凭空推断。",
        f"标的：{name}（{code}）\n新闻/公告列表：{_compact_news(payload['news'])}",
    )
    if isinstance(r3, dict) and r3.get("view"):
        analysts.append(
            {
                "role": "新闻情绪分析师",
                "dataBased": bool(r3.get("dataBased")) and news_available,
                **{k: v for k, v in r3.items() if k != "dataBased"},
            }
        )

    if not analysts:
        return {
            "ok": False,
            "error": "分析师角色均未能产出观点（LLM 不可用或全部熔断）",
            "llmCalls": budget.calls,
        }

    # ---- 角色 4：多空辩论（仅采信有真实数据支撑的观点——P0 话语约束） ----
    progress("多空辩论中")
    data_based = [a for a in analysts if a.get("dataBased")]
    no_data = [a["role"] for a in analysts if not a.get("dataBased")]
    debate_input = {
        "analysts": data_based,
        "缺口说明": (
            f"以下角色无真实数据支撑，其观点不计入辩论：{('、'.join(no_data))}" if no_data else "无"
        ),
    }
    r4 = _ask(
        budget,
        "你是辩论主持人。基于以下分析师观点整理一轮多空辩论，输出 JSON："
        '{"bull":["多方论点1","多方论点2"],"bear":["空方论点1","空方论点2"]}'
        "。论点必须来自分析师观点引用的数据，不得新增虚构数据；"
        "标注为无数据支撑的角色观点不得引用。",
        json.dumps(debate_input, ensure_ascii=False),
    )
    debate = r4 if isinstance(r4, dict) and (r4.get("bull") or r4.get("bear")) else None
    if debate is None and no_data:
        debate = {"bull": [], "bear": [], "note": f"有数据支撑的角色不足，辩论未产出（{('、'.join(no_data))} 缺数据）"}

    # ---- 角色 5：研究经理 ----
    progress("研究经理汇总评级")
    r5 = _ask(
        budget,
        "你是研究经理。综合全部观点与辩论，输出最终 JSON："
        '{"rating":"乐观/中性/谨慎/悲观","summary":"150字以内的综合结论",'
        '"risk":["风险提示1","风险提示2"]}。'
        "规则：观点分歧时如实呈现分歧；不确定时评级向中性靠拢；"
        "无真实数据支撑的维度只可作中性参考，不得作为评级依据；"
        "summary 中须说明哪些维度存在数据缺口；"
        "summary 结尾必须包含：仅供参考，不构成投资建议。",
        json.dumps({"analysts": analysts, "debate": debate}, ensure_ascii=False),
    )
    rating, summary, risks = "中性", "", []
    if isinstance(r5, dict):
        rating = r5.get("rating") if r5.get("rating") in ("乐观", "中性", "谨慎", "悲观") else "中性"
        summary = str(r5.get("summary", ""))[:400]
        risks = [str(x) for x in (r5.get("risk") or [])][:4]
    else:
        summary = "研究经理汇总未能产出（LLM 熔断），以下为各角色原始观点。"

    degraded = bool(gaps) or any(not a.get("points") for a in analysts)
    note_bits = [f"数据缺口：{g}" for g in gaps]
    if budget.calls >= MAX_LLM_CALLS:
        note_bits.append("触发 LLM 调用上限熔断")

    # P0 稳健性：LLM 偶尔把 points 返回为字符串而非数组 → 统一为数组（前端 .map 安全）
    def _norm_points(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()][:5]
        if isinstance(v, str) and v.strip():
            parts = [x.strip() for x in re.split(r"[\n；;]+", v) if x.strip()]
            return parts[:5] if parts else [v.strip()]
        return []

    analysts = [
        {
            "role": a["role"],
            "view": a.get("view", "中性"),
            "points": _norm_points(a.get("points")),
            "dataBased": bool(a.get("dataBased", True)),
        }
        for a in analysts
    ]

    # 数据截至标注（报告时点可审计）
    as_of = None
    if payload["kline"].get("ok"):
        candles = payload["kline"]["data"].get("candles") or []
        if candles:
            as_of = str(candles[-1].get("date", ""))[:10] or None

    report = {
        "ok": True,
        "rating": rating,
        "summary": summary or "（综合结论缺失）",
        "analysts": analysts,
        "debate": debate or {"bull": [], "bear": [], "note": "辩论未能产出"},
        "risk": risks or ["市场有风险，投资需谨慎"],
        "meta": {
            "llmCalls": budget.calls,
            "engine": "custom-multichar",
            "asOf": as_of,
            "sources": list({
                *( [payload["market"]["source"]] if payload["market"].get("ok") else [] ),
                *( [payload["kline"]["source"]] if payload["kline"].get("ok") else [] ),
                *( [payload["news"]["source"]] if payload["news"].get("ok") else [] ),
            }),
            # 维度可用性（2026-09-19 集成验收补充）：sources 按**来源名去重**，
            # 当行情/K线/新闻恰好同源（如均为 akshare）时会塌缩成 1 项，
            # 无法反映"采到了几个维度"。此处显式给出已采集维度，供 UI/验收判定。
            "dimensions": [
                dim for dim in ("market", "kline", "news") if payload[dim].get("ok")
            ],
            "degraded": degraded,
            "note": "；".join(note_bits)[:400] or None,
            "phasesSource": "P2 同源阶段算法",
        },
    }
    progress("研报生成完成")
    return report
