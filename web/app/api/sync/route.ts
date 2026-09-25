import { NextRequest, NextResponse } from "next/server";

import { SYNC_TYPES, syncAll, syncType } from "@/lib/sync";
import { checkRequestOrigin } from "@/lib/request-origin";

// CR-07（本轮 code review）：全量同步含外部取数 + 快照刷新，单类型可达数分钟、
// 四类型串行可达 20+ 分钟，此前未声明 maxDuration（与 /api/hotspots/run 口径不一致）。
// C3-①（CR7-9，2026-09-25）：C0 实测全 5 类型 9.6min（部分源失败日）~13min
// （全成功日上限估算）→ 800s（13.3min）余量不足，上调至 1500s（25min）；
// 自托管下 maxDuration 为声明性（无 serverless 强制），但与 ds 侧 timeout=1800
// 保持"web 先超时于 ds"的口径，避免 ds 侧把成功误记失败。
export const maxDuration = 1500;

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
