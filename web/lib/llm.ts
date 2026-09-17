// LLM 客户端（PLAN M4：OpenAI 兼容端点，适配 DeepSeek/GLM 等）
// - 流式解析（token 增量 + tool_calls 碎片累积）
// - 未配置时抛 LlmNotConfiguredError（路由层转 SSE 错误事件，页面给出明确指引）

export class LlmNotConfiguredError extends Error {
  constructor() {
    super(
      "LLM 未配置：请在 web/.env 设置 LLM_API_KEY / LLM_MODEL（可选 LLM_BASE_URL，DeepSeek/GLM 模型可自动推断）",
    );
    this.name = "LlmNotConfiguredError";
  }
}

export type LlmToolCall = {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
};

export type LlmMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  tool_calls?: LlmToolCall[];
  tool_call_id?: string;
  name?: string;
};

export type LlmToolDef = {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
};

export type LlmChunk =
  | { type: "delta"; content: string }
  | { type: "tool_calls"; toolCalls: LlmToolCall[] };

// CR4（2026-09-15 review）：LLM 流超时防护——首字节连接与读流空闲双看门狗，
// 防止上游"连接建立但停止吐字"时请求永久挂起占住连接（对话停在转圈）。
const CONNECT_TIMEOUT_MS = 60_000;
const IDLE_TIMEOUT_MS = 60_000;

export function llmConfig(): { base: string; key: string; model: string } | null {
  const key = process.env.LLM_API_KEY;
  const model = process.env.LLM_MODEL;
  if (!key || !model) return null;
  // LLM_BASE_URL 缺省时按模型名推断常见供应商（DeepSeek/GLM，PLAN 暂定选型）
  let base = process.env.LLM_BASE_URL;
  if (!base) {
    const m = model.toLowerCase();
    if (m.includes("deepseek")) base = "https://api.deepseek.com";
    else if (m.includes("glm")) base = "https://open.bigmodel.cn/api/paas/v4";
  }
  if (!base) return null;
  return { base: base.replace(/\/+$/, ""), key, model };
}

export function llmReady(): boolean {
  return llmConfig() !== null;
}

/**
 * 流式对话（function calling）。
 * yield 顺序：若干 {type:"delta"}（正文增量）→ 若模型要求工具，最后 yield 一次
 * {type:"tool_calls"}（已按 index 拼装完整）。无 tool_calls 则无第二个事件。
 */
