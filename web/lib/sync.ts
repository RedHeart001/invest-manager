// 产品主数据同步：data-service 拉全量 → SQLite 落库 → 重建 FTS 索引
// 约定（PLAN.md）：data-service 无状态、不写库；一切持久化由 BFF 负责。

import { randomUUID } from "node:crypto";

import { dsGet } from "./data-service";
import { refreshSnapshot } from "./market-snapshot";
import { prisma } from "./prisma";
import { buildSearchText } from "./search-text";

export const SYNC_TYPES = ["stock", "fund", "bond", "crypto"] as const;
export type SyncType = (typeof SYNC_TYPES)[number];

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
  await prisma.$executeRawUnsafe(
    `CREATE TABLE IF NOT EXISTS "${table}" (
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
  const started = Date.now();
  try {
    const data = await dsGet<{ count: number; products: ProductPayload[] }>(
      "/products",
      { type },
      180_000,
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

    // L1（O4）：重活移出主表写锁窗口——
    //   ① 先把全量数据写入分型暂存表（逐批自动提交，不持长锁）
    //   ② 再用一个小事务做"删旧 + 服务端批量拷入"（3 万行约 1~2s）
    // 此前单事务 deleteMany+createMany 会把写锁持有数分钟。
    const table = await ensureStageTable(type);
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
    // 暂存数据已拷入主表 → 直接 DROP（避免残留空表占用 sqlite_master；下次 CREATE IF NOT EXISTS 重建）
    await prisma.$executeRawUnsafe(`DROP TABLE IF EXISTS "${table}"`);

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
  try {
    await prisma.$executeRawUnsafe(
      `DELETE FROM Product_fts WHERE productId NOT IN (SELECT id FROM Product)`,
    );
    await prisma.$executeRawUnsafe(
      `DELETE FROM Product_fts WHERE productId IN (SELECT id FROM Product WHERE type = ?)`,
      type,
    );
    await prisma.$executeRawUnsafe(
      `INSERT INTO Product_fts(productId, searchText)
       SELECT id, COALESCE(searchText, '') FROM Product WHERE type = ?`,
      type,
    );
  } catch {
    // FTS5 虚表不存在时忽略；搜索层有 LIKE 兜底
  }
}

export async function syncAll(types: readonly string[] = SYNC_TYPES): Promise<SyncResult[]> {
  const results: SyncResult[] = [];
  for (const t of types) {
    results.push(await syncType(t));
  }
  return results;
}
