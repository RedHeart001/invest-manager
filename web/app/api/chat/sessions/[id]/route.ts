import { NextRequest, NextResponse } from "next/server";

import { deleteSession, getMessages } from "@/lib/chat";
import { prisma } from "@/lib/prisma";

// 单会话：GET 消息历史 / DELETE 删除会话（级联删消息）
export async function GET(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  const session = await prisma.chatSession.findUnique({ where: { id } });
  if (!session) {
    return NextResponse.json({ error: "session not found" }, { status: 404 });
  }
  return NextResponse.json({
    id: session.id,
    title: session.title ?? "新会话",
    createdAt: session.createdAt.toISOString(),
    messages: await getMessages(id),
  });
}

export async function DELETE(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const { id } = await ctx.params;
  try {
    await deleteSession(id);
    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ error: "session not found" }, { status: 404 });
  }
}

export const dynamic = "force-dynamic";
