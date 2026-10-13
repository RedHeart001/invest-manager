import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { DataServiceError, dsGet } from "@/lib/data-service";
import { REALTIME_BUDGET_MS, type RealtimeResponse } from "@/lib/realtime";
import { checkSubject } from "@/lib/validate";

// CR9-92（OPT-3 第一批 1a）：详情页「当日实时行情条」的 BFF。
export const dynamic = "force-dynamic";

/**
 * 只做三件事：入参成对校验（非法码在出网之前 400，CR7-6/C5 口径）、把 `parts` 原样透给 ds
 * 那条"两个节奏"、预算按 §B 契约给（`REALTIME_BUDGET_MS` ≥ ds 串行跑腿的最坏 9s）。
 *
 * ds 的 400（没登记腿的类型／写了不存在的腿）保持 400 语义往回交，其余失败 502——
 * 这一条**不是**给浏览器看的接口，屏上那一块由 `RealtimeStrip` 自己按 R10 降级。
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const subject = checkSubject(sp.get("type"), sp.get("code"), "stock");
  if ("error" in subject) {
    return NextResponse.json({ error: subject.error }, { status: 400 });
  }
  const parts = sp.get("parts") ?? "price,intraday";
  try {
    const data = await dsGet<RealtimeResponse>(
      "/quote/realtime",
      { type: subject.type, code: subject.code, parts },
      REALTIME_BUDGET_MS,
    );
    return NextResponse.json(data);
  } catch (e) {
    const status = e instanceof DataServiceError && e.status === 400 ? 400 : 502;
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "realtime fetch failed" },
      { status },
    );
  }
}
