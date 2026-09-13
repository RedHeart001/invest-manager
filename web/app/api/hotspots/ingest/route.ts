import { NextRequest, NextResponse } from "next/server";

import { broadcast } from "@/lib/sse";
import { countDigests, ingestDigests, type IngestPayload } from "@/lib/hotspots";

// 热点 digest 落库回调（data-service → BFF，PLAN「产出落库的统一模式」）
// POST：落库 + SSE 广播；GET：按日期计数（供 data-service 启动补跑判断）
export async function POST(req: NextRequest) {
  const expected = process.env.INGEST_TOKEN;
  if (expected && req.headers.get("x-ingest-token") !== expected) {
    return NextResponse.json({ error: "invalid ingest token" }, { status: 401 });
  }

  let payload: IngestPayload;
  try {
    payload = (await req.json()) as IngestPayload;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  try {
    const result = await ingestDigests(payload);
    if (result.rows.length > 0) {
      broadcast("digest", {
        date: payload.date,
        trigger: payload.trigger ?? "manual",
        rows: result.rows,
      });
    }
    return NextResponse.json({
      date: payload.date,
      inserted: result.inserted,
      skipped: result.skipped,
      count: await countDigests(payload.date),
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "ingest failed" },
      { status: 400 },
    );
  }
}

export async function GET(req: NextRequest) {
  const date = req.nextUrl.searchParams.get("date");
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return NextResponse.json({ error: "date=YYYY-MM-DD is required" }, { status: 400 });
  }
  return NextResponse.json({ date, count: await countDigests(date) });
}
