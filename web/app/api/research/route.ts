import { NextRequest, NextResponse } from "next/server";

import { getLatestReport } from "@/lib/research";

// 查询最近研报（详情页轮询 / L2 工具 get_research_report 的后端）
export async function GET(req: NextRequest) {
  const type = req.nextUrl.searchParams.get("type") ?? "stock";
  const code = req.nextUrl.searchParams.get("code") ?? "";
  if (!code) {
    return NextResponse.json({ error: "code is required" }, { status: 400 });
  }
  const row = await getLatestReport(type, code);
  if (!row) {
    return NextResponse.json({ status: "none" });
  }
  return NextResponse.json(row);
}

export const dynamic = "force-dynamic";
