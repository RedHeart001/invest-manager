// 产品主数据同步：data-service 拉全量 → SQLite 落库 → 重建 FTS 索引
// 约定（PLAN.md）：data-service 无状态、不写库；一切持久化由 BFF 负责。

import { randomUUID } from "node:crypto";

import { dsGet } from "./data-service";
import { refreshSnapshot } from "./market-snapshot";
import { prisma } from "./prisma";
import { buildSearchText } from "./search-text";

// G6（批次 D）：新增 hk（港股）——data-service 已提供 provider 与列表接口
export const SYNC_TYPES = ["stock", "fund", "bond", "crypto", "hk"] as const;
export type SyncType = (typeof SYNC_TYPES)[number];

// 分型同步单飞锁（C17：进程内单例挂 globalThis，避免 dev HMR 重建模块作用域后失效）
const SYNC_INFLIGHT_KEY = Symbol.for("invest-manager.sync.inflight");
const syncInflight: Map<string, Promise<SyncResult>> = ((
  globalThis as unknown as Record<symbol, Map<string, Promise<SyncResult>> | undefined>
)[SYNC_INFLIGHT_KEY] ??= new Map());

type ProductPayload = {
  type: string;
  code: string;
  name: string;
  pinyin?: string | null;
  pinyinInitials?: string | null;
  exchange?: string | null;
  tags?: string[] | null;
};

export type SyncResult = {
  type: string;
  count?: number;
  error?: string;
  note?: string;
  tookMs: number;
};

const CHUNK = 500;

const PRODUCT_COLS = [
  "id",
  "type",
  "code",
  "name",
  "pinyin",
  "pinyinInitials",
  "exchange",
  "tags",
  "sector",
  "searchText",
  "lastPrice",
  "lastChangePct",
  "updatedAt",
] as const;

/** L1：分型暂存表（app 管理，与 Product_fts 同模式），把重活移出主表写锁窗口 */
function stageTable(type: string): string {
  if (!(SYNC_TYPES as readonly string[]).includes(type)) {
    throw new Error(`invalid sync type: ${type}`);
  }
  return `Product_stage_${type}`;
}

async function ensureStageTable(type: string): Promise<string> {
  const table = stageTable(type);
  // CR4（P3）：先 DROP 再 CREATE——`IF NOT EXISTS` 只建不校验，若进程崩溃残留的暂存表
  // schema 已演进（列名/列数不符），后续 `INSERT ... SELECT` 会持续报错使该类型同步失败。
  // 暂存表在下述流程中被 fully 重建并最终 DROP，故先删后建是安全的（表名受 SYNC_TYPES 约束，无注入面）。
  await prisma.$executeRawUnsafe(`DROP TABLE IF EXISTS "${table}"`);
  await prisma.$executeRawUnsafe(
    `CREATE TABLE "${table}" (
      "id" TEXT NOT NULL PRIMARY KEY,
      "type" TEXT NOT NULL,
      "code" TEXT NOT NULL,
      "name" TEXT NOT NULL,
      "pinyin" TEXT,
      "pinyinInitials" TEXT,
      "exchange" TEXT,
      "tags" TEXT,
      "sector" TEXT,
      "searchText" TEXT,
      "lastPrice" REAL,
      "lastChangePct" REAL,
      "updatedAt" DATETIME NOT NULL
    )`,
  );
  return table;
}

export async function syncType(type: string): Promise<SyncResult> {
  // 并发保护（2026-09-13 code review）：分型暂存表名是固定的 Product_stage_<type>，
  // 两次同类型并发同步会互相清除对方写入的暂存行 → 事务可能只拷入不完整集合，
  // 造成 Product 表该类型数据丢失。`/api/sync` 可被定时任务与手动同时触发，故加单飞。
  //
  // 修复（2026-09-14 code review）：此前实现是"等待前一次完成后再各自重跑一次"——
  // 只是串行化，并发 N 次仍会跑 N 次完整同步（各 180s 取数 + 全量写库 + FTS 重建）。
  // 正确的单飞是**返回同一个 in-flight Promise**，让并发调用共享同一次结果。
  // （_syncTypeInner 内部已 try/catch 永不 reject，直接返回该 Promise 语义正确。）
  const inflight = syncInflight.get(type);
  if (inflight) return inflight;
  const run = _syncTypeInner(type);
  syncInflight.set(type, run);
  try {
    return await run;
  } finally {
    if (syncInflight.get(type) === run) syncInflight.delete(type);
  }
}

