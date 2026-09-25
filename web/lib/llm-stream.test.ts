import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// D1（CR7-11）：chatStream 三条语义此前只靠集成测试间接覆盖——
// ① SSE 尾帧 flush（最后一帧无换行结尾不得丢弃）
// ② tool_calls name 仅首片赋值（重复发全名不累加损坏）
// ③ 收尾统一产出 tool_calls（不依赖 finish_reason）
// ④ 未配置 → LlmNotConfiguredError（守卫先行）
// 用 mock fetch 构造受控 SSE 流，不触真实网络。

const mockFetch = vi.fn();

beforeEach(() => {
  process.env.LLM_API_KEY = "test-key";
  process.env.LLM_MODEL = "test-model";
  process.env.LLM_BASE_URL = "http://llm.test";
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  delete process.env.LLM_DEBUG;
});

/** 构造 SSE Response（chunks 为服务端依次发出的原始帧文本） */
function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  let sent = 0;
  return new Response(
    new ReadableStream<Uint8Array>({
      pull(controller) {
        if (sent < chunks.length) {
          controller.enqueue(encoder.encode(chunks[sent]));
          sent += 1;
        } else {
          controller.close();
        }
      },
    }),
    { status: 200 },
  );
}

async function collect(gen: AsyncGenerator<{ type: string; content?: string; toolCalls?: unknown[] }>) {
  const out: { type: string; content?: string; toolCalls?: unknown[] }[] = [];
  for await (const c of gen) out.push(c);
  return out;
}

describe("chatStream（D1：流式解析语义回归）", () => {
  it("① 尾帧无换行结尾：携带 delta 的最后一帧不被丢弃", async () => {
    mockFetch.mockResolvedValue(
      sseResponse([
        'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"，世界"}}]}', // 无 \n\n 结尾
      ]),
    );
    const { chatStream } = await import("./llm");
    const out = await collect(chatStream({ messages: [{ role: "user", content: "hi" }] }));
    const text = out.filter((c) => c.type === "delta").map((c) => c.content).join("");
    expect(text).toBe("你好，世界");
  });

  it("② tool_calls name 仅首片赋值：兼容端点重复发全名不损坏", async () => {
    mockFetch.mockResolvedValue(
      sseResponse([
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"get_quote"}}]}}]}\n\n',
        // 重复发全名（部分兼容端点行为）——若累加会变成 "get_quoteget_quote"
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"get_quote","arguments":"{\\"type\\""}}]}}]}\n\n',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":\\"stock\\"}"}}]}}]}\n\n',
        "data: [DONE]\n",
      ]),
    );
    const { chatStream } = await import("./llm");
    const out = await collect(chatStream({ messages: [{ role: "user", content: "q" }] }));
    const tc = out.find((c) => c.type === "tool_calls");
    expect(tc).toBeDefined();
    const calls = (tc!.toolCalls ?? []) as { function: { name: string; arguments: string } }[];
    expect(calls[0].function.name).toBe("get_quote");
    expect(JSON.parse(calls[0].function.arguments)).toEqual({ type: "stock" });
  });

  it("③ 无 finish_reason 帧也产出 tool_calls（只要累积到了）", async () => {
    mockFetch.mockResolvedValue(
      sseResponse([
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"x","function":{"name":"search_products","arguments":"{}"}}]}}]}\n\n',
        // 流直接结束，无 [DONE]、无 finish 帧（部分供应商行为）
      ]),
    );
    const { chatStream } = await import("./llm");
    const out = await collect(chatStream({ messages: [{ role: "user", content: "q" }] }));
    expect(out.some((c) => c.type === "tool_calls")).toBe(true);
  });

  it("④ 未配置 LLM → LlmNotConfiguredError（不触 fetch）", async () => {
    delete process.env.LLM_API_KEY;
    const { chatStream, LlmNotConfiguredError } = await import("./llm");
    await expect(async () => {
      for await (const _ of chatStream({ messages: [{ role: "user", content: "q" }] })) {
        // 不应产出
      }
    }).rejects.toThrow(LlmNotConfiguredError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("⑤ 非 JSON 心跳行被忽略，正常 delta 不受影响", async () => {
    mockFetch.mockResolvedValue(
      sseResponse([
        ": keep-alive\n\n",
        'data: not-json\n\n',
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
      ]),
    );
    const { chatStream } = await import("./llm");
    const out = await collect(chatStream({ messages: [{ role: "user", content: "q" }] }));
    expect(out.map((c) => c.content).join("")).toBe("ok");
  });
});