export async function* chatStream(opts: {
  messages: LlmMessage[];
  tools?: LlmToolDef[];
  temperature?: number;
  signal?: AbortSignal;
}): AsyncGenerator<LlmChunk, void, unknown> {
  const cfg = llmConfig();
  if (!cfg) throw new LlmNotConfiguredError();

  const body: Record<string, unknown> = {
    model: cfg.model,
    messages: opts.messages,
    temperature: opts.temperature ?? 0.3,
    stream: true,
  };
  if (opts.tools && opts.tools.length > 0) {
    body.tools = opts.tools;
    body.tool_choice = "auto";
  }

  const t0 = Date.now();
  // CR4（2026-09-15 review）：首字节连接也设超时——上游"连接建立但一直不吐头"
  // 时原 fetch 只受 opts.signal（用户断开）约束，请求会永久挂起占连接。
  const connectSignals = [opts.signal, AbortSignal.timeout(CONNECT_TIMEOUT_MS)].filter(
    (s): s is AbortSignal => Boolean(s),
  );
  const res = await fetch(`${cfg.base}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${cfg.key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    // Next.js patched fetch 会缓冲 SSE 流（等待完整响应以判定缓存），
    // 必须 no-store 才能让流式 chunk 直通（P4 实测修复挂起问题）
    cache: "no-store",
    signal: connectSignals.length > 0 ? AbortSignal.any(connectSignals) : undefined,
  });
  // B3：默认静默；需要排查时设 LLM_DEBUG=1 再输出（此前每次请求无条件打印）
  if (process.env.LLM_DEBUG) {
    console.log(`[llm] fetch status=${res.status} in ${Date.now() - t0}ms (base=${cfg.base})`);
  }
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `LLM 请求失败（${res.status}）：url=${cfg.base}/chat/completions model=${cfg.model} body=${detail.slice(0, 150)}`,
    );
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finish: string | null = null;
  void finish; // 仅用于日志/诊断；工具调用的产出不再依赖它（见文件末尾说明）
  const toolAcc = new Map<number, { id: string; name: string; arguments: string }>();

  // 处理一行 SSE data 载荷（抽成闭包，供循环与收尾 flush 复用）
  const handleLine = (raw: string): LlmChunk | null => {
    const line = raw.trim();
    if (!line.startsWith("data:")) return null;
    const data = line.slice(5).trim();
    if (data === "[DONE]") return null;
    let parsed: {
      choices?: {
        delta?: {
          content?: string | null;
          tool_calls?: {
            index?: number;
            id?: string;
            function?: { name?: string; arguments?: string };
          }[];
        };
        finish_reason?: string | null;
      }[];
    };
    try {
      parsed = JSON.parse(data);
    } catch {
      return null; // 非 JSON 行（心跳等）
    }
    const choice = parsed.choices?.[0];
    if (!choice) return null;
    if (choice.finish_reason) finish = choice.finish_reason;
    const delta = choice.delta;
    if (!delta) return null;
    if (delta.tool_calls) {
      for (const tc of delta.tool_calls) {
        const i = tc.index ?? 0;
        const acc = toolAcc.get(i) ?? { id: "", name: "", arguments: "" };
        if (tc.id) acc.id = tc.id;
        // CR4：name 仅首片赋值（部分兼容端点重复发全名 → 累加损坏工具名）
        if (tc.function?.name && !acc.name) acc.name = tc.function.name;
        if (tc.function?.arguments) acc.arguments += tc.function.arguments;
        toolAcc.set(i, acc);
      }
    }
    return delta.content ? { type: "delta", content: delta.content } : null;
  };

  const takeLine = (): string | null => {
    const idx = buffer.indexOf("\n");
    if (idx < 0) return null;
    const line = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 1);
    return line;
  };

  // CR4：读流空闲看门狗——每个 chunk 必须在 IDLE_TIMEOUT_MS 内到达，否则中止。
  let idleTimer: NodeJS.Timeout | null = null;
  const withIdle = <T>(p: Promise<T>): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      idleTimer = setTimeout(
        () => reject(new Error(`LLM 流空闲超时（>${IDLE_TIMEOUT_MS}ms 无数据）`)),
        IDLE_TIMEOUT_MS,
      );
      p.then(
        (v) => {
          if (idleTimer) {
            clearTimeout(idleTimer);
            idleTimer = null;
          }
          resolve(v);
        },
        (e) => {
          if (idleTimer) {
            clearTimeout(idleTimer);
            idleTimer = null;
          }
          reject(e);
        },
      );
    });

  try {
    while (true) {
      const { value, done } = await withIdle(reader.read());
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let raw: string | null;
      while ((raw = takeLine()) !== null) {
        const chunk = handleLine(raw);
        if (chunk) yield chunk;
      }
    }
  } finally {
    if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
  }

  // 收尾 flush（代码审查修复）：最后一帧常常**没有换行结尾**，此前直接被丢弃；
  // 若该帧恰好携带 finish_reason / tool_calls 分片，就会导致工具调用静默失效
  // （用户只看到空回复）。此处补处理残留 buffer。
  if (buffer.trim()) {
    const chunk = handleLine(buffer);
    if (chunk) yield chunk;
    buffer = "";
  }

  // 只要累积到工具调用就产出，不再强依赖 finish 值（部分供应商收尾帧缺失或不为
  // "tool_calls"）；finish="length" 属输出被截断，可用于告警但不应吞掉工具调用。
  if (toolAcc.size > 0) {
    const toolCalls = [...toolAcc.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([, v]) => ({
        id: v.id || `call_${v.name}_${Date.now()}`,
        type: "function" as const,
        function: { name: v.name, arguments: v.arguments || "{}" },
      }))
      .filter((c) => c.function.name.length > 0);
    if (toolCalls.length > 0) {
      yield { type: "tool_calls", toolCalls };
    }
  }
}
