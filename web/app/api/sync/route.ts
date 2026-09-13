import { NextRequest, NextResponse } from "next/server";

import { SYNC_TYPES, syncAll, syncType } from "@/lib/sync";

// 触发产品主数据同步（P3 起由 data-service 定时调度调用本接口）
export async function POST(req: NextRequest) {
  const type = req.nextUrl.searchParams.get("type");
  if (type && !SYNC_TYPES.includes(type as (typeof SYNC_TYPES)[number])) {
    return NextResponse.json(
      { error: `unsupported type: ${type}` },
      { status: 400 },
    );
  }
  const started = Date.now();
  const results = type ? [await syncType(type)] : await syncAll();
  return NextResponse.json({
    tookMs: Date.now() - started,
    results,
    ok: results.every((r) => !r.error),
  });
}
