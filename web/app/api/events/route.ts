import { NextRequest, NextResponse } from "next/server";

import { fetchEvents } from "@/lib/events";

// 事件标注（R11 轻量归因）：股票走东财新闻，其余类型返回缺口说明
export async function GET(req: NextRequest) {
  const type = req.nextUrl.searchParams.get("type") ?? "stock";
  const code = req.nextUrl.searchParams.get("code");
  if (!code) {
    return NextResponse.json({ error: "code is required" }, { status: 400 });
  }
  const result = await fetchEvents(type, code);
  return NextResponse.json(result);
}
