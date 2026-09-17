import { NextRequest, NextResponse } from "next/server";

import { appendMessage, createSession, listSessions } from "@/lib/chat";
import { prisma } from "@/lib/prisma";

// 会话列表 / 新建会话
export async function GET() {
  return NextResponse.json({ sessions: await listSessions() });
}

export async function POST(req: NextRequest) {
  let title = "新会话";
  try {
    const body = (await req.json()) as { title?: string };
    if (body.title) title = String(body.title);
  } catch {
    // 无 body 也可
  }
  const s = await createSession(title);
  return NextResponse.json(s);
}

// 追加消息（供 UI 在流结束后兜底同步；正常流程由 /api/chat 内部持久化）
export async function PUT(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as {
    sessionId?: string;
    role?: "user" | "assistant" | "tool";
    content?: string;
  };
  if (!body.sessionId || !body.role || !body.content) {
    return NextResponse.json({ error: "sessionId/role/content required" }, { status: 400 });
  }
  // CR4（P3）：role 运行时白名单校验——此前只有 TS 类型标注，任意字符串可落库，
  // 该会话下次对话把非法 role 发给 LLM → 400。
  if (!["user", "assistant", "tool"].includes(body.role)) {
    return NextResponse.json({ error: "illegal role" }, { status: 400 });
  }
  // 代码审查修复：向不存在的会话写消息会触发外键错误 → 未捕获 500
  const exists = await prisma.chatSession.findUnique({
    where: { id: body.sessionId },
    select: { id: true },
  });
  if (!exists) {
    return NextResponse.json({ error: "session not found" }, { status: 404 });
  }
  await appendMessage(body.sessionId, body.role, body.content);
  return NextResponse.json({ ok: true });
}

export const dynamic = "force-dynamic";
