// 行情快照刷新（R14 分类浏览）：
// 把全类型产品的最新价/涨跌幅批量写入 Product.lastPrice/lastChangePct，
// 供"分类浏览"做全局涨幅排序（库内排序，避免对 3.4 万产品打实时行情）。
// - 触发形态（刀 3/甲-1，2026-10-02）：**不再挂在 lib/sync.ts 的同步事务末尾**，改由
//   data-service 在同步腿收尾后链式调用 `POST /api/market/refresh?type=all`（两条腿各拿
//   各的预算，理由与数字见 `app/sync_scheduler.py`）；手动触发是同一条路径
// - 展示层仍以实时富集为准（P1 管线），快照只用于排序
// - 限流友好：东财族批次间隔与源族桶放行速率同值（`EM_BATCH_DELAY_MS`，CR9-9）；
//   任一批次失败不中断整体（R10），返回失败计数

import { fetchQuotes } from "./data-service";
import { snapshotRefreshedToday } from "./freshness";
import { prisma } from "./prisma";
import { completedToday, hasCompletionLedger, lastCompletedAt } from "./refresh-progress";
import { beijingStamp } from "./time";

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

export type SnapshotResult = {
  type: string;
  total: number;
  updated: number;
  failedBatches: number;
  tookMs: number;
  /** 本轮写入的快照时刻（ISO）；一批都没写成功时为 null（刀 1/#22(b)） */
  snapshotAt: string | null;
  /** #23 当日幂等闸门（甲-1 之后**贵的那条腿在这里**）：该类今日已刷过 ⇒
   *  本轮零出网、零写库，`snapshotAt` 回填库里已有的那个时刻而不是新时刻 */
  skipped?: boolean;
  /** 被挡下时自己说清"哪一列、几点"（#21 同族：能做成状态位的别做成日志） */
  skippedReason?: string;
  /** CR9-61（乙＝可续跑）：本轮是**接着被打断的那一类重跑**的（今日有 `snapshotAt`
   *  但完成账本里没有它）。标出来是为了让 ds 的 `results` 与页面上都能看出这一轮不是常规轮；
   *  续跑粒度＝整类重跑，不是批次游标。 */
  resumed?: boolean;
};

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** 构造批量快照 UPDATE 的 SQL 与绑定参数（纯函数，便于单测；CR-09）
 *
 * 刀 1（#22(b)）：整批写一个**共享的 `snapshotAt` 时刻**。此前快照列没有任何
 * "这是什么时候的价"的记号——`updatedAt` 是 Prisma 的 `@updatedAt`，只被 list 阶段的
 * 整表删旧插新推动，而这里的 raw SQL 绕过 Prisma 所以根本不碰它 ⇒ 分类浏览的涨幅
 * 排序可以长期吃陈旧价而无人可知（10-01 实测：库内 `600519 lastPrice=1275.16`，
 * 同日实盘 1258.62，差 1.3%）。时刻由**调用方传入** ⇒ 一次刷新内所有批次同一标记，
 * 并能与 `updatedAt`（list 阶段）对照出"哪一类只换了主数据、没刷到快照"。
 */
export function buildSnapshotUpdate(
  type: string,
  rows: { code: string; price: number | null; changePct: number | null }[],
  snapshotAt: Date,
): { sql: string; params: unknown[] } {
  const codes = rows.map((r) => r.code);
  const placeholders = codes.map(() => "?").join(",");
  const caseOf = (n: number) => Array.from({ length: n }, () => "WHEN ? THEN ?").join(" ");

  const params: unknown[] = [];
  for (const r of rows) params.push(r.code, r.price);
  for (const r of rows) params.push(r.code, r.changePct);

  const sql = `UPDATE "Product" SET
       "lastPrice" = COALESCE(CASE "code" ${caseOf(rows.length)} END, "lastPrice"),
       "lastChangePct" = COALESCE(CASE "code" ${caseOf(rows.length)} END, "lastChangePct"),
       "snapshotAt" = ?
     WHERE "type" = ? AND "code" IN (${placeholders})`;
  // 绑定顺序必须与 SQL 文本里的 ? 同序：price 组 → changePct 组 → snapshotAt → type → codes
  return { sql, params: [...params, snapshotAt, type, ...codes] };
}

