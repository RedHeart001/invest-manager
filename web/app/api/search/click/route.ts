import { NextRequest, NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";

// 记录搜索点击（进入排序加权的历史点击率信号）
export async function POST(req: NextRequest) {
  let body: { query?: string; type?: string; code?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }
  const { query, type, code } = body;
  if (!query || !type || !code) {
    return NextResponse.json(
      { error: "query/type/code are required" },
      { status: 400 },
    );
  }
  await prisma.searchClickLog.create({ data: { query, type, code } });
  return NextResponse.json({ ok: true });
}
