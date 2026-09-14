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

  let total = 0;
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
        const kept = rest.slice(start).map((m) =>
          msgSize(m) <= budget ? m : { ...m, content: truncateContent(m.content, budget) },
        );
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
