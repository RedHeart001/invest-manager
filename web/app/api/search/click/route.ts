import { NextRequest, NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";
import { checkRequestOrigin } from "@/lib/request-origin";

// 记录搜索点击（进入排序加权的历史点击率信号）
export async function POST(req: NextRequest) {
  // CR10-12：这一发往 `SearchClickLog` 写一行、且那行就是排序加权的历史点击信号，
  // 外站可用 `sendBeacon`（简单请求，不预检）无界插入 ⇒ 挡在任何一次读 body 之前。
  const blocked = checkRequestOrigin(req);
  if (blocked) {
    return NextResponse.json({ error: blocked }, { status: 403 });
  }
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
  // CR5-P3（2026-09-17 review）：入参长度上限，避免无界写入
  await prisma.searchClickLog.create({
    data: { query: String(query).slice(0, 200), type: String(type).slice(0, 20), code: String(code).slice(0, 30) },
  });
  return NextResponse.json({ ok: true });
}
