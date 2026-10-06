/**
 * CR9-67（丙）离线单测：刷新腿的**逐批限速**——睡不睡问的是「这一批打不打东财」。
 *
 * 为什么单独一个文件：`market-snapshot-gate.test.ts` 钉的是当日幂等**闸门**（挡不挡），
 * 每个类型只跑 1 个批次，本来就碰不到批间隔；这里钉的是**循环里那一行 `sleep`**。
 *
 * 实测依据（10-06 10:2x 直读 `dev.db`，零出网）＝fund 28,013 行切 281 批，其中**只有 31 批**
 * 含场内代码 ⇒ 之前每轮那 280 个 5 秒里有 **249 个（1,245s）付给的是不占东财桶的场外净值批次**。
 * 本刀不改任何秒数（`EM_BATCH_DELAY_MS=5000` 等于桶自己的放行速率，CR9-9 钉着），
 * 只把「为哪些批次睡」从按类型名猜改成问 ds（`/quotes` 的 `usesEastmoney`）。
 *
 * ⚠️ 这些用例**不等真睡眠**：`setTimeout` 被换成"记下毫秒数、立刻放行"，
 * 断言的是**睡不睡**与**睡了几批**，不是真等了 5 秒。
 *
 * #38 那一课（10-06 反向验证挖出来的）也写在这里：纯函数 `shouldPaceBatch` 绿**不等于**
 * 循环真的用了它 ⇒ 下面每条都从 `refreshSnapshot` 这一端读（接线面），
 * 而不是只调那个纯函数（`market-snapshot.test.ts` 才是钉纯函数三态的地方）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const findMany = vi.fn();
const executeRawUnsafe = vi.fn();
const fetchQuotes = vi.fn();
const snapshotRefreshedToday = vi.fn();
const hasCompletionLedger = vi.fn();
const completedToday = vi.fn();
const lastCompletedAt = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    product: {
      findMany: (...a: unknown[]) => findMany(...a),
      findFirst: vi.fn(async () => null),
    },
    $executeRawUnsafe: (...a: unknown[]) => executeRawUnsafe(...a),
  },
}));
vi.mock("./data-service", () => ({ fetchQuotes: (...a: unknown[]) => fetchQuotes(...a) }));
vi.mock("./freshness", () => ({
  snapshotRefreshedToday: (...a: unknown[]) => snapshotRefreshedToday(...a),
}));
// 进度状态位不落真文件：本文件只关心睡不睡，闸门那一半由 gate 套件钉
vi.mock("./refresh-progress", () => ({
  hasCompletionLedger: () => hasCompletionLedger(),
  completedToday: (...a: unknown[]) => completedToday(...a),
  lastCompletedAt: (...a: unknown[]) => lastCompletedAt(...a),
}));

import { EM_BATCH_DELAY_MS, refreshSnapshot } from "./market-snapshot";

const realSetTimeout = globalThis.setTimeout;
let delays: number[] = [];

/** 本轮真实"睡了"的批次数＝间隔≥5s 的那几次 `setTimeout`（其余是 mock/内部微延时） */
function pacedSleeps(): number[] {
  return delays.filter((d) => d >= EM_BATCH_DELAY_MS);
}

/** `n` 行标的（一批 100 只 ⇒ 350 行＝4 批，末批 50 只） */
function products(n: number) {
  return Array.from({ length: n }, (_, i) => ({ code: String(100000 + i) }));
}
/** 按 `markers` 逐批回 `usesEastmoney`（下标越界则重复最后一个），报价按**实际那批代码**给 */
function markersFor(markers: Array<boolean | null>) {
  let i = 0;
  return (_type: string, codes: unknown) => {
    const usesEastmoney = markers[Math.min(i, markers.length - 1)];
    i += 1;
    const list = Array.isArray(codes) ? (codes as string[]) : [];
    return Promise.resolve({
      quotes: Object.fromEntries(list.map((code) => [code, { price: 1.5, changePct: 0.2 }])),
      usesEastmoney,
    });
  };
}

