import { NextRequest, NextResponse } from "next/server";

import { listDigests } from "@/lib/hotspots";

// 热点列表（Dashboard 手动刷新 / 客户端重连后补齐）
export async function GET(req: NextRequest) {
  const date = req.nextUrl.searchParams.get("date");
  const limitParam = Number(req.nextUrl.searchParams.get("limit") ?? "30");
  const limit = Number.isFinite(limitParam) ? limitParam : 30;
  try {
    const data = await listDigests({ date, limit });
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "list failed" },
      { status: 500 },
    );
  }
}
