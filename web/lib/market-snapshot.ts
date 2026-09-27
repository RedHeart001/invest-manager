// 行情快照刷新（R14 分类浏览）：
// 把全类型产品的最新价/涨跌幅批量写入 Product.lastPrice/lastChangePct，
// 供"分类浏览"做全局涨幅排序（库内排序，避免对 3.4 万产品打实时行情）。
// - 每日同步（lib/sync.ts）末尾自动执行；也可 POST /api/market/refresh 手动触发
// - 展示层仍以实时富集为准（P1 管线），快照只用于排序
// - 限流友好：东财族批次间隔与源族桶放行速率同值（`EM_BATCH_DELAY_MS`，CR9-9）；
//   任一批次失败不中断整体（R10），返回失败计数

import { fetchQuotes } from "./data-service";
import { prisma } from "./prisma";

const BATCH = 100;

/** 会打东财 ulist 批量通道的类型（CR9-9，2026-09-27 按源实测，不再靠猜）：
 *  - stock / bond / **fund** → `akshare_provider._em_ulist`；fund 只有**场内**部分打东财
 *    （实测 27954 只里 2821 只场内，落在 280 批中的 30 批），场外走 30 分钟缓存的全市场净值表单请求
 *  - **hk** → `hk_provider.get_quotes`，与 A 股共用**同一个** eastmoney 源族令牌桶
 *  - crypto → CoinGecko（不属东财族）；us 不在刷新类型内 ⇒ 两者都不需要限速
 */
export const EM_SNAPSHOT_TYPES = new Set(["stock", "fund", "bond", "hk"]);

/** 东财族批间隔（CR9-9）：**与源族桶自己的放行速率同值**，不是随手调的礼貌性节流。
 *
 * data-service 的 eastmoney 桶＝`min_interval 5s / burst 2 / rate_per_min 12`
 * （唯一来源 `utils/limiter.py:PROFILES`）⇒ 稳态最多 12 批/分钟。
 *
 * 09-27 同一天、同一批转债标的做了对照实验（各 20 批 × 100 只，直连 data-service）：
 *   · @1.5s（改动前）：尝试速率 **14.3 批/分** ＞ 桶的 12 ⇒ 批 1–2 走 burst（0.4/1.0s），
 *     批 3–12 一律被 ds 侧 `acquire` 排队拉到 3.2~3.75s，批 13 滑窗卡到 6.86s，
 *     批 14 东财报 all-hosts 失败并**连坐熔断 180s** ⇒ 余下批次 0.01~2.3s 全部转备源。
 *     **非主源批次 7/20**。
 *   · @5.5s（改动后）：尝试速率 **10.1 批/分** ＜ 12 ⇒ **非主源批次 0/20**，
 *     单批均值从 2.69s 掉到 **0.58s**（排队整个消失），全程 `src=akshare` 无 note。
 * ⇒ 抬到 5s（5s + 实测单批 0.58s ≈ 10.7 批/分，仍在桶内）不是"更礼貌"，而是
 *    **让快照不再自己把家族打进熔断**——熔断一开，同族所有消费者（热点 pipeline、
 *    搜索行情富集、其它类型快照）一起连坐，这正是 CR9-9 原始现象与 CR7-7 的根因。
 * 代价实测口径（不是推算）：09-27 12:2x 用改后代码实跑 `POST /api/market/refresh?type=bond`
 * ⇒ **11 批 51.7s（有效 4.7s/批，末批无尾延）**，`updated=311 failedBatches=0` 快照照常产出；
 * 按当日真实批次数 149 个东财批次折算全类型刷新 ≈ **700s**（＋场外净值首拉与 280 批写库），
 * 这就是 `/api/market/refresh` 的 maxDuration 从 800 抬到 1500 的依据（CR9-20）。
 */
export const EM_BATCH_DELAY_MS = 5000;

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
    if (EM_SNAPSHOT_TYPES.has(type) && i + BATCH < total) {
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
