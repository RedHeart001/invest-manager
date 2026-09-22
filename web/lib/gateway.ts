// Tool Gateway（PLAN M7 / P6 二轮补强）
//
// 三类工具源聚合后统一命名空间（对 LLM 透明）：
//   builtin:*  —— 原有 L1/L2 工具（AGENT_TOOLS，**发给 LLM 的名字保持不变**，P4 兼容红线）
//   skill:*    —— 技能（prompt 指令包，编排既有工具，不注册新函数）
//   mcp:*      —— 第三方 MCP server 工具（LLM 侧名 `mcp_<server>_<tool>`）
//
// 设计约束：
// - 命名空间仅用于**内部分类与状态展示**，不改变 builtin 工具对 LLM 的可见名称（test-p4 19/19 回归红线）
// - 任一来源不可用时降级为"该源工具不可用"，不阻塞对话

import { AGENT_TOOLS, executeTool } from "./tools";
import { mcpLlmTools, callMcpTool, mcpStatus } from "./mcp";
import { loadSkills, selectSkills, skillRouterMode, skillsBodyPrompt, skillsMetaPrompt, skillsStatus } from "./skills";
import type { LlmToolDef } from "./llm";

export type ToolSource = "builtin" | "skill" | "mcp";

export const BASE_SYSTEM_PROMPT = `你是"投资理财助手"（Invest Manager）的金融分析 AI。
- 定位：帮助用户理解行情、查询产品信息、解读市场热点与走势阶段。
- 你可以调用工具查询实时数据；回答要基于工具返回的真实数据，不要编造数字。
- 涉及涨跌原因时使用"可能相关"等谨慎表述，不做因果断言；不给出确定性买卖指令。
- 回答末尾如涉及投资判断，附一句"仅供参考，不构成投资建议"。
- 用简体中文回答，简洁专业。`;

/** 发给 LLM 的完整工具集：内置（名字不变）+ MCP（若已连接） */
export async function getAgentTools(): Promise<LlmToolDef[]> {
  const tools = [...AGENT_TOOLS];
  try {
    const extra = await mcpLlmTools();
    for (const t of extra) {
      if (!tools.some((x) => x.function.name === t.function.name)) tools.push(t);
    }
  } catch (e) {
    // MCP 故障不得影响内置工具可用性
    console.warn(`[gateway] MCP 工具加载失败（已降级）：${e instanceof Error ? e.message : e}`);
  }
  return tools;
}

/** 统一执行入口：按命名空间分派 */
export async function executeAgentTool(
  name: string,
  args: Record<string, unknown>,
): Promise<{ ok: boolean; summary: string; data?: unknown }> {
  if (AGENT_TOOLS.some((t) => t.function.name === name)) {
    return executeTool(name, args);
  }
  if (name.startsWith("mcp_")) {
    return callMcpTool(name, args);
  }
  return { ok: false, summary: `未知工具：${name}` };
}

/**
 * 动态 system prompt（按 SKILL_ROUTER 分档）：
 * - llm（默认，OPT-1 路线 C）：元信息常驻 + 引导 load_skill；正文不注入，实际加载由 loader 在 done 事件汇报
 * - keyword/hybrid：元信息常驻 + 触发词命中注入正文（keyword 为原行为，hybrid 另开放工具补长尾）
 */
export function buildSystemPrompt(message: string): { prompt: string; activeSkills: string[] } {
  const all = loadSkills();
  const mode = skillRouterMode();
  if (mode === "llm") {
    return { prompt: `${BASE_SYSTEM_PROMPT}${skillsMetaPrompt(all, mode)}`, activeSkills: [] };
  }
  // B1：只选一次，结果同时用于 meta 与正文注入（此前重复触发词匹配 ×2）
  const matched = selectSkills(message, all);
  const prompt = `${BASE_SYSTEM_PROMPT}${skillsMetaPrompt(all, mode)}${skillsBodyPrompt(message, all, matched)}`;
  return { prompt, activeSkills: matched.map((s) => s.name) };
}

/** /api/tools/status 数据源（connect=true 时探测 MCP 连接，如实反映可用性/降级） */
/** 状态面板缓存（代码审查修复）：探测式 connect 可能 spawn MCP 子进程，
 *  高频轮询既慢又有副作用 → 30 秒内复用同一结果。
 *  C17（2026-09-14 code review 修复）：跨请求单例挂 globalThis——dev HMR 会重建
 *  模块作用域，模块级变量随之清空 → 缓存失效、下次轮询重复探测。 */
type StatusData = Awaited<ReturnType<typeof buildStatus>>;
/** CR-15：按 connect 分键缓存（plain=未探测 / connect=已探测） */
type StatusCacheMap = Partial<Record<"plain" | "connect", { at: number; data: StatusData }>>;
const STATUS_CACHE_KEY = Symbol.for("invest-manager.gateway.statusCache");
const statusCacheBox: { current: StatusCacheMap | null } = ((
  globalThis as unknown as Record<symbol, { current: StatusCacheMap | null } | undefined>
)[STATUS_CACHE_KEY] ??= { current: null });
const STATUS_TTL_MS = 30_000;

async function buildStatus(opts: { connect?: boolean }) {
  const names = AGENT_TOOLS.map((t) => t.function.name);
  const mcp = await mcpStatus({ connect: opts.connect });
  const skills = skillsStatus();
  return {
    namespaces: {
      builtin: { count: names.length, tools: names },
      skill: {
        count: skills.skills.length,
        router: skills.router,
        skills: skills.skills.map((s) => s.name),
        maxActive: skills.maxActive,
        maxBodyChars: skills.maxBodyChars,
      },
      mcp: {
        count: mcp.servers.reduce((acc, s) => acc + s.tools, 0),
        servers: mcp.servers,
      },
    },
  };
}

export async function gatewayStatus(opts: { connect?: boolean } = {}) {
  const now = Date.now();
  // CR-15（本轮 code review）：缓存按 connect 分键——此前只有单一缓存槽，
  // 首次 connect:false 探测会把"未探测（idle）"的结果污染后续 connect:true 的
  // 30s 窗口（当前唯一调用方传 true，影响有限，但语义上应隔离）。
  const slot = opts.connect ? "connect" : "plain";
  const cached = statusCacheBox.current?.[slot];
  if (cached && now - cached.at < STATUS_TTL_MS) {
    return cached.data;
  }
  const data = await buildStatus(opts);
  statusCacheBox.current = { ...(statusCacheBox.current ?? {}), [slot]: { at: now, data } };
  return data;
}
