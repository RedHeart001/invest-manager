import { NextRequest, NextResponse } from "next/server";

import { refreshAll, refreshSnapshot } from "@/lib/market-snapshot";
import { checkRequestOrigin } from "@/lib/request-origin";

// CR-07（本轮 code review）：全类型快照刷新走东财批量通道（含 1.5s/批节流），
// fund 27811 只 → 单类型即数分钟。显式声明 maxDuration。
// （C3-②/CR7-9 勘误 2026-09-25：原注释"stock 约 2.9 万只"把量级安错了类型——
// 实测 fund 27916 / stock 5913 / bond 1059 / crypto 250。）
export const maxDuration = 800;

// 行情快照刷新（R14）：把各类型最新价/涨跌幅写入 Product 快照列。
// 低频任务：每日同步末尾自动执行；此处供手动触发。EM 通道已内置批次限速。
export async function POST(req: NextRequest) {
  // CR-08：拒绝浏览器跨站简单表单触发
  const blocked = checkRequestOrigin(req);
  if (blocked) {
    return NextResponse.json({ error: blocked }, { status: 403 });
  }
  const type = req.nextUrl.searchParams.get("type") ?? "all";
  // G6：纳入 hk（港股）
  const SNAPSHOT_TYPES = ["stock", "fund", "bond", "crypto", "hk"];
  const types =
    type === "all" ? SNAPSHOT_TYPES : SNAPSHOT_TYPES.includes(type) ? [type] : null;
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
