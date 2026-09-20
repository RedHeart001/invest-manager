// 会话持久化（PLAN M4：ChatSession / ChatMessage，P0 已建表）

import { prisma } from "./prisma";

export type StoredMessage = {
  role: "user" | "assistant" | "tool";
  content: string;
  toolCalls?: unknown; // 原始 tool_calls JSON（assistant）
  toolCallId?: string; // tool 角色对应的服务端工具结果 id
  name?: string; // tool 角色的工具名
  createdAt: string;
};

export async function createSession(title: string): Promise<{ id: string; title: string }> {
  const s = await prisma.chatSession.create({ data: { title: title.slice(0, 60) } });
  return { id: s.id, title: s.title ?? s.id };
}

export async function listSessions(limit = 30): Promise<
  { id: string; title: string; createdAt: string; messageCount: number }[]
> {
  const sessions = await prisma.chatSession.findMany({
    orderBy: { createdAt: "desc" },
    take: limit,
    include: { _count: { select: { messages: true } } },
  });
  return sessions.map((s) => ({
    id: s.id,
    title: s.title ?? "新会话",
    createdAt: s.createdAt.toISOString(),
    messageCount: s._count.messages,
  }));
}

export async function appendMessage(
  sessionId: string,
  role: "user" | "assistant" | "tool",
  content: string,
  extra?: { toolCalls?: unknown; toolCallId?: string; name?: string },
): Promise<void> {
  await prisma.chatMessage.create({
    data: {
      sessionId,
      role,
      content,
      toolCalls: extra?.toolCalls != null ? JSON.stringify(extra.toolCalls) : null,
      toolCallId: extra?.toolCallId ?? null,
      name: extra?.name ?? null,
    },
  });
}

export async function getMessages(sessionId: string): Promise<StoredMessage[]> {
  // 取**最近** 200 条（代码审查修复）：此前 orderBy asc + take 200 拿到的是最早
  // 200 条，长会话会让 LLM 丢失最新上下文且用户无感知。故倒序取再反转为时间序。
  // CR6-P2-6：改用真实 createdAt 排序（此前用 cuid 主键代理，极端并发下可能错序）。
  const rows = await prisma.chatMessage.findMany({
    where: { sessionId },
    orderBy: [{ createdAt: "desc" }, { id: "desc" }],
    take: 200,
  });
  rows.reverse();
  return rows.map((r) => ({
    role: r.role as StoredMessage["role"],
    content: r.content,
    toolCalls: r.toolCalls ? safeJson(r.toolCalls) : undefined,
    toolCallId: r.toolCallId ?? undefined,
    name: r.name ?? undefined,
    createdAt: r.createdAt.toISOString(),
  }));
}

export async function deleteSession(id: string): Promise<void> {
  await prisma.chatSession.delete({ where: { id } });
}

function safeJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}
