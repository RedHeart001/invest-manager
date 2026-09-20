// 行情快照刷新（R14 分类浏览）：
// 把全类型产品的最新价/涨跌幅批量写入 Product.lastPrice/lastChangePct，
// 供"分类浏览"做全局涨幅排序（库内排序，避免对 3.4 万产品打实时行情）。
// - 每日同步（lib/sync.ts）末尾自动执行；也可 POST /api/market/refresh 手动触发
// - 展示层仍以实时富集为准（P1 管线），快照只用于排序
// - 限流友好：EM 通道批次间隔 1.5s；任一批次失败不中断整体（R10），返回失败计数

import { fetchQuotes } from "./data-service";
import { prisma } from "./prisma";

const BATCH = 100;
const EM_TYPES = new Set(["stock", "bond"]); // 走东财 ulist，需限速
const EM_BATCH_DELAY_MS = 1500;

type SnapshotResult = {
  type: string;
  total: number;
  updated: number;
  failedBatches: number;
  tookMs: number;
};

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** 构造批量快照 UPDATE 的 SQL 与绑定参数（纯函数，便于单测；CR-09） */
export function buildSnapshotUpdate(
  type: string,
  rows: { code: string; price: number | null; changePct: number | null }[],
): { sql: string; params: unknown[] } {
  const codes = rows.map((r) => r.code);
  const placeholders = codes.map(() => "?").join(",");
  const caseOf = (n: number) => Array.from({ length: n }, () => "WHEN ? THEN ?").join(" ");

  const params: unknown[] = [];
  for (const r of rows) params.push(r.code, r.price);
  for (const r of rows) params.push(r.code, r.changePct);

  const sql = `UPDATE "Product" SET
       "lastPrice" = COALESCE(CASE "code" ${caseOf(rows.length)} END, "lastPrice"),
       "lastChangePct" = COALESCE(CASE "code" ${caseOf(rows.length)} END, "lastChangePct")
     WHERE "type" = ? AND "code" IN (${placeholders})`;
  return { sql, params: [...params, type, ...codes] };
}

async function updateChunk(
  type: string,
  rows: { code: string; price: number | null; changePct: number | null }[],
): Promise<void> {
  // CR6-P1-2（2026-09-18 review）：此前是"一个事务里跑 100 条 updateMany"，
  // 在 SQLite 单写锁下把锁窗口拉到秒级（timeout 120s），与页面读库并发时
  // 读请求会遭遇 SQLITE_BUSY。改为**整批一条 UPDATE**（CASE 表达式），
  // 锁窗口从秒级降到毫秒级——未命中的 code 不更新。
  //
  // 参数上限：BATCH=100 → 100×2（price）+100×2（changePct）+1（type）+100（code）
  // = 501 个绑定参数，低于 SQLite 默认 999 上限。
  if (rows.length === 0) return;
  // CR-09（本轮 code review）：某字段缺失（null）时**保留旧值**——
  // 此前 CASE 会把该行另一为 null 的字段直接写成 NULL，覆盖上一轮有效快照。
  // 用 COALESCE(新值, 旧值)：新值为 null 时沿用旧值，避免部分降级把快照列擦空。
  // code/type 均来自库内白名单（products 表），无注入面；值一律走绑定参数。
  const { sql, params } = buildSnapshotUpdate(type, rows);
  await prisma.$executeRawUnsafe(sql, ...params);
}

// M2/O3：单飞——每日 sync 与手动 refresh 并发触发时共享同一次刷新，
// 避免 SQLite 单写锁下两个长事务互相等待
//
// C17（2026-09-14 code review 修复）：跨请求共享的进程内单例必须挂 globalThis——
// Next dev 的 HMR 会重建模块作用域，模块级 Map 随之清空，而旧模块里仍在跑的刷新
// 不受影响 → 新请求会另起一次同类型刷新（写锁争用 + 重复外部取数），
// 正是本单飞要防的场景。
const INFLIGHT_KEY = Symbol.for("invest-manager.market.snapshot.inflight");
const inflight: Map<string, Promise<SnapshotResult>> = ((
  globalThis as unknown as Record<symbol, Map<string, Promise<SnapshotResult>> | undefined>
)[INFLIGHT_KEY] ??= new Map());

export function refreshSnapshot(type: string): Promise<SnapshotResult> {
  const hit = inflight.get(type);
  if (hit) return hit;
  const p = refreshSnapshotInner(type).finally(() => inflight.delete(type));
  inflight.set(type, p);
  return p;
}

async function refreshSnapshotInner(type: string): Promise<SnapshotResult> {
  const started = Date.now();
  const products = await prisma.product.findMany({
    where: { type },
    select: { code: true },
    orderBy: { code: "asc" },
  });
  const total = products.length;
  if (total === 0) {
    return { type, total: 0, updated: 0, failedBatches: 0, tookMs: Date.now() - started };
  }

  let updated = 0;
  let failedBatches = 0;
  for (let i = 0; i < total; i += BATCH) {
    const codes = products.slice(i, i + BATCH).map((p) => p.code);
    try {
      const quotes = await fetchQuotes(type, codes);
      const rows = codes
        .map((code) => {
          const q = quotes[code];
          return {
            code,
            price: q?.price ?? null,
            changePct: q?.changePct ?? null,
          };
        })
        .filter((r) => r.price != null || r.changePct != null);
      if (rows.length === 0) {
        // 整批无可用报价（代码审查修复）：`fetchQuotes` 在数据源不可达时
        // 会静默返回空对象，此前直接跳过 → "updated=0 failedBatches=0" 被
        // 当成正常成功，分类浏览的排序数据长期陈旧却无任何标注。
        failedBatches += 1;
      } else {
        await updateChunk(type, rows);
        updated += rows.length;
      }
    } catch {
      failedBatches += 1;
    }
    if (EM_TYPES.has(type) && i + BATCH < total) {
      await sleep(EM_BATCH_DELAY_MS);
    }
  }
  return { type, total, updated, failedBatches, tookMs: Date.now() - started };
}

export async function refreshAll(types: string[]): Promise<SnapshotResult[]> {
  const results: SnapshotResult[] = [];
  for (const t of types) {
    results.push(await refreshSnapshot(t));
  }
  return results;
}
