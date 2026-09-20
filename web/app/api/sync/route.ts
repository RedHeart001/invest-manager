import { NextRequest, NextResponse } from "next/server";

import { SYNC_TYPES, syncAll, syncType } from "@/lib/sync";
import { checkRequestOrigin } from "@/lib/request-origin";

// CR-07（本轮 code review）：全量同步含外部取数 + 快照刷新，单类型可达数分钟、
// 四类型串行可达 20+ 分钟，此前未声明 maxDuration（与 /api/hotspots/run 口径不一致）。
export const maxDuration = 800;

// 触发产品主数据同步（P3 起由 data-service 定时调度调用本接口）
export async function POST(req: NextRequest) {
  // CR-08：拒绝浏览器跨站简单表单触发
  const blocked = checkRequestOrigin(req);
  if (blocked) {
    return NextResponse.json({ error: blocked }, { status: 403 });
  }
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
