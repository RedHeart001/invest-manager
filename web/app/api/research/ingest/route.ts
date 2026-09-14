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
  // type 缺失会让 upsert.create 触发 Prisma 500（堆栈泄漏）→ 仅判非空。
  // 注意（2026-09-14 code review 回归修复）：**不得**限制 type 枚举——
  // ResearchPanel 对所有类型（stock/fund/bond/crypto/hk/us）渲染，
  // data-service /research/start 接受任意 type，白名单会把 fund/bond/crypto/hk
  // 的完成回调全部 400 拒绝 → ResearchReport 永久 running、前端无限轮询、研报静默丢失。
  if (!payload.type) {
    return NextResponse.json({ error: "type is required" }, { status: 400 });
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
