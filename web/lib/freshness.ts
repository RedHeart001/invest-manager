// 「这一类数据是什么时候动的」——一个判据、两个用途
//
// 用途一（#23 当日幂等闸门，主人 2026-10-02 拍板"两道叠加"）：
//   同一台机上的任何东西（定时／手动／重启补跑／我自己的探针）随时能再触发一轮
//   30–40 分钟的取数并烧掉东财额度，而 data-service 的 `lastDate` 是**内存态** ⇒
//   过了 02:00 之后每重启一次 ds 就会再补跑一整轮（10-01 为跑门禁重启五次就是这形态）。
//   内存那条继续管"同进程内当天只试一次（含失败轮）"，本文件这条管"当天成功过 ⇒
//   连重启也不再重复"——**叠加而不是替换**，所以 CR9-28「失败轮不自动重试」那两条
//   被测试钉住的既有取舍一个字都不用改判。
//
// 用途二（#22(b) 快照新鲜度 ＋ #25 stock 主数据陈旧 ＋ CR9-57 的价格缺口，同一条判据、
//   同一处文案）：有问题才说话，正常态一行字都不出。
//
// 为什么看这两列时刻（`Product`）——第三条判据要多看一列 `lastPrice`，理由写在 `Freshness.maxPrice` 上：
//   · `updatedAt`＝Prisma 的 `@updatedAt`，只被 list 阶段的**整表删旧插新**推动
//     ⇒ 它是"主数据什么时候换过"的唯一痕迹；
//   · `snapshotAt`＝刷新腿（`/api/market/refresh`）整批写入的收尾时刻，raw SQL 刻意
//     **不碰** `updatedAt`（否则"主数据变更"与"快照变更"两种语义会混进同一列，
//     而 10-01 那轮的逐类归因正是靠 `max(updatedAt)` 反推出来的）。
//   ⇒ 两列各管一条腿，闸门与陈旧说明才分得清"哪条腿今天动过"。

import { prisma } from "./prisma";
import { beijingDateOf, beijingToday } from "./time";

/** 分类浏览有 tab 的类型（见 `app/search/search-client.tsx` 的 `TABS`）。
 *  陈旧说明只报这几类：`us` 有主数据却没有入口 ⇒ 报一句会把人引向一个不存在的 tab。 */
export const BROWSE_TYPES = ["stock", "fund", "bond", "crypto", "hk"] as const;

export type Freshness = {
  type: string;
  listAt: Date | null;
  snapAt: Date | null;
  /** 该类**有没有一个价格**（`MAX(lastPrice)`）。不能拿 `snapshotAt` 代替它——
   *  crypto 的 250 行在库里就是"有价而 `snapshotAt` 为 null"（09-27 由当时的列表阶段
   *  直接把价写进 `lastPrice`，而 `snapshotAt` 这列是刀 1 之后才加的）。
   *  ⇒ 两列要一起看，否则那一类会被误报成"价格还没跟上"（CR9-57）。 */
  maxPrice: number | null;
};

/** 逐类的新鲜度面（一次 `groupBy` 取齐三列，比多次全表扫省一半以上） */
export async function freshnessOfTypes(where: { type?: string } = {}): Promise<Freshness[]> {
  const rows = await prisma.product.groupBy({
    by: ["type"],
    where,
    _max: { updatedAt: true, snapshotAt: true, lastPrice: true },
  });
  return rows.map((r) => ({
    type: r.type,
    listAt: r._max.updatedAt ?? null,
    snapAt: r._max.snapshotAt ?? null,
    maxPrice: r._max.lastPrice ?? null,
  }));
}

/** 某类**今日**（北京日界）已成功落过列表 ⇒ 返回那个时刻；否则 null。
 *
 * `updatedAt DATETIME NOT NULL` ⇒ 只要该类有行就能取到最大值；空表（如 hk 列表未到货）
 * 走不到这条判据——"0 行"在页面上表现为该类无内容，不需要一句陈旧说明。
 */
