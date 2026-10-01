import { NextRequest, NextResponse } from "next/server";

import { broadcast } from "@/lib/sse";
import { prisma } from "@/lib/prisma";
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
  // 刀 2（#22(a)，2026-10-01）：**语义白名单**，不是枚举白名单——上面那条 09-14 的决定
  // 依然成立，所以这里不查 QUOTE_TYPES；查的是"这个标的存在吗"。
  // 起因：10-01 实测 `POST {"type":"bogus","code":"600519",…}` → `200` 并真的 upsert 出
  // 一行研报（我当场删掉了）。`/research/start` 那一侧有 CODE_SET＋QUOTE_TYPES 把关，
  // 所以任意字符串只能从 ingest 这个口子进来。
  // **放行条件刻意是两条"或"**：我们自己发起过的 (type, code) 必须照收——哪怕它不在
  // Product 里（hk 列表未到货时 Product hk 为 0 行，正是 CR9-26② 的现状）。若只认
  // Product，这类在途任务会被 400 拒掉 ⇒ 行永远停在 running ⇒ 就是 09-14 那条事故
  // 换条路重演。所以：有既有研报行 **或** 标的在 Product 里 → 收；两者都无 → 400 不写库。
  const code = String(payload.code).trim();
  const type = String(payload.type).trim();
  try {
    const known =
      (await prisma.researchReport.count({ where: { type, code } })) > 0 ||
      (await prisma.product.findFirst({ where: { type, code }, select: { code: true } })) !== null;
    if (!known) {
      return NextResponse.json(
        { error: `unknown subject: ${type}/${code} 既不在 Product，也没有在途研报行` },
        { status: 400 },
      );
    }
  } catch (e) {
    // 查库失败不拿它当拒绝理由——宁可放行由下游 upsert 报错，也不能把在途研报挡在门外
    console.warn("research ingest 标的核验查库失败，按放行处理：", e);
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
