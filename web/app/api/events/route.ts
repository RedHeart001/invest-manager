import { NextRequest, NextResponse } from "next/server";

import { fetchEvents } from "@/lib/events";
import { checkSubject } from "@/lib/validate";

// 事件标注（R11 轻量归因）：股票走东财新闻，其余类型返回缺口说明
export async function GET(req: NextRequest) {
  // CR9-10：改走 lib/validate 单一来源（此前只判 code 非空，任意串都能进
  // fetchEvents→dsGet("/news")，耗东财额度且绕过 type 白名单）
  const v = checkSubject(
    req.nextUrl.searchParams.get("type"),
    req.nextUrl.searchParams.get("code"),
  );
  if ("error" in v) {
    return NextResponse.json({ error: v.error }, { status: 400 });
  }
  const result = await fetchEvents(v.type, v.code);
  return NextResponse.json(result);
}
