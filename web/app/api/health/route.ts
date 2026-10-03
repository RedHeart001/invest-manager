import { NextResponse } from "next/server";

import { prisma } from "@/lib/prisma";
import { readRefreshProgress } from "@/lib/refresh-progress";

// 容器健康检查端点（P7）：校验应用可响应 **且** 数据库连通
// - docker compose 的 service_healthy 依赖它（data-service 等 web 就绪）
// - 不暴露敏感信息，仅返回 ok/version 与 DB 探活结果
//
// #33 甲／CR9-60 追加的 `refresh`：刷新腿的逐类进度状态位（无文件时为 null）。
// ds 那侧在**刷新腿失败的三条路径**上 GET 这一次把进度读回去（`sync_scheduler._refresh_progress`）——
// 连接被中途重置时响应体永远拿不到，只有这里还能读出"跑到第几类"。
// 两个分支都带这个键：库正忙／刚被重启的那一刻，恰恰是最需要看进度的时刻。载荷只有逐类
// 计数与时刻，**不含绝对路径**（与 #29 的 `state.json` 载荷口径一致）。
export const dynamic = "force-dynamic";

export async function GET() {
  const refresh = readRefreshProgress();
  try {
    await prisma.$queryRaw`SELECT 1`;
    return NextResponse.json({ status: "ok", db: "ok", refresh });
  } catch (e) {
    // 安全（代码审查修复）：异常细节可能含 DATABASE_URL/路径等敏感信息，
    // 只回固定文案，细节写服务端日志
    console.error("[health] db check failed:", e instanceof Error ? e.message : e);
    return NextResponse.json(
      { status: "degraded", db: "unavailable", refresh },
      { status: 503 },
    );
  }
}
