import { NextResponse } from "next/server";

import { dsGet } from "@/lib/data-service";

// 热点调度状态代理（M4：手动抓取异步化后，前端经此轮询进度）
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const data = await dsGet<Record<string, unknown>>("/hotspots/status", {}, 10_000);
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "hotspots status failed" },
      { status: 502 },
    );
  }
}
