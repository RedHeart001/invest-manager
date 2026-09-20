// 会话历史 tool 配对修复（CR-01，本轮 code review）
//
// 背景：`getMessages` 取"最近 200 条"，窗口头部可能截断出**孤立 tool 消息**
// （其 assistant(tool_calls) 已被切掉）；`safeAppend` 单条失败也可能留下
// assistant(tool_calls) 无对应 tool 结果，或 tool 结果缺 `tool_call_id`。
// OpenAI 兼容端点（DeepSeek/GLM）对这类历史一律 400：
//   - tool message must be a response to a preceding message with tool_calls
//   - assistant message with tool_calls must be followed by tool messages
// 使该会话此后**每次提问都失败，用户无法自愈**（只能删会话）。
//
// 本模块是**零依赖纯函数**（便于单测），只做配对修复：
//   1) 丢弃孤立 tool 消息（无前置 assistant 声明，或缺 toolCallId）
//   2) 把 assistant.tool_calls 收窄到"确有 tool 结果回应"的子集；
//      若一条都没有，则剥离 tool_calls（仅保留文本，避免"声明了却没回应"同样被拒）

export type HistoryMessageLike = {
  role: string;
  content: string;
  toolCalls?: unknown;
  toolCallId?: string;
  name?: string;
};

/** 从 assistant.toolCalls（未解析类型）中提取非空 id 列表 */
function callIds(toolCalls: unknown): string[] {
  if (!Array.isArray(toolCalls)) return [];
  const ids: string[] = [];
  for (const c of toolCalls) {
    const id = (c as { id?: unknown } | null)?.id;
    if (typeof id === "string" && id) ids.push(id);
  }
  return ids;
}

/** 返回去掉 toolCalls 字段的副本 */
function withoutToolCalls<T extends HistoryMessageLike>(m: T): T {
  const { toolCalls, ...rest } = m as T & { toolCalls?: unknown };
  void toolCalls;
  return rest as T;
}

/**
 * 修复 tool 配对，返回可安全发给 LLM 的消息序列。
 * 顺序与不相关消息保持原样；只移除/收窄无法配对的部分。
 */
export function repairToolPairing<T extends HistoryMessageLike>(messages: T[]): T[] {
  const out: T[] = [];
  let i = 0;
  while (i < messages.length) {
    const m = messages[i];

    if (m.role === "assistant") {
      const ids = callIds(m.toolCalls);
      if (ids.length === 0) {
        // 无 tool_calls（或声明缺 id）：确保不带 tool_calls
        out.push(m.toolCalls ? withoutToolCalls(m) : m);
        i += 1;
        continue;
      }
      // 收集紧随其后的 tool 消息
      let j = i + 1;
      const tools: T[] = [];
      while (j < messages.length && messages[j].role === "tool") {
        tools.push(messages[j]);
        j += 1;
      }
      // 只保留 id 属于本 assistant 声明、且每条 id 只取首次回应的 tool 消息
      const seen = new Set<string>();
      const kept: T[] = [];
      for (const t of tools) {
        const id = t.toolCallId;
        if (id && ids.includes(id) && !seen.has(id)) {
          seen.add(id);
          kept.push(t);
        }
      }
      if (kept.length === ids.length) {
        // 全部被回应：原样保留
        out.push(m);
        out.push(...kept);
      } else if (kept.length > 0) {
        // 部分回应：把 tool_calls 收窄到已回应的子集，保持双向一致
        const answered = new Set(kept.map((t) => t.toolCallId));
        const filteredCalls = (m.toolCalls as { id?: string }[]).filter(
          (c) => c && typeof c.id === "string" && answered.has(c.id),
        );
        out.push({ ...m, toolCalls: filteredCalls } as T);
        out.push(...kept);
      } else {
        // 无任何回应：剥离 tool_calls（有文本则保留文本，否则整条丢弃）
        const stripped = withoutToolCalls(m);
        if (stripped.content) out.push(stripped);
      }
      i = j;
      continue;
    }

    if (m.role === "tool") {
      // 能到达此处说明没有前置 assistant（否则已被上面消费）→ 孤立，丢弃
      i += 1;
      continue;
    }

    // user / system 等
    out.push(m);
    i += 1;
  }
  return out;
}
