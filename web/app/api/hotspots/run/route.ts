import { NextRequest, NextResponse } from "next/server";

import { dsPost, DataServiceError } from "@/lib/data-service";
import { checkRequestOrigin } from "@/lib/request-origin";

// 手动触发热点抓取（代码审查修复）：
// 此前 Dashboard 由**浏览器直连** `${NEXT_PUBLIC_DATA_SERVICE_URL ?? localhost:8000}`，
// 而 P7 容器化后 data-service 故意不发布端口（仅 compose 内网可达）→ 按钮必然失效。
// 改为经 BFF 代理，浏览器永远只与 web 通信（与全站 BFF 约定一致）。
export const dynamic = "force-dynamic";
// 热点 pipeline 含多次外部抓取 + LLM 结构化，耗时可达分钟级
export const maxDuration = 300;

export async function POST(req: NextRequest) {
  // CR-08：拒绝浏览器跨站简单表单触发（无请求体的 POST 尤其易被 CSRF）
  const blocked = checkRequestOrigin(req);
  if (blocked) {
    return NextResponse.json({ error: blocked }, { status: 403 });
  }
  try {
    const data = await dsPost<Record<string, unknown>>(
      "/hotspots/run?trigger=manual-ui",
      {},
      240_000,
    );
    return NextResponse.json(data);
  } catch (e) {
    const status = e instanceof DataServiceError ? e.status ?? 502 : 502;
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "hotspots run failed" },
      { status },
    );
  }
}
