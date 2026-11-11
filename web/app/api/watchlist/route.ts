import { NextRequest, NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";

// G5（批次 D）：自选产品（Watchlist）。
// 此前 Watchlist 表只被 search.ts **读取**用于排序加权，却没有任何写入入口
// （"只读不通写"的半成品）。此处补齐增删查，使自选加权真正可用。
//
// 约束：type/code 走白名单与字符集校验（与 research/start 同口径），
// name 用于展示（前端已带，缺失时回退 code）。

// C5（2026-09-25）：改用 lib/validate.ts 单一来源（原字面量硬写删除）
import { CODE_SET, QUOTE_TYPES } from "@/lib/validate";
import { checkRequestOrigin } from "@/lib/request-origin";

const TYPES = QUOTE_TYPES;

export async function GET() {
  try {
    const rows = await prisma.watchlist.findMany({ orderBy: { createdAt: "desc" } });
    return NextResponse.json({
      items: rows.map((r) => ({ type: r.type, code: r.code, name: r.name })),
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "watchlist read failed" },
      { status: 500 },
    );
  }
}

export async function POST(req: NextRequest) {
  // CR10-12：本枚是看板上最早登记的那一枚（`#74`／CR10-10 的 POST 那半），与其余
  // 三枚可被外站驱动的 POST 一起补。DELETE 当时判为非简单请求（浏览器必先预检、全站零 CORS 头
  // ⇒ 外站驱动不到）缓办；CR10-20（2026-11-12 主人拍板）已补齐＝纵深防御，两枚写腿同口径。
  const blocked = checkRequestOrigin(req);
  if (blocked) {
    return NextResponse.json({ error: blocked }, { status: 403 });
  }
  const body = (await req.json().catch(() => ({}))) as {
    type?: string;
    code?: string;
    name?: string;
  };
  const type = String(body.type ?? "").trim();
  const code = String(body.code ?? "").trim();
  const name = String(body.name ?? code).trim().slice(0, 100);
  if (!TYPES.includes(type as (typeof TYPES)[number])) {
    return NextResponse.json({ error: "illegal type" }, { status: 400 });
  }
  if (!CODE_SET.test(code)) {
    return NextResponse.json({ error: "illegal code" }, { status: 400 });
  }
  try {
    // upsert：重复添加幂等（唯一键 type+code）
    await prisma.watchlist.upsert({
      where: { type_code: { type, code } },
      create: { type, code, name },
      update: { name },
    });
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "watchlist add failed" },
      { status: 500 },
    );
  }
}

export async function DELETE(req: NextRequest) {
  // CR10-20：纵深防御补齐。挡在读 searchParams 之前（与 POST 同口径；仍不挂写 token 守卫＝浏览器持不住密钥）。
  const blocked = checkRequestOrigin(req);
  if (blocked) {
    return NextResponse.json({ error: blocked }, { status: 403 });
  }
  const type = req.nextUrl.searchParams.get("type") ?? "";
  const code = req.nextUrl.searchParams.get("code") ?? "";
  if (!TYPES.includes(type as (typeof TYPES)[number]) || !CODE_SET.test(code)) {
    return NextResponse.json({ error: "illegal type/code" }, { status: 400 });
  }
  try {
    await prisma.watchlist.deleteMany({ where: { type, code } });
    return NextResponse.json({ ok: true });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "watchlist delete failed" },
      { status: 500 },
    );
  }
}

export const dynamic = "force-dynamic";
