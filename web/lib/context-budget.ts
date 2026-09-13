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
      //
      // 修复（2026-09-13 code review）：若溢出点落在**最后一条消息**（即本轮用户提问
      // 自身超出预算），j 会直达 rest.length，kept=[] → 用户提问被整条丢弃、模型空答。
      // 此时退化为"至少保留 i 起的一条并硬截断"，保证本轮提问始终可见。
      let j = i + 1;
      while (j < rest.length && rest[j].role !== "user") j++;
      if (j >= rest.length && i >= 0 && rest[i].role === "user") {
        const only = rest[i];
        const truncated = {
          ...only,
          content: truncateContent(only.content, budget),
        };
        if (!system) return [truncated];
        return [
          { ...system, content: `${system.content}\n\n（更早的对话历史已因长度限制省略）` },
          truncated,
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