async function updateChunk(
  type: string,
  rows: { code: string; price: number | null; changePct: number | null }[],
  snapshotAt: Date,
): Promise<void> {
  // CR6-P1-2（2026-09-18 review）：此前是"一个事务里跑 100 条 updateMany"，
  // 在 SQLite 单写锁下把锁窗口拉到秒级（timeout 120s），与页面读库并发时
  // 读请求会遭遇 SQLITE_BUSY。改为**整批一条 UPDATE**（CASE 表达式），
  // 锁窗口从秒级降到毫秒级——未命中的 code 不更新。
  //
  // 参数上限：BATCH=100 → 100×2（price）+100×2（changePct）+1（snapshotAt）+1（type）+100（code）
  // = 502 个绑定参数，低于 SQLite 默认 999 上限。
  if (rows.length === 0) return;
  // CR-09（本轮 code review）：某字段缺失（null）时**保留旧值**——
  // 此前 CASE 会把该行另一为 null 的字段直接写成 NULL，覆盖上一轮有效快照。
  // 用 COALESCE(新值, 旧值)：新值为 null 时沿用旧值，避免部分降级把快照列擦空。
  // code/type 均来自库内白名单（products 表），无注入面；值一律走绑定参数。
  const { sql, params } = buildSnapshotUpdate(type, rows, snapshotAt);
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

export function refreshSnapshot(
  type: string,
  opts: { force?: boolean } = {},
): Promise<SnapshotResult> {
  const hit = inflight.get(type);
  if (hit) return hit;
  const p = _refreshGated(type, opts.force === true).finally(() => inflight.delete(type));
  inflight.set(type, p);
  return p;
}

/** #23 当日幂等闸门（刷新腿这一侧＝**真正贵的那条**）
 *
 * 刀 3/甲-1 之后 `/api/sync` 只剩取列表（≈1 分钟、5 个桶位），那 ≈1,700s 的净值/行情批次
 * 搬进了本模块 ⇒ "重复触发会烧额度"这件事的落点随之搬到这里（#23(v)）。
 * 磁盘判据正好是刀 1 为 #22(b) 装的那一列 `snapshotAt`：**新鲜度标记与幂等判据是同一列**，
 * 这是那条决定之外的第二个用途，也是"陈旧才说话"必须真实可信的原因——
 * 一旦这句话能上屏，它同时就在给闸门当值。
 *
 * 跳过时 `updated/failedBatches` 都记 0（本轮确实一批都没发），`snapshotAt` 回填库里
 * **已有**的那个时刻而不是新时刻：状态位不能因为"有人问了一次"就把自己说成刚刷过。
 */
async function _refreshGated(type: string, force: boolean): Promise<SnapshotResult> {
  if (!force) {
    const doneAt = await snapshotRefreshedToday(type);
    if (doneAt) {
      // CR9-61（乙＝可续跑）：`snapshotAt` 只能证明"这一行今天被碰过"，证明不了"这一类跑完了"。
      // 10-04 那轮 fund 的 `snapshotAt` 落在第 35 批就断了 ⇒ 只按旧判据会整天挡下，
      // 而库里 28,013 只里只有 3,500 只有价——"补一次"这件事在那个判据下根本没有入口。
      if (!hasCompletionLedger()) {
        // 空账本＝这台机还没跑过含本刀的刷新轮 ⇒ **退回旧判据**（叠加而非替换的另一半）。
        // 不退回的后果是部署当天每一类都成了"没跑完"⇒ 整轮重刷，那是凭空多烧的额度，不是续跑。
        return skipResult(
          type,
          doneAt,
          `今日已刷新（快照时刻 ${beijingStamp(doneAt)}；完成账本还是空的 ⇒ 按快照时刻挡下），本轮不重复取数；确要重刷带 ?force=1`,
        );
      }
      if (completedToday(type)) {
        const at = lastCompletedAt(type);
        return skipResult(
          type,
          doneAt,
          `今日已刷新（快照时刻 ${beijingStamp(doneAt)}，整轮跑完于${at ? beijingStamp(new Date(at)) : "未知时刻"}），本轮不重复取数；确要重刷带 ?force=1`,
        );
      }
      // 走到这里＝今日有快照时刻、但这一类今日**没跑完过** ⇒ 放行续跑。
      // ⚠️ 粒度要说清：续跑＝**整类重跑**（`refreshSnapshotInner` 没有批次游标），
      // 所以那 35 批已付的会连同剩下 245 批一起再付一遍——这是它的代价，不藏着。
      // 仍**不新增自动重试**（CR9-28"失败批次不自动重试"被 `test_c3_readtimeout` 钉着）：
      // 本刀只让"下一次触发"变成续跑，夜跑链照旧是一轮。
      console.log(`[market-snapshot] resuming interrupted type=${type} (snapshotAt 今日但整轮未跑完)`);
      const r = await refreshSnapshotInner(type);
      return { ...r, resumed: true };
    }
  }
  return refreshSnapshotInner(type);
}

/** 被 #23 挡下时的那份返回：本轮一批都没发，所以 `updated/failedBatches` 记 0，
 *  而 `snapshotAt` 回填库里**已有**的时刻（状态位不许因为"有人问了一次"就撒谎）。 */
function skipResult(type: string, doneAt: Date, skippedReason: string): SnapshotResult {
  return {
    type,
    total: 0,
    updated: 0,
    failedBatches: 0,
    tookMs: 0,
    snapshotAt: doneAt.toISOString(),
    skipped: true,
    skippedReason,
  };
}

async function refreshSnapshotInner(type: string): Promise<SnapshotResult> {
  const started = Date.now();
  // 一次刷新一个时刻（不是每批各取一次）⇒ 同批全部行可比对；写失败的批次不写，
  // 所以 `snapshotAt` 表达的是"这一行的快照最早可能新到这个时刻"（刀 1/#22(b)）。
  const snapshotAt = new Date();
  const products = await prisma.product.findMany({
    where: { type },
    select: { code: true },
    orderBy: { code: "asc" },
  });
  const total = products.length;
  if (total === 0) {
    return {
      type,
      total: 0,
      updated: 0,
      failedBatches: 0,
      tookMs: Date.now() - started,
      snapshotAt: null,
    };
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
        await updateChunk(type, rows, snapshotAt);
        updated += rows.length;
      }
    } catch {
      failedBatches += 1;
    }
    if (EM_SNAPSHOT_TYPES.has(type) && i + BATCH < total) {
      await sleep(EM_BATCH_DELAY_MS);
    }
  }
  return {
    type,
    total,
    updated,
    failedBatches,
    tookMs: Date.now() - started,
    snapshotAt: updated > 0 ? snapshotAt.toISOString() : null,
  };
}

export async function refreshAll(
  types: string[],
  opts: { force?: boolean; onResult?: (r: SnapshotResult) => void } = {},
): Promise<SnapshotResult[]> {
  // #33 甲：每完成一类就回调一次（进度状态位要**边跑边落盘**，等证据自己攒完就晚了）。
  // `onResult` 留在调用方手里而不让本模块直接写文件，是为了让这条刷新链仍然可单测、
  // 也让"谁拥有这一轮"这件事继续在路由层说清（路由才是那轮刷新的一条腿）。
  const { onResult, ...inner } = opts;
  const results: SnapshotResult[] = [];
  for (const t of types) {
    const r = await refreshSnapshot(t, inner);
    results.push(r);
    onResult?.(r);
  }
  return results;
}