async function _syncTypeInner(type: string): Promise<SyncResult> {
  const started = Date.now();
  let stageTableName: string | null = null;
  try {
    // 超时说明（2026-09-20）：港股列表必须分页（东财 `clist/get` 对港股忽略大分页参数，
    // 固定 100 条/页；约 4700 只 → 48 页），且每页经源族限速器（最小间隔 5s）
    // → 最坏约 4 分钟。原 180s 会在港股同步时必然超时，故放宽到 600s。
    const data = await dsGet<{ count: number; products: ProductPayload[] }>(
      "/products",
      { type },
      600_000,
    );
    const rows = (data.products ?? []).map((p) => ({
      id: randomUUID(),
      type: p.type,
      code: p.code,
      name: p.name,
      pinyin: p.pinyin ?? null,
      pinyinInitials: p.pinyinInitials ?? null,
      exchange: p.exchange ?? null,
      tags: JSON.stringify(p.tags ?? []),
      sector: null,
      searchText: buildSearchText({
        name: p.name,
        code: p.code,
        pinyin: p.pinyin,
        pinyinInitials: p.pinyinInitials,
        tags: p.tags ?? [],
      }),
      lastPrice: null,
      lastChangePct: null,
      updatedAt: new Date(),
    }));

    // 空载荷保护（C1）：全量替换前必须判空——上游返回空列表时保留旧数据
    if (rows.length === 0) {
      return {
        type,
        error: "empty payload from data-service, existing data kept",
        tookMs: Date.now() - started,
      };
    }

    // 降级缩水保护（G2 引入，2026-09-20 集成验收发现）：
    // 全量替换语义是"新载荷 = 该类型完整集合"。但主源限流时会降级到**覆盖度更低**的
    // 备源（实测：转债东财 1052 只 → 新浪 cov_spot 仅 329 只），直接替换会把主数据
    // **缩小**（既有 1052 条被 329 条覆盖），属静默数据劣化。此处与现有条数比较，
    // 新载荷明显缩水（< 70%）时保留旧数据并显式标注，等主源恢复后再全量更新。
    const existingCount = await prisma.product.count({ where: { type } });
    if (existingCount > 0 && rows.length < existingCount * 0.7) {
      return {
        type,
        error:
          `payload shrunk (${rows.length} < ${existingCount} 的 70%)，` +
          `疑似降级备源覆盖度不足，已保留现有数据`,
        tookMs: Date.now() - started,
      };
    }

    // L1（O4）：重活移出主表写锁窗口——
    //   ① 先把全量数据写入分型暂存表（逐批自动提交，不持长锁）
    //   ② 再用一个小事务做"删旧 + 服务端批量拷入"（3 万行约 1~2s）
    // 此前单事务 deleteMany+createMany 会把写锁持有数分钟。
    const table = (stageTableName = await ensureStageTable(type));
    await prisma.$executeRawUnsafe(`DELETE FROM "${table}"`);
    const cols = PRODUCT_COLS.join('","');
    for (let i = 0; i < rows.length; i += CHUNK) {
      const batch = rows.slice(i, i + CHUNK);
      const placeholders = batch
        .map(() => `(${PRODUCT_COLS.map(() => "?").join(",")})`)
        .join(",");
      await prisma.$executeRawUnsafe(
        `INSERT INTO "${table}" ("${cols}") VALUES ${placeholders}`,
        ...batch.flatMap((r) => [
          r.id,
          r.type,
          r.code,
          r.name,
          r.pinyin,
          r.pinyinInitials,
          r.exchange,
          r.tags,
          r.sector,
          r.searchText,
          r.lastPrice,
          r.lastChangePct,
          r.updatedAt,
        ]),
      );
    }

    await prisma.$transaction(
      async (tx) => {
        await tx.$executeRawUnsafe(`DELETE FROM "Product" WHERE type = ?`, type);
        await tx.$executeRawUnsafe(
          `INSERT INTO "Product" ("${cols}")
           SELECT "${cols}" FROM "${table}"`,
        );
      },
      { timeout: 120_000, maxWait: 30_000 },
    );
    // 暂存表清理统一放到 finally（成功/失败都要 DROP，避免失败时残留全量数据）
    await rebuildFts(type);
    // R14：同步完成后刷新行情快照（分类浏览排序用；失败不影响同步结果）
    let note: string | undefined;
    try {
      const snap = await refreshSnapshot(type);
      note = `snapshot updated=${snap.updated}/${snap.total} failedBatches=${snap.failedBatches}`;
    } catch (e) {
      note = `snapshot failed: ${e instanceof Error ? e.message : "unknown"}`;
    }
    return { type, count: rows.length, note, tookMs: Date.now() - started };
  } catch (e) {
    return {
      type,
      error: e instanceof Error ? e.message : String(e),
      tookMs: Date.now() - started,
    };
  } finally {
    // 无论成功或失败都清理暂存表（2026-09-13 code review：此前失败路径不 DROP，
    // 会残留整份全量数据与空表）
    if (stageTableName) {
      try {
        await prisma.$executeRawUnsafe(`DROP TABLE IF EXISTS "${stageTableName}"`);
      } catch {
        // 清理失败不影响同步结果
      }
    }
  }
}

