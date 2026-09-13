import { NextRequest, NextResponse } from "next/server";

import { broadcast } from "@/lib/sse";
import { ingestResearch, type IngestPayload } from "@/lib/research";

// 研报完成回调（data-service → BFF，产出落库统一模式）+ SSE 广播
const INGEST_TOKEN = process.env.INGEST_TOKEN;

export async function POST(req: NextRequest) {
  if (INGEST_TOKEN && req.headers.get("x-ingest-token") !== INGEST_TOKEN) {
    return NextResponse.json({ error: "invalid ingest token" }, { status: 401 });
  }
  let payload: IngestPayload;
  try {
    payload = (await req.json()) as IngestPayload;
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (!payload.code) {
    return NextResponse.json({ error: "code is required" }, { status: 400 });
  }
  // 2026-09-13 code review：type 缺失会让 upsert.create 触发 Prisma 500（堆栈泄漏）
  if (!payload.type) {
    return NextResponse.json({ error: "type is required" }, { status: 400 });
  }
  if (payload.type !== "stock" && payload.type !== "us") {
    return NextResponse.json(
      { error: `unsupported research type: ${payload.type}` },
      { status: 400 },
    );
  }
  try {
    const row = await ingestResearch(payload);
    return NextResponse.json({ ok: true, status: row.status, rating: row.rating });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "ingest failed" },
      { status: 500 },
    );
  }
}

export const dynamic = "force-dynamic";
