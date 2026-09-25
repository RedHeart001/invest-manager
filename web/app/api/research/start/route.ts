import { NextRequest, NextResponse } from "next/server";

import { startResearch } from "@/lib/research";
import { CODE_SET, QUOTE_TYPES } from "@/lib/validate";

// CR4（P3）：研报支持的类型白名单 + code 字符集约束
// C5（2026-09-25）：改用 lib/validate.ts 单一来源（原字面量硬写删除）
const TYPES = QUOTE_TYPES;

// 提交深度研究任务（P5 / M5）：详情页按钮与聊天 L2 工具共用入口
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as {
    type?: string;
    code?: string;
    name?: string;
    sessionId?: string;
  };
  const type = String(body.type ?? "stock").trim();
  const code = String(body.code ?? "").trim();
  // CR-14（本轮 code review）：可选 sessionId 透传——聊天路径通过 lib/research
  // 直接传发起会话；此 BFF 路由此前不透传，导致"统一入口"的会话语义缺口。
  // 详情页触发不传（无会话，属预期），聊天侧如需经 BFF 也可带上。
  const sessionId = body.sessionId ? String(body.sessionId).slice(0, 64) : undefined;
  // CR4（P3）：type/code 白名单——code 经 WAT_FTS 之外还会拼进研报推送的
  // markdown 链接（/product/${type}/${code}#research），限制字符集避免注入
  // 任意 linker（react-markdown 已拦 javascript:，此处收紧可注入 https 外链的面）。
  if (!CODE_SET.test(code)) {
    return NextResponse.json({ error: "illegal code" }, { status: 400 });
  }
  if (!TYPES.includes(type as (typeof TYPES)[number])) {
    return NextResponse.json({ error: "illegal type" }, { status: 400 });
  }
  if (!code) {
    return NextResponse.json({ error: "code is required" }, { status: 400 });
  }
  try {
    const result = await startResearch(type, code, body.name, sessionId);
    return NextResponse.json(result);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "start failed" },
      { status: 500 },
    );
  }
}

export const dynamic = "force-dynamic";