export async function listSyncedToday(type: string): Promise<Date | null> {
  const row = await prisma.product.findFirst({
    where: { type },
    orderBy: { updatedAt: "desc" },
    select: { updatedAt: true },
  });
  return row && beijingDateOf(row.updatedAt) === beijingToday() ? row.updatedAt : null;
}

/** 某类**今日**（北京日界）刷过快照 ⇒ 返回那个时刻；否则 null。
 *  这是贵的那条腿（10-01 实测 fund 的 280 个净值批次单独 ≈1,700s）真正的重复触发风险点。 */
export async function snapshotRefreshedToday(type: string): Promise<Date | null> {
  const row = await prisma.product.findFirst({
    where: { type },
    orderBy: { snapshotAt: "desc" },
    select: { snapshotAt: true },
  });
  return row?.snapshotAt && beijingDateOf(row.snapshotAt) === beijingToday()
    ? row.snapshotAt
    : null;
}

export type StaleNote = { type: string; kind: "list" | "snapshot" | "pending"; since: string };

/** 昨日（北京日界）——**给 1 天宽限**：休市日与"服务停了一晚"都不该报陈旧，
 *  否则 10-02 这种国庆休市日会天天出字，那句话就失去判别力了。 */
function previousDay(day: string): string {
  return new Date(new Date(`${day}T00:00:00Z`).getTime() - 86_400_000).toISOString().slice(0, 10);
}

/** 陈旧／缺口说明（纯函数，便于把日界与"正常态不出字"都钉成断言）
 *
 * 三条规则各管一种成因，**同一类只报一条**（优先级 `list` ＞ `pending` ＞ `snapshot`）：
 *  · `listAt` 早于昨日 ⇒ 「主数据未更新」——列表是主数据（名称/代码/币种）之源，
 *    它旧了会连带 CR8-8 那类"按库内权威名判退市"的前提一起变旧（#25 的牵动项）。
 *  · 该类**一个价都没有**（`snapshotAt` 与 `lastPrice` 双双为 null）⇒ 「价格还没跟上」。
 *    这一档是 CR9-57（主人 10-03 拍板"那句要上屏"）补进来的：刀 3 拆腿后列表阶段会把
 *    新行价格写成 null（`sync.test.ts` 钉着那个窗口），刷新腿还没跑到之前用户看到的
 *    就是**一整列空白＋一句话都没有**——10-03 实测那个形态挂了约 20 小时。
 *    它**不是陈旧**，所以措辞不许用"未更新"；它也不许承诺"正在刷新"（刷新腿可能整晚
 *    没跑，那是第二种谎）⇒ 只锚在两个用户能自己核对的事实上：名单什么时候换的、
 *    这一列现在是空的。判据要 `snapshotAt` 与 `lastPrice` 两列一起看，理由见 `Freshness.maxPrice`。
 *  · `snapAt` 早于昨日 ⇒ 「价格快照未更新」。
 *
 * **本函数不截断**：条数上限属于渲染层（CR8-1「一批最多两条」），归 `browse.ts` 与前端，
 * 因为它们要一并说出"还有几条"。在这里 `slice(0,2)` 会把第三类**静默丢掉**——
 * 10-02 的活体探针正好撞上：stock／bond／crypto 三类同日陈旧，屏上只剩两条，
 * 被藏掉的那一条恰恰是这句话要防的那种"看不见的降级"（R16）。
 */
export function staleNotes(rows: Freshness[], today: string = beijingToday()): StaleNote[] {
  const cutoff = previousDay(today);
  const notes: StaleNote[] = [];
  for (const type of BROWSE_TYPES) {
    const row = rows.find((r) => r.type === type);
    if (!row) continue;
    if (row.listAt && beijingDateOf(row.listAt) < cutoff) {
      notes.push({ type, kind: "list", since: beijingDateOf(row.listAt) });
    } else if (row.listAt && !row.snapAt && row.maxPrice === null) {
      notes.push({ type, kind: "pending", since: beijingDateOf(row.listAt) });
    } else if (row.snapAt && beijingDateOf(row.snapAt) < cutoff) {
      notes.push({ type, kind: "snapshot", since: beijingDateOf(row.snapAt) });
    }
  }
  return notes;
}
