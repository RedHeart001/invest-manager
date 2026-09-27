import { NextRequest, NextResponse } from "next/server";

import { refreshAll, refreshSnapshot } from "@/lib/market-snapshot";
import { checkRequestOrigin } from "@/lib/request-origin";

// CR-07（本轮 code review）：全类型快照刷新走东财批量通道，单类型即数分钟。显式声明 maxDuration。
// （C3-②/CR7-9 勘误 2026-09-25：原注释"stock 约 2.9 万只"把量级安错了类型——
// 实测 fund 27916 / stock 5913 / bond 1059 / crypto 250。）
//
// CR9-20（2026-09-27 实测定数，800→1500）：批间隔按 CR9-9 抬到 5s 后重新算时长——
// 当日库内真实批次：stock 60 + fund 30（27954 只里只有 2821 只场内打东财）+ bond 11
// + hk 48（列表到货后）＝ **149 个东财批次**。改后代码实跑 `POST /api/market/refresh?type=bond`
// ⇒ **11 批 51.7s（有效 4.7s/批，末批不尾延）且 updated=311 / failedBatches=0 照常产出**，
// 据此折算全类型 ≈ **700s**，加场外净值整表首拉与 280 批写库 ≈ 750~900s
// （与 CR7-9 当年"5 类串行 15 分钟起"的推算吻合，当年是拿推算当代测）。
// 1500s = 实测上界的 1.7 倍，与 /api/sync 同值（每日同步末尾跑的就是同一份刷新）。
// ⚠️ 上界要说清楚：熔断日单批仍可能被 ds 侧 `acquire` 排队卡满 20s ⇒ 全量刷新理论
// 上界约 60 分钟，任何 maxDuration 都盖不住；自托管下本声明不强制执行，真正的护栏是
// 源族桶的冷却与 ds 侧超时（见 docs/CONSTRAINTS.md C-5）。
export const maxDuration = 1500;

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
