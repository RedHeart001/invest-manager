import { NextRequest, NextResponse } from "next/server";

import { SYNC_TYPES, syncAll, syncType } from "@/lib/sync";
import { checkRequestOrigin } from "@/lib/request-origin";

// CR-07（本轮 code review）：显式声明 maxDuration。
// C3-①（CR7-9，2026-09-25）：C0 实测全 5 类型 9.6min（部分源失败日）~13min
// （全成功日上限估算）→ 800s（13.3min）余量不足，上调至 1500s（25min）；
// 自托管下 maxDuration 为声明性（无 serverless 强制），但与 ds 侧 timeout=1800
// 保持"web 先结束、ds 不把已成功的同步误记为失败"的口径。
// ⚠️ 1500 这个数是**拆腿之前**的形态（当时本端点末尾还跑一份全类型快照刷新，10-01 实测
// 那一段单独 ≈1,700s）。刀 3/甲-1（2026-10-02）之后刷新已移交给
// `POST /api/market/refresh?type=all`，本端点只剩"取列表＋落库＋重建 FTS"⇒ 1500 现在是
// 一个**明显偏大但无害**的声明。**没有跟着调小**：调它需要一个真实的"纯列表 wall"样本，
// 而 10-01 那次 5 类里 3 类秒败、列表只占头一分钟，不构成定数依据（CR7-9 的教训就是
// 不要按注释 tuning）。ds 侧同步腿预算同理（见 `sync_scheduler.SCHEDULED_CALLBACK_TIMEOUT_S`）。
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
