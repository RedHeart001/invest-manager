// 聊天上下文预算（M1/O1）：按字符预算裁剪历史，防止长会话撑爆 LLM 上下文
// 约束：不切断 tool_calls ↔ tool 结果的配对（成对裁掉整轮）

import type { LlmMessage } from "./llm";

/** 上下文字符预算（可经 CHAT_CONTEXT_BUDGET 覆盖） */
export function contextBudget(): number {
  const v = Number(process.env.CHAT_CONTEXT_BUDGET);
  return Number.isFinite(v) && v > 0 ? v : 24_000;
}

function msgSize(m: LlmMessage): number {
  const base = m.content?.length ?? 0;
  const tools = (m.tool_calls ?? []).reduce(
    (acc, c) => acc + c.function.name.length + c.function.arguments.length,
    0,
  );
  return base + tools;
}

/** 单条消息超预算时的硬截断（保留前 60% 或至少 500 字符） */
function truncateContent(content: string | null | undefined, budget: number): string {
  const text = content ?? "";
  const keep = Math.max(500, Math.floor(budget * 0.6));
  if (text.length <= keep) return text;
  return `${text.slice(0, keep)}\n\n（本条内容过长，已截断）`;
}

/**
 * CR4（P3）：单条消息压缩——content 之外，tool_calls.arguments（大段 JSON）也可能
 * 是体积大头，此前只截 content 截不动。仅在整条超预算时调用（末路兜底）。
 */
function shrinkMessage(m: LlmMessage, budget: number): LlmMessage {
  if (msgSize(m) <= budget) return m;
  const content = truncateContent(m.content, budget);
  let toolCalls = m.tool_calls;
  if (toolCalls && toolCalls.length > 0) {
    const perCall = Math.max(200, Math.floor(budget / (toolCalls.length * 2)));
    toolCalls = toolCalls.map((c) => ({
      ...c,
      function: {
        ...c.function,
        arguments:
          c.function.arguments.length > perCall
            ? `${c.function.arguments.slice(0, perCall)}…（参数过长已截断）`
            : c.function.arguments,
      },
    }));
  }
  return { ...m, content, tool_calls: toolCalls };
}

/**
 * 裁剪消息序列到字符预算内：
 * - system 提示（首条）始终保留
 * - 溢出时从**最早的整轮**开始丢弃（轮以 user 消息为界），保证 tool 配对完整
 * - 预算内无法容纳任何一轮时，至少保留最后一轮并在 system 尾部标注省略
 */
export function trimContext(messages: LlmMessage[]): LlmMessage[] {
  const budget = contextBudget();
  const hasSystem = messages[0]?.role === "system";
  const system = hasSystem ? messages[0] : null;
  const rest = hasSystem ? messages.slice(1) : messages;

  // CR4（P3）：system 也计入预算——此前只累计 rest，而 system（base prompt +
  // ≤3 技能正文 ≈ 8K）在预算之外，实际峰值超 CHAT_CONTEXT_BUDGET 约 1/3。
  let total = system ? msgSize(system) : 0;
  let overflow = false;
  for (let i = rest.length - 1; i >= 0; i--) {
    total += msgSize(rest[i]);
    if (total > budget) {
      overflow = true;
      // 溢出发生在 i：从 i 之后第一个 user 消息开始保留（不切断轮内配对）
      let j = i + 1;
      while (j < rest.length && rest[j].role !== "user") j++;
      // 通用兜底（2026-09-14 code review 修复）：若溢出点**之后没有任何 user 消息**
      // （多轮工具循环里末尾常是 assistant/tool 对，route.ts 的 roundText 无长度上限），
      // 原实现会 kept=[] → 整段对话被丢弃、本轮提问消失、模型空答。
      // 正确做法：保留**包含溢出点的那一整轮**（从最近的 user 消息起），
      // 并对仍超预算的单条消息硬截断，保证提问可见且 tool 配对不断。
      if (j >= rest.length) {
        let u = i;
        while (u >= 0 && rest[u].role !== "user") u--;
        const start = u >= 0 ? u : i;
        const kept = rest.slice(start).map((m) => shrinkMessage(m, budget));
        if (!system) return kept;
        return [
          { ...system, content: `${system.content}\n\n（更早的对话历史已因长度限制省略）` },
          ...kept,
        ];
      }
      const kept = rest.slice(Math.min(j, rest.length));
      if (!system) return kept;
      return [
        { ...system, content: `${system.content}\n\n（更早的对话历史已因长度限制省略）` },
        ...kept,
      ];
    }
  }

  // 未超预算：原样返回
  void overflow;
  return messages;
}