describe("刷新腿的逐批限速（CR9-67／丙）", () => {
  beforeEach(() => {
    delays = [];
    vi.spyOn(globalThis, "setTimeout").mockImplementation(
      ((fn: (...args: unknown[]) => void, ms?: number) => {
        delays.push(ms ?? 0);
        return realSetTimeout(fn, 0);
      }) as unknown as typeof setTimeout,
    );
    findMany.mockReset().mockResolvedValue(products(350)); // 4 批，末批不睡 ⇒ 最多睡 3 次
    executeRawUnsafe.mockReset().mockResolvedValue(1);
    fetchQuotes.mockReset();
    snapshotRefreshedToday.mockReset().mockResolvedValue(null); // 默认：今日没刷过 ⇒ 真跑循环
    hasCompletionLedger.mockReset().mockReturnValue(true);
    completedToday.mockReset().mockReturnValue(false);
    lastCompletedAt.mockReset().mockReturnValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fund 四批全是场外 ⇒ 一次都不睡，而读数说得出「4 批里睡了 0 批」", async () => {
    fetchQuotes.mockImplementation(markersFor([false, false, false, false]));
    const r = await refreshSnapshot("fund");
    expect(fetchQuotes).toHaveBeenCalledTimes(4); // 循环真的按 100 一批走了 4 趟
    expect(pacedSleeps()).toEqual([]);
    expect(r.batches).toBe(4);
    expect(r.pacedBatches).toBe(0);
    expect(r.updated).toBe(350); // 不睡不等于没刷：350 行照常写库
  });

  it("🔁 含场内的批次照旧各睡 5 秒，末批仍不睡尾延（丙没把既有规则带跑）", async () => {
    fetchQuotes.mockImplementation(markersFor([false, true, true, false]));
    const r = await refreshSnapshot("fund");
    expect(pacedSleeps()).toEqual([EM_BATCH_DELAY_MS, EM_BATCH_DELAY_MS]);
    expect(r.batches).toBe(4);
    expect(r.pacedBatches).toBe(2);
  });

  it("问不出路由（老 ds 没这个键／那次取数没成功）⇒ 循环退回旧的每类型表：stock 睡满、crypto 一睡都没有", async () => {
    fetchQuotes.mockImplementation(markersFor([null, null, null, null]));
    const stock = await refreshSnapshot("stock"); // 在回落表里 ⇒ 睡 3 次（末批除外）
    expect(pacedSleeps().length).toBe(3);
    expect(stock.pacedBatches).toBe(3);
    delays = [];
    const crypto = await refreshSnapshot("crypto"); // 不在表里 ⇒ 一次都不睡
    expect(pacedSleeps()).toEqual([]);
    expect(crypto.pacedBatches).toBe(0);
  });

  it("🔁 标记优先于类型名：stock 被告知不打东财就真的不睡、crypto 被告知要打就睡", async () => {
    fetchQuotes.mockImplementation(markersFor([false, false, false, false]));
    const stock = await refreshSnapshot("stock");
    expect(pacedSleeps()).toEqual([]);
    expect(stock.pacedBatches).toBe(0);
    delays = [];
    fetchQuotes.mockImplementation(markersFor([true, true, true, true]));
    const crypto = await refreshSnapshot("crypto"); // `crypto` 不在回落表里——这一条只可能由标记点亮
    expect(pacedSleeps().length).toBe(3);
    expect(crypto.pacedBatches).toBe(3);
  });

  it("被 #23 挡下的轮次把两个读数写成 0 而不是留空（逐类相加时才不会出现『这一类没数』）", async () => {
    snapshotRefreshedToday.mockResolvedValue(new Date());
    completedToday.mockReturnValue(true);
    fetchQuotes.mockImplementation(markersFor([true]));
    const r = await refreshSnapshot("fund");
    expect(r.skipped).toBe(true);
    expect(fetchQuotes).not.toHaveBeenCalled();
    expect(pacedSleeps()).toEqual([]);
    expect(r.batches).toBe(0);
    expect(r.pacedBatches).toBe(0);
  });
});
