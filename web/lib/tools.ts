// L1 工具注册表（PLAN M4 + P4 补强：已有 API 的薄封装，不写新数据逻辑）
// 命名空间约定：builtin:*（M7 Tool Gateway 挂点）
// 结果压缩：面向 LLM 的 token 经济（只返回必要字段，条数封顶）

import { dsGet } from "./data-service";
import { getKlineRange, normalizeRange } from "./kline";
import { listDigests } from "./hotspots";
import { detectPhases } from "./phases";
import { getLatestReport, startResearch } from "./research";
import { searchProducts } from "./search";
import { priceWithCurrency } from "./currency";
import type { LlmToolDef } from "./llm";
import { beijingToday, beijingShiftDays } from "./time";

export type ToolResult = { ok: boolean; summary: string; data?: unknown };

// CR7-4/B2a（2026-09-24）：产品类型单一来源。此前四处 `enum` 各写各的——
// hk 全缺、us 只在两处，Agent 的 schema 层根本无法寻址港股（4707 只标的
// "腾讯控股多少钱"问不出）。须核对 test-p4 19 项（红线只锁工具名不锁 enum）。
export const PRODUCT_TYPE_ENUM = ["stock", "fund", "bond", "crypto", "hk", "us"] as const;

// 研报类工具的子集（engine 只支持 A股/美股，见 data-service research 契约）
export const RESEARCH_TYPE_ENUM = ["stock", "us"] as const;

const JSON_SCHEMA = {
  type: "object",
  properties: {},
  required: [],
} as const;

