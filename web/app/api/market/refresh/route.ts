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
// 1500s = 实测上界的 1.7 倍。⚠️ 那个上界已被 10-01 实测推翻（fund 的 280 个净值批次单独
// ≈1,700s ⇒ 全类型刷新真实基数 ≈2,300s，不是 850~900s）。刀 3/甲-1（2026-10-02）之后
// **本端点就是每日刷新腿**（ds 在同步腿收尾后链式打 `?type=all`），所以按新实测把它抬到
// 2400s，与 ds 侧 `sync_scheduler.REFRESH_CALLBACK_TIMEOUT_S` 同值——注意这是**对齐**不是
// "修法"：真正的修法是把这 1,700s 从同步事务里拆出来各拿各的预算，抬一个数盖住两件事
// 是账本里已经否掉过的做法（见「批次划分」八·明确不做）。
// ⚠️ 上界仍要说清楚：熔断日单批可能被 ds 侧 `acquire` 排队卡满 20s ⇒ 全量刷新理论上界约
// 60 分钟，任何 maxDuration 都盖不住；自托管下本声明不强制执行，真正的护栏是源族桶的冷却
// （见 docs/CONSTRAINTS.md C-5）。
export const maxDuration = 2400;

// 行情快照刷新（R14）：把各类型最新价/涨跌幅写入 Product 快照列。
// 触发形态（刀 3/甲-1，2026-10-02）：**不再挂在 lib/sync.ts 的同步事务末尾**，改由
// data-service 在同步腿收尾后链式调用 `?type=all`；手动触发是同一条路径。EM 通道已内置批次限速。
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
  // #23 当日幂等闸门：这一条腿才是甲-1 之后**真正贵的那条**（10-01 实测 fund 的 280 个
  // 净值批次单独 ≈1,700s），判据＝该类今日有没有 `snapshotAt`；逐类各自判 ⇒
  // "列表今天到位了、快照还没到位"这种最需要补的形态照常放行（`?force=1` 为总出口）。
  const force = req.nextUrl.searchParams.get("force") === "1";
  try {
    const results =
      types.length === 1
        ? [await refreshSnapshot(types[0], { force })]
        : await refreshAll(types, { force });
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
