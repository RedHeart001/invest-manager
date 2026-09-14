import { describe, expect, it, beforeEach } from "vitest";

import { trimContext } from "./context-budget";
import type { LlmMessage } from "./llm";

function msg(role: LlmMessage["role"], content: string, extra?: Partial<LlmMessage>): LlmMessage {
  return { role, content, ...extra };
}

describe("trimContext（聊天上下文预算裁剪）", () => {
  beforeEach(() => {
    process.env.CHAT_CONTEXT_BUDGET = "24000";
  });

  it("未超预算：原样返回", () => {
    const messages: LlmMessage[] = [
      msg("system", "SYS"),
      msg("user", "你好"),
      msg("assistant", "你好，有什么可以帮你？"),
    ];
    expect(trimContext(messages)).toEqual(messages);
  });

  it("溢出点落在最后一条 user 消息（提问自身超预算）→ 硬截断保留", () => {
    const messages: LlmMessage[] = [
      msg("system", "S"),
      msg("user", "问".repeat(30000)),
    ];
    const out = trimContext(messages);
    const users = out.filter((m) => m.role === "user");
    expect(users).toHaveLength(1);
    expect(users[0].content?.length ?? 0).toBeLessThan(30000);
  });

  it("溢出点落在 assistant/tool 尾部（多轮工具循环）→ 仍保留本轮提问与配对（回归修复）", () => {
    const messages: LlmMessage[] = [
      msg("system", "S".repeat(2000)),
      msg("user", "USER_QUESTION"),
      msg("assistant", "A".repeat(30000), {
        tool_calls: [{ id: "c1", type: "function", function: { name: "get_quote", arguments: "{}" } }],
      }),
      msg("tool", "T".repeat(3000), { tool_call_id: "c1", name: "get_quote" }),
    ];
    const out = trimContext(messages);
    // 本轮提问必须仍在（此前会整段丢弃 → 模型空答）
    expect(out.some((m) => m.role === "user" && m.content === "USER_QUESTION")).toBe(true);
    // tool 配对不得被切断
    const assistant = out.find((m) => m.role === "assistant");
    const tool = out.find((m) => m.role === "tool");
    expect(assistant?.tool_calls?.[0]?.id).toBe("c1");
    expect(tool?.tool_call_id).toBe("c1");
    // 超预算的单条消息被硬截断
    expect((assistant?.content ?? "").length).toBeLessThan(30000);
  });
});
