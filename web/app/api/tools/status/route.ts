import { NextResponse } from "next/server";

import { gatewayStatus } from "@/lib/gateway";

// P6（M7）：Tool Gateway 可视面板——内置工具 / 技能 / MCP server 连接与降级状态
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    // connect=true：探测 MCP 连接，使面板反映真实可用性与降级原因
    return NextResponse.json(await gatewayStatus({ connect: true }));
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "gateway status failed" },
      { status: 500 },
    );
  }
}
