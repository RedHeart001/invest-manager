import { NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";

// 容器健康检查端点（P7）：校验应用可响应 **且** 数据库连通
// - docker compose 的 service_healthy 依赖它（data-service 等 web 就绪）
// - 不暴露敏感信息，仅返回 ok/version 与 DB 探活结果
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    await prisma.$queryRaw`SELECT 1`;
    return NextResponse.json({ status: "ok", db: "ok" });
  } catch (e) {
    // 安全（代码审查修复）：异常细节可能含 DATABASE_URL/路径等敏感信息，
    // 只回固定文案，细节写服务端日志
    console.error("[health] db check failed:", e instanceof Error ? e.message : e);
    return NextResponse.json({ status: "degraded", db: "unavailable" }, { status: 503 });
  }
}
