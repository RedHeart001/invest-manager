import { NextRequest, NextResponse } from "next/server";

import { startResearch } from "@/lib/research";

// 提交深度研究任务（P5 / M5）：详情页按钮与聊天 L2 工具共用入口
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as {
    type?: string;
    code?: string;
    name?: string;
  };
  const type = String(body.type ?? "stock").trim();
  const code = String(body.code ?? "").trim();
  if (!code) {
    return NextResponse.json({ error: "code is required" }, { status: 400 });
  }
  try {
    const result = await startResearch(type, code, body.name);
    return NextResponse.json(result);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "start failed" },
      { status: 500 },
    );
  }
}

export const dynamic = "force-dynamic";
