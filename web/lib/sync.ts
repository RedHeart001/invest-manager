// 产品主数据同步：data-service 拉全量 → SQLite 落库 → 重建 FTS 索引
// 约定（PLAN.md）：data-service 无状态、不写库；一切持久化由 BFF 负责。

import { randomUUID } from "node:crypto";

import { dsGet } from "./data-service";
import { listSyncedToday } from "./freshness";
import { prisma } from "./prisma";
import { buildSearchText } from "./search-text";
import { beijingStamp } from "./time";

// G6（批次 D）：新增 hk（港股）
// CR9-59（2026-10-04，主人「#32 甲」的字）：新增 **us（美股主数据）**——只进同步阶梯，
// **不进刷新腿**（`app/api/market/refresh/route.ts:38` 的 `SNAPSHOT_TYPES` 是另一份名单，
// 没跟着长），因为主人这轮明确"先不用开美股 tab" ⇒ 没有分类浏览就没有 `lastPrice` 的消费方，
// 让夜跑去给几百只美股打现价是纯烧额度。也不进 `BROWSE_TYPES`（`lib/freshness.ts:27`）
// ⇒ 美股不出现在分类浏览，也就不需要给它配陈旧说明那一档。
export const SYNC_TYPES = ["stock", "fund", "bond", "crypto", "hk", "us"] as const;
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
  /** #23 当日幂等闸门：该类**今日已成功落过列表** ⇒ 本轮不动它（零出网、零写库）。
   *  刻意不算 `error`——web 的 `ok` 是 `results.every(r => !r.error)`，跳过不是失败；
   *  data-service 侧则按"整轮都是 skipped"给出 `outcome="skipped"`（第六态）。 */
  skipped?: boolean;
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

export async function syncType(
  type: string,
  opts: { force?: boolean } = {},
): Promise<SyncResult> {
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
  const run = _syncTypeGated(type, opts.force === true);
  syncInflight.set(type, run);
  try {
    return await run;
  } finally {
    if (syncInflight.get(type) === run) syncInflight.delete(type);
  }
}

/** #23 当日幂等闸门（同步腿这一侧，主人 2026-10-02 拍板"两道叠加"）
 *
 * 要治的形态：data-service 的 `lastDate` 是**内存**态且只管启动补跑那一条路，
 * ⇒ 过了 02:00 之后每重启一次 ds 就会再补跑一整轮（10-01 为跑门禁重启五次就是这形态，
 * 全靠 `SYNC_CATCHUP=off` 挡着，而那是测试开关、不是生产默认）。磁盘这一条补的是
 * "当天已经成功落过 ⇒ 连重启、手动、探针都不再来一次"——**叠加**在内存那条之上，
 * 所以 CR9-28「失败轮不自动重试」那两个被测试钉住的既有取舍不必改判。
 *
 * 判据取 `MAX(updatedAt)` 的**北京日**（`lib/freshness.ts`：list 阶段是整表删旧插新，
 * 这一列因此是"这一类的主数据什么时候换过"的唯一痕迹；快照刷新走 raw SQL 刻意不碰它）。
 * 逐类粒度还带来一个附带好处：一整轮里只有 stock 失败的日子，次日之前**单独**重跑 stock
 * 仍然放行，而其他四类不会被陪着再烧一遍额度。
 *
 * 出口 `?force=1`（#23(vi)）：没有它，"我今天就是要重刷一遍"会撞上自己的闸门。
 */
async function _syncTypeGated(type: string, force: boolean): Promise<SyncResult> {
  if (!force) {
    const doneAt = await listSyncedToday(type);
    if (doneAt) {
      return {
        type,
        skipped: true,
        note:
          `今日已同步（列表时刻 ${beijingStamp(doneAt)}），本轮不重复触发取数；` +
          "确要重跑带 ?force=1",
        tookMs: 0,
      };
    }
  }
  return _syncTypeInner(type);
}

