import { NextRequest, NextResponse } from "next/server";

import { DataServiceError } from "@/lib/data-service";
import { getKlineRange, normalizeRange } from "@/lib/kline";
import { CODE_SET, QUOTE_TYPES } from "@/lib/validate";

// 日 K（增量缓存）/ 当日分钟线（透传）：
// 浏览器 → /api/kline → KlineDaily（miss 回源 data-service → upsert）
export async function GET(req: NextRequest) {
  const type = req.nextUrl.searchParams.get("type") ?? "stock";
  const code = req.nextUrl.searchParams.get("code");
  const interval = req.nextUrl.searchParams.get("interval") ?? "1d";
  // CR7-6/C5（2026-09-25）：code/type 白名单前移——此前只判非空，任意串都会
  // 直传 ds 消耗一发东财令牌（rate_per_min=12），页面内 <img>/no-cors GET 即可
  // 被利用刷额度（R15）。与 research/start、watchlist、quote/verify 同口径。
  if (!QUOTE_TYPES.includes(type as (typeof QUOTE_TYPES)[number])) {
    return NextResponse.json({ error: `unsupported type: ${type}` }, { status: 400 });
  }
  if (!code || !CODE_SET.test(code)) {
    return NextResponse.json({ error: "invalid code" }, { status: 400 });
  }
  if (!["1d", "1m"].includes(interval)) {
    return NextResponse.json({ error: "interval must be 1d or 1m" }, { status: 400 });
  }

  let start = "";
  let end = "";
  if (interval === "1d") {
    const range = normalizeRange(
      req.nextUrl.searchParams.get("start"),
      req.nextUrl.searchParams.get("end"),
    );
    if ("error" in range) {
      return NextResponse.json({ error: range.error }, { status: 400 });
    }
    start = range.start;
    end = range.end;
  }

  try {
    const result = await getKlineRange(type, code, start, end, interval);
    return NextResponse.json(result);
  } catch (e) {
    if (e instanceof DataServiceError) {
      const status = e.status === 502 ? 502 : e.status === 501 ? 501 : 503;
      return NextResponse.json(
        { error: e.message },
        { status },
      );
    }
    return NextResponse.json({ error: "kline fetch failed" }, { status: 500 });
  }
}
