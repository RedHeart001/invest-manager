import { NextRequest, NextResponse } from "next/server";

import { refreshAll, refreshSnapshot } from "@/lib/market-snapshot";

// 行情快照刷新（R14）：把各类型最新价/涨跌幅写入 Product 快照列。
// 低频任务：每日同步末尾自动执行；此处供手动触发。EM 通道已内置批次限速。
export async function POST(req: NextRequest) {
  const type = req.nextUrl.searchParams.get("type") ?? "all";
  const types =
    type === "all"
      ? ["stock", "fund", "bond", "crypto"]
      : ["stock", "fund", "bond", "crypto"].includes(type)
        ? [type]
        : null;
  if (!types) {
    return NextResponse.json({ error: `unsupported type: ${type}` }, { status: 400 });
  }
  const started = Date.now();
  try {
    const results =
      types.length === 1 ? [await refreshSnapshot(types[0])] : await refreshAll(types);
    return NextResponse.json({
      tookMs: Date.now() - started,
      results,
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "snapshot refresh failed" },
      { status: 500 },
    );
  }
}
