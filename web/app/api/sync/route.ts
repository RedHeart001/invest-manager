import { NextRequest, NextResponse } from "next/server";

import { SYNC_TYPES, syncAll, syncType } from "@/lib/sync";
import { checkRequestOrigin } from "@/lib/request-origin";
import { requireWriteToken } from "@/lib/guard";

// CR-07（本轮 code review）：显式声明 maxDuration。
// C3-①（CR7-9，2026-09-25）：C0 实测全 5 类型 9.6min（部分源失败日）~13min
// （全成功日上限估算）→ 800s（13.3min）余量不足，上调至 1500s（25min）。
// 刀 3/甲-1（2026-10-02）之后刷新已移交给 `POST /api/market/refresh?type=all`，
// 本端点只剩"取列表＋落库＋重建 FTS"。
// 11-12 美股乙：us 列表全量（上限 950 页、早停按实盘）名义 ≈950s，加其余五类（10-17 基线
// ≈540s＋stock 修复后 324s）⇒ 整轮名义 ≈1506s、最坏（各类都撞重试）≈2086s ⇒ 上调至 2400s（40min）。
// 自托管下 maxDuration 为声明性（无 serverless 强制），仍小于 ds 侧 SCHEDULED 回调预算
// 2500s，维持"web 先结束、ds 不把已成功的同步误记为失败"的口径。
export const maxDuration = 2400;

// 触发产品主数据同步（P3 起由 data-service 定时调度调用本接口）
export async function POST(req: NextRequest) {
  // CR-08：拒绝浏览器跨站简单表单触发
  const blocked = checkRequestOrigin(req);
  if (blocked) {
    return NextResponse.json({ error: blocked }, { status: 403 });
  }
  // G7 最小版：WRITE_TOKEN 未设时放行（本机默认态），设了才校验（见 lib/guard.ts）
  const unauthorized = requireWriteToken(req);
  if (unauthorized) {
    return NextResponse.json({ error: unauthorized }, { status: 401 });
  }
  const type = req.nextUrl.searchParams.get("type");
  if (type && !SYNC_TYPES.includes(type as (typeof SYNC_TYPES)[number])) {
    return NextResponse.json(
      { error: `unsupported type: ${type}` },
      { status: 400 },
    );
  }
  const started = Date.now();
  // #23 当日幂等闸门（主人 10-02 拍板"两道叠加"）：某类今日已成功落过列表 ⇒ 该类本轮
  // 零出网、零写库，结果里带 `skipped:true`（**不是** error，所以 `ok` 仍为真）。
  // 出口 `?force=1` 给"我今天就是要重跑一遍"（手测前刷数据、以及 ds 侧的透传）。
  const force = req.nextUrl.searchParams.get("force") === "1";
  const results = type ? [await syncType(type, { force })] : await syncAll(SYNC_TYPES, { force });
  return NextResponse.json({
    tookMs: Date.now() - started,
    results,
    ok: results.every((r) => !r.error),
  });
}