/** 重建某类型的 FTS 索引（表缺失时静默降级为 LIKE 检索）
 *
 * C15（2026-09-13）：必须先做**孤儿清理**——L1 全量替换会给产品生成全新 id，
 * 按「Product 表中 id」定位的 DELETE 无法命中旧 id 的 FTS 行 → 每次同步都会
 * 累积与该类型条数相等的孤儿行（实测 bond 一次同步即留下 1052 行孤儿）。
 * 孤儿清理与 type 无关且安全（仅删主表中已不存在的行）。
 */
export async function rebuildFts(type: string): Promise<void> {
  // CR-15（本轮 code review）：三条语句分步 try/catch——此前整段一个 try，
  // 第一条成功、后两条失败时 FTS 索引处于**半更新态**且无任何日志
  // （现象上搜索靠 LIKE 兜底，问题被静默）。此处逐步记录，暴露真实失败。
  try {
    await prisma.$executeRawUnsafe(
      `DELETE FROM Product_fts WHERE productId NOT IN (SELECT id FROM Product)`,
    );
  } catch (e) {
    console.warn(`[fts] 孤儿清理失败（${type}）:`, e instanceof Error ? e.message : e);
  }
  try {
    await prisma.$executeRawUnsafe(
      `DELETE FROM Product_fts WHERE productId IN (SELECT id FROM Product WHERE type = ?)`,
      type,
    );
    await prisma.$executeRawUnsafe(
      `INSERT INTO Product_fts(productId, searchText)
       SELECT id, COALESCE(searchText, '') FROM Product WHERE type = ?`,
      type,
    );
  } catch (e) {
    // FTS5 虚表不存在时忽略（搜索层有 LIKE 兜底）；其余情况记录，避免索引半更新静默
    console.warn(`[fts] 重建失败（${type}），本次搜索可能退化为 LIKE:`, e instanceof Error ? e.message : e);
  }
}

export async function syncAll(types: readonly string[] = SYNC_TYPES): Promise<SyncResult[]> {
  const results: SyncResult[] = [];
  for (const t of types) {
    results.push(await syncType(t));
  }
  return results;
}