export const L1_TOOLS: LlmToolDef[] = [
  {
    type: "function",
    function: {
      name: "search_products",
      description:
        "按名称/代码/拼音/标签搜索理财产品（股票、基金、债券等），返回匹配列表与实时价格",
      parameters: {
        type: "object",
        properties: {
          q: { type: "string", description: "搜索关键词，如 贵州茅台、600519、gzmt" },
          type: {
            type: "string",
            enum: [...PRODUCT_TYPE_ENUM],
            description: "可选，限定产品类型",
          },
          limit: { type: "number", description: "可选，返回条数（默认 8，最大 10）" },
        },
        required: ["q"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "get_quote",
      description: "获取单个产品的实时行情快照（价格、涨跌幅、开高低、成交量等）",
      parameters: {
        type: "object",
        properties: {
          type: {
            type: "string",
            enum: [...PRODUCT_TYPE_ENUM],
            description: "产品类型",
          },
          code: { type: "string", description: "产品代码，如 600519" },
        },
        required: ["type", "code"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "get_kline",
      description: "获取日 K 概要：最新收盘、区间涨跌、最高最低与最近几个交易日的数据",
      parameters: {
        type: "object",
        properties: {
          type: {
            type: "string",
            enum: [...PRODUCT_TYPE_ENUM],
            description: "产品类型",
          },
          code: { type: "string", description: "产品代码" },
          days: { type: "number", description: "回看天数（默认 30，最大 365）" },
        },
        required: ["type", "code"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "get_hotspots",
      description: "获取最近的市场热点 digest（标题、板块标签）",
      parameters: { ...JSON_SCHEMA },
    },
  },
  {
    type: "function",
    function: {
      name: "get_fund_holdings",
      description: "获取场外基金的最新披露重仓持股（Top10）",
      parameters: {
        type: "object",
        properties: {
          code: { type: "string", description: "场外基金代码，如 110022" },
        },
        required: ["code"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "get_phase_analysis",
      description:
        "获取某产品近期走势的阶段划分（上涨/下跌/震荡各段的幅度与天数）与可能相关事件，用于回答'最近为什么涨/跌'类问题",
      parameters: {
        type: "object",
        properties: {
          type: {
            type: "string",
            enum: [...PRODUCT_TYPE_ENUM],
            description: "产品类型",
          },
          code: { type: "string", description: "产品代码" },
          days: { type: "number", description: "回看天数（默认 90）" },
        },
        required: ["type", "code"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "get_fund_report",
      description:
        "获取场外基金的定期报告解数据：报告清单（季报/半年报/年报披露记录）与最新披露的行业配置占比",
      parameters: {
        type: "object",
        properties: {
          code: { type: "string", description: "场外基金代码，如 110022" },
        },
        required: ["code"],
      },
    },
  },
];

// L2 深度研究工具（P5 / M5：分钟级异步，与详情页按钮同一链路）
export const L2_TOOLS: LlmToolDef[] = [
  {
    type: "function",
    function: {
      name: "deep_research",
      description:
        "触发某标的的深度研究（多角色研报：技术/基本面/新闻情绪分析师 + 多空辩论 + 评级，约 2~5 分钟异步完成）。当日同一标的限一次。",
      parameters: {
        type: "object",
        properties: {
          type: {
            type: "string",
            enum: [...RESEARCH_TYPE_ENUM],
            description: "市场类型（stock=A股，us=美股）",
          },
          code: { type: "string", description: "标的代码，如 600519 或 AAPL" },
        },
        required: ["code"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "get_research_report",
      description: "获取某标的最近一次深度研报（评级、综合结论与降级说明）",
      parameters: {
        type: "object",
        properties: {
          type: {
            type: "string",
            enum: [...RESEARCH_TYPE_ENUM],
            description: "市场类型（stock=A股，us=美股）",
          },
          code: { type: "string", description: "标的代码" },
        },
        required: ["code"],
      },
    },
  },
];

// Agent 实际暴露给 LLM 的完整工具集（L1 即时 + L2 深度）
export const AGENT_TOOLS: LlmToolDef[] = [...L1_TOOLS, ...L2_TOOLS];

const round2 = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? null : Math.round(v * 100) / 100;

/** 行情字段转换（代码审查修复）：Number(null)===0 会把"缺价"上报成 0 元，
 *  LLM 会据此回答"现价 0 元"。缺失一律保持 null。 */
const numOrNull = (v: unknown): number | null => {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : null;
};

async function toolSearchProducts(args: {
  q: string;
  type?: string;
  limit?: number;
}): Promise<ToolResult> {
  const q = String(args.q ?? "").trim();
  if (!q) return { ok: false, summary: "缺少搜索关键词 q" };
  const results = await searchProducts({
    q,
    type: args.type,
    limit: Math.min(Math.max(args.limit ?? 8, 1), 10),
  });
  return {
    ok: true,
    summary: `找到 ${results.length} 条`,
    data: results.map((r) => ({
      type: r.type,
      code: r.code,
      name: r.name,
      price: round2(r.price),
      changePct: round2(r.changePct),
      tags: r.tags.slice(0, 3),
    })),
  };
}

async function toolGetQuote(args: { type: string; code: string }): Promise<ToolResult> {
  const q = await dsGet<Record<string, unknown>>("/quote", { type: args.type, code: args.code }, 20_000);
  const price = numOrNull(q.price);
  // CR7-4/B2c：非 CNY 报价带币种单位（HKD→港币 / USD→美元），LLM 回答与 UI 同口径
  const priceSummary =
    price != null
      ? priceWithCurrency(
          `${q.name ?? args.code} 现价 ${price}`,
          typeof q.currency === "string" ? q.currency : null,
        )
      : `${q.name ?? args.code} 暂无可用报价（外部源未返回价格）`;
  return {
    ok: price != null,
    summary: priceSummary,
    data: {
      name: q.name ?? null,
      price,
      currency: typeof q.currency === "string" ? q.currency : null,
      changePct: numOrNull(q.changePct),
      open: numOrNull(q.open),
      high: numOrNull(q.high),
      low: numOrNull(q.low),
      prevClose: numOrNull(q.prevClose),
      volume: numOrNull(q.volume),
      source: q.source ?? null,
    },
  };
}

async function toolGetKline(args: { type: string; code: string; days?: number }) {
  const days = Math.min(Math.max(args.days ?? 30, 5), 365);
  const range = normalizeRange(null, null);
  if ("error" in range) return { ok: false, summary: range.error };
  const start = beijingShiftDays(-days);
  const k = await getKlineRange(args.type, args.code, start, range.end);
  if (k.candles.length === 0) return { ok: false, summary: "无 K 线数据（可能外部源不可用）" };
  const first = k.candles[0];
  const last = k.candles[k.candles.length - 1];
  const pct = first.close ? ((last.close / first.close - 1) * 100).toFixed(2) : null;
  return {
    ok: true,
    summary: `${args.code} 近 ${k.candles.length} 个交易日，区间涨跌 ${pct}%`,
    data: {
      interval: "1d",
      rangeStart: first.date,
      rangeEnd: last.date,
      latestClose: round2(last.close),
      rangeChangePct: pct == null ? null : Number(pct),
      rangeHigh: round2(Math.max(...k.candles.map((c) => c.high))),
      rangeLow: round2(Math.min(...k.candles.map((c) => c.low))),
      recent: k.candles.slice(-5).map((c) => ({
        date: c.date,
        close: round2(c.close),
        volume: c.volume,
      })),
      source: k.source,
    },
  };
}

async function toolGetHotspots(): Promise<ToolResult> {
  const { date, rows } = await listDigests({ limit: 5 });
  if (rows.length === 0) return { ok: true, summary: "暂无热点 digest 数据" };
  return {
    ok: true,
    summary: `${date} 共 ${rows.length} 条热点`,
    data: rows.map((r) => ({
      title: r.title,
      boards: r.boardTags,
      engine: r.engine,
      degraded: r.degraded,
    })),
  };
}

async function toolGetFundHoldings(args: { code: string }) {
  const data = await dsGet<{
    degraded: boolean;
    note: string | null;
    quarter: string | null;
    holdings: { code: string; name: string; weight: number | null }[];
  }>("/fund/holdings", { code: args.code }, 30_000);
  if (data.degraded || data.holdings.length === 0) {
    return { ok: false, summary: `重仓数据不可用（${data.note ?? "未披露"}）` };
  }
  return {
    ok: true,
    summary: `${data.quarter} 前十大重仓`,
    data: data.holdings.map((h) => ({
      name: h.name,
      code: h.code,
      weight: h.weight == null ? null : Math.round(h.weight * 100) / 100,
    })),
  };
}

async function toolGetFundReport(args: { code: string }): Promise<ToolResult> {
  const data = await dsGet<{
    degraded: boolean;
    note: string | null;
    reports: { title: string; date: string; id: string }[];
    industry: { asOf: string; items: { name: string; weight: number }[] } | null;
  }>("/fund/report", { code: args.code }, 30_000);
  if (data.degraded || (data.reports.length === 0 && !data.industry)) {
    return { ok: false, summary: `定期报告数据不可用（${data.note ?? "未披露"}）` };
  }
  return {
    ok: true,
    summary: `报告 ${data.reports.length} 条${
      data.industry ? `；行业配置截至 ${data.industry.asOf}` : "；行业配置未披露"
    }`,
    data: {
      报告清单: data.reports.map((r) => ({ 标题: r.title, 日期: r.date })),
      行业配置: data.industry
        ? {
            截至: data.industry.asOf,
            占比: data.industry.items.map((i) => `${i.name} ${i.weight}%`),
          }
        : null,
    },
  };
}

async function toolGetPhaseAnalysis(args: { type: string; code: string; days?: number }) {
  const days = Math.min(Math.max(args.days ?? 90, 30), 365);
  const start = beijingShiftDays(-days);
  const k = await getKlineRange(args.type, args.code, start, normalizeRangeEnd());
  if (k.candles.length < 2) return { ok: false, summary: "无足够 K 线数据" };
  const phases = detectPhases(k.candles).map((p) => ({
    阶段: p.label,
    时段: `${p.startDate} → ${p.endDate}`,
    幅度: `${p.changePct >= 0 ? "+" : ""}${p.changePct}%`,
    交易日: p.tradingDays,
  }));
  return {
    ok: true,
    summary: `近 ${k.candles.length} 个交易日划分出 ${phases.length} 个阶段`,
    data: { phases, source: k.source, 提示: "阶段为算法划分；如需因果解释请结合新闻事件，不构成投资建议" },
  };
}

// ---------- L2 深度研究工具（P5 / M5：分钟级异步，与详情页按钮同一链路） ----------

async function toolDeepResearch(args: { type?: string; code: string }): Promise<ToolResult> {
  const code = String(args.code ?? "").trim();
  if (!code) return { ok: false, summary: "缺少标的代码" };
  const type = String(args.type ?? (/\d{6}/.test(code) ? "stock" : "us"));
  // 进程内直调（会做当日 done 复用 / running 判重 / 每日限 1 次）
  const result = await startResearch(type, code);
  if (result.status === "done") {
    return { ok: true, summary: "该标的今日研报已完成，可用 get_research_report 获取" };
  }
  if (result.status === "running") {
    return {
      ok: true,
      summary: `深度研究已启动（约 2~5 分钟）：${result.reason ?? "执行中"}。完成后可用 get_research_report 获取。`,
    };
  }
  return { ok: false, summary: `研究任务未能启动：${result.reason ?? "unknown"}` };
}

async function toolGetResearchReport(args: { type?: string; code: string }): Promise<ToolResult> {
  const code = String(args.code ?? "").trim();
  if (!code) return { ok: false, summary: "缺少标的代码" };
  const type = String(args.type ?? (/\d{6}/.test(code) ? "stock" : "us"));
  const row = await getLatestReport(type, code);
  if (!row) return { ok: false, summary: "该标的暂无研报（可先触发 deep_research）" };
  if (row.status === "running") {
    return { ok: true, summary: "深度研究执行中，稍后再用本工具获取" };
  }
  if (row.status === "failed") {
    return { ok: false, summary: `最近一次研究失败：${row.error ?? "unknown"}` };
  }
  const degradedNote =
    row.fullReport?.meta?.degraded
      ? `（降级产出：${row.fullReport.meta.note ?? "部分数据源不可用"}）`
      : "";
  return {
    ok: true,
    summary: `评级：${row.rating}。${row.summary ?? ""}${degradedNote}`,
    data: { rating: row.rating, 结论: row.summary, 降级说明: degradedNote || undefined },
  };
}

function normalizeRangeEnd(): string {
  return beijingToday(); // B4：统一走公共 util
}

export async function executeTool(
  name: string,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  try {
    switch (name) {
      case "search_products":
        return await toolSearchProducts(args as { q: string; type?: string; limit?: number });
      case "get_quote":
        return await toolGetQuote(args as { type: string; code: string });
      case "get_kline":
        return await toolGetKline(args as { type: string; code: string; days?: number });
      case "get_hotspots":
        return await toolGetHotspots();
      case "get_fund_holdings":
        return await toolGetFundHoldings(args as { code: string });
      case "get_fund_report":
        return await toolGetFundReport(args as { code: string });
      case "get_phase_analysis":
        return await toolGetPhaseAnalysis(args as { type: string; code: string; days?: number });
      case "deep_research":
        return await toolDeepResearch(args as { type?: string; code: string });
      case "get_research_report":
        return await toolGetResearchReport(args as { type?: string; code: string });
      default:
        return { ok: false, summary: `未知工具：${name}` };
    }
  } catch (e) {
    return { ok: false, summary: e instanceof Error ? e.message : "工具执行失败" };
  }
}