async function _syncTypeInner(type: string): Promise<SyncResult> {
  const started = Date.now();
  let stageTableName: string | null = null;
  try {
    // 超时说明（2026-09-20）：港股列表必须分页（东财 `clist/get` 对港股忽略大分页参数，
    // 固定 100 条/页；约 4700 只 → 48 页），且每页经源族限速器（最小间隔 5s）
    // → 最坏约 4 分钟。原 180s 会在港股同步时必然超时，故放宽到 600s。
    const data = await dsGet<{
      count: number;
      products: ProductPayload[];
      // CR9-31：data-service 对列表载荷显式声明出网源（走内部备源时另带 degraded/note）。
      // 覆盖面因降级而缩水这件事，此前消费侧只能靠条数猜——见下面缩水保护那段。
      source?: string;
      degraded?: boolean;
      note?: string;
      // #35／CR9-63：上游声明"这一类本来就是有意取的子集"（不是上游劣化）。
      // 只有带这个声明的载荷才允许通过下面的缩水闸；未声明者原判据一字不动。
      intentionalSubset?: boolean;
    }>("/products", { type }, 600_000);
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
    //
    // #35／CR9-63（主人 10-05 取「甲」）：上面那句前提里藏着一个口径——"缩水"有两种成因，
    // ① 上游劣化（备源覆盖度不足，正是本闸要挡的）② 我们自己的产品口径（`us` 有意只取前排
    // N 页＋剔无行业 ⇒ 179 行 < 库里 300 行）。第二种过去被误读成第一种，于是**第二次起的
    // 每一次同步都挡回同一份名单**，美股主数据事实上停止更新。现在只有载荷**显式声明**
    // `intentionalSubset` 时才放行，未声明者本闸与原文案一字不动（`sync-shrink.test.ts`
    // 钉着的那条 G2 取舍不许放宽）；空载荷保护在更前面且不看声明 ⇒ 声明了但 0 行仍保留旧数据。
    const existingCount = await prisma.product.count({ where: { type } });
    let shrinkByDeclaration: string | null = null;
    if (existingCount > 0 && rows.length < existingCount * 0.7) {
      if (!data.intentionalSubset) {
        // CR9-31：上游已显式声明降级时，这里不再是"疑似"，而是带来源、带原话的诊断
        // （省掉一次去 data-service 日志里翻根因的功夫）；未声明时保留原有猜测口径。
        const cause = data.degraded
          ? `data-service 已声明降级：source=${data.source ?? "?"}——${data.note ?? "（无说明）"}`
          : "疑似降级备源覆盖度不足";
        return {
          type,
          error:
            `payload shrunk (${rows.length} < ${existingCount} 的 70%)，` +
            `${cause}，已保留现有数据`,
          tookMs: Date.now() - started,
        };
      }
      // 放行不等于不留痕：整表删旧插新会把 121 行没有行业的主数据换掉，这是已认下的代价
      // （#32 的 (2)＝主人 10-04 定案），但必须在结果里说得出，不能让它长得像一次正常替换。
      shrinkByDeclaration = `按上游声明放行有意子集（旧 ${existingCount} → 新 ${rows.length}）`;
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
    // 刀 3/甲-1（2026-10-02）：**这里不再刷行情快照**。R14 的刷新曾是同步事务的收尾一步
    // （旧 `:231` 紧邻 `refreshSnapshot(type)`），代价实测：10-01 一轮里 fund 的 280 个
    // 净值批次单独吃掉 ≈1,700s，把整轮 wall 顶到 ≥1800s ＝ 打穿 ds 侧回调预算 ⇒ 每晚
    // 02:00 都以"读超时（结果未知）"收尾。现在两条腿各拿各的预算：本端点只取列表，
    // 刷新由 **ds 在同步腿收尾后链式触发** `POST /api/market/refresh?type=all`
    // （预算 `sync_scheduler.REFRESH_CALLBACK_TIMEOUT_S`）。
    // ⚠️ 拆腿带来的窗口（有意接受）：整表删旧插新 ⇒ 新行的 lastPrice/lastChangePct 必为
    // null，直到刷新腿跑完才有价；这段时间分类浏览是"无价"而不是"陈旧价"。
    // CR9-31（R16）：载荷被上游声明为降级来源时，即便条数过了缩水闸门也要留痕——
    // 否则"327 只转债入库"与全量同步长得一模一样，分类浏览的覆盖面缺口没人说得清。
    let note: string | undefined;
    if (data.degraded) {
      note = `list degraded source=${data.source ?? "?"}${data.note ? `：${data.note}` : ""}`;
    }
    // #35／CR9-63：按"有意子集"声明放行过一次缩水，就要在结果里留下这笔账
    // （否则"300 行换成 179 行"与一次正常替换在回执里长得一模一样）。
    if (shrinkByDeclaration) {
      note = note ? `${note}；${shrinkByDeclaration}` : shrinkByDeclaration;
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

export async function syncAll(
  types: readonly string[] = SYNC_TYPES,
  opts: { force?: boolean } = {},
): Promise<SyncResult[]> {
  const results: SyncResult[] = [];
  for (const t of types) {
    results.push(await syncType(t, opts));
  }
  return results;
}
