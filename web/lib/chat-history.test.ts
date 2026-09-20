import { describe, expect, it } from "vitest";

import { repairToolPairing, type HistoryMessageLike } from "./chat-history";

// CR-01：会话历史 tool 配对修复。历史可能因"取最近 200 条"窗口切割或
// safeAppend 单条失败而出现孤立 tool 消息 / tool_calls 无回应，
// OpenAI 兼容端点会一律 400 且该会话此后不可用。

function m(role: string, content: string, extra?: Partial<HistoryMessageLike>): HistoryMessageLike {
  return { role, content, ...extra };
}

const callA = { id: "a", type: "function", function: { name: "get_quote", arguments: "{}" } };
const callB = { id: "b", type: "function", function: { name: "get_kline", arguments: "{}" } };

describe("repairToolPairing（CR-01）", () => {
  it("完整配对：原样保留", () => {
    const input = [
      m("user", "茅台多少钱"),
      m("assistant", "", { toolCalls: [callA] }),
      m("tool", "{\"price\":1}", { toolCallId: "a", name: "get_quote" }),
    ];
    expect(repairToolPairing(input)).toEqual(input);
  });

  it("窗口首条为孤立 tool（其 assistant 已被切掉）→ 丢弃", () => {
    const input = [
      m("tool", "orphan", { toolCallId: "zzz", name: "get_quote" }),
      m("user", "继续"),
    ];
    const out = repairToolPairing(input);
    expect(out.some((x) => x.role === "tool")).toBe(false);
    expect(out.map((x) => x.role)).toEqual(["user"]);
  });

  it("tool 消息缺 toolCallId → 丢弃（不再退化为常量 call）", () => {
    const input = [
      m("assistant", "", { toolCalls: [callA] }),
      m("tool", "no-id", { name: "get_quote" }),
    ];
    const out = repairToolPairing(input);
    // 无任何回应 → 剥离 tool_calls（无文本则整条丢弃）
    expect(out.find((x) => x.role === "assistant")?.toolCalls).toBeUndefined();
    expect(out.some((x) => x.role === "tool")).toBe(false);
  });

  it("assistant 声明两个 tool_calls 但只回应一个 → 收窄 tool_calls", () => {
    const input = [
      m("assistant", "查一下", { toolCalls: [callA, callB] }),
      m("tool", "{\"price\":1}", { toolCallId: "a", name: "get_quote" }),
    ];
    const out = repairToolPairing(input);
    const assistant = out.find((x) => x.role === "assistant");
    expect((assistant?.toolCalls as { id: string }[]).map((c) => c.id)).toEqual(["a"]);
    expect(out.filter((x) => x.role === "tool")).toHaveLength(1);
  });

  it("assistant 有 tool_calls 但无任何回应且有文本 → 剥离 tool_calls 保留文本", () => {
    const input = [m("assistant", "我先看看", { toolCalls: [callA] })];
    const out = repairToolPairing(input);
    expect(out).toHaveLength(1);
    expect(out[0].toolCalls).toBeUndefined();
    expect(out[0].content).toBe("我先看看");
  });

  it("assistant 有 tool_calls 无回应且无文本 → 整条丢弃", () => {
    const input = [m("assistant", "", { toolCalls: [callA] })];
    expect(repairToolPairing(input)).toHaveLength(0);
  });

  it("重复回应同一 id → 只保留首次", () => {
    const input = [
      m("assistant", "", { toolCalls: [callA] }),
      m("tool", "first", { toolCallId: "a" }),
      m("tool", "second", { toolCallId: "a" }),
    ];
    const out = repairToolPairing(input);
    expect(out.filter((x) => x.role === "tool")).toHaveLength(1);
  });

  it("多轮工具循环混合：配对正常的两轮不受影响", () => {
    const input = [
      m("user", "q1"),
      m("assistant", "", { toolCalls: [callA] }),
      m("tool", "r1", { toolCallId: "a" }),
      m("assistant", "answer1"),
      m("user", "q2"),
      m("assistant", "", { toolCalls: [callB] }),
      m("tool", "r2", { toolCallId: "b" }),
    ];
    const out = repairToolPairing(input);
    expect(out).toEqual(input);
  });

  it("空输入 → 空输出", () => {
    expect(repairToolPairing([])).toEqual([]);
  });
});
