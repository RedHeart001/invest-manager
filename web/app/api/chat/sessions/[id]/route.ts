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
  // CR-15（本轮 code review）：区分"会话不存在"（P2025）与真实 DB 故障——
  // 此前任何异常都吞成 404，掩盖了数据库错误。
  try {
    await deleteSession(id);
    return NextResponse.json({ ok: true });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { code?: string }).code === "P2025") {
      return NextResponse.json({ error: "session not found" }, { status: 404 });
    }
    console.error("[sessions] delete failed:", e instanceof Error ? e.message : e);
    return NextResponse.json({ error: "delete failed" }, { status: 500 });
  }
}

export const dynamic = "force-dynamic";
