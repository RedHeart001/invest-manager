import { NextRequest, NextResponse } from "next/server";

import { startResearch } from "@/lib/research";

// CR4（P3）：研报支持的类型白名单 + code 字符集约束
const TYPES = ["stock", "fund", "bond", "crypto", "hk", "us"];
const CODE_SET = /^[\w.-]{1,20}$/;

// 提交深度研究任务（P5 / M5）：详情页按钮与聊天 L2 工具共用入口
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as {
    type?: string;
    code?: string;
    name?: string;
  };
  const type = String(body.type ?? "stock").trim();
  const code = String(body.code ?? "").trim();
  // CR4（P3）：type/code 白名单——code 经 WAT_FTS 之外还会拼进研报推送的
  // markdown 链接（/product/${type}/${code}#research），限制字符集避免注入
  // 任意 linker（react-markdown 已拦 javascript:，此处收紧可注入 https 外链的面）。
  if (!CODE_SET.test(code)) {
    return NextResponse.json({ error: "illegal code" }, { status: 400 });
  }
  if (!TYPES.includes(type)) {
    return NextResponse.json({ error: "illegal type" }, { status: 400 });
  }
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
