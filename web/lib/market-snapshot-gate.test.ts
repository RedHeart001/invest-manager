import { beforeEach, describe, expect, it, vi } from "vitest";

// #23 当日幂等闸门的**刷新腿**这一侧——甲-1 之后真正贵的那条腿在这里
// （10-01 实测：fund 的 280 个净值批次单独 ≈1,700s，而 `/api/sync` 只剩取列表 ≈1 分钟）。
// 所以"重复触发会烧额度"这件事的落点随结构一起搬了过来（#23(v)），判据用的是
// 刀 1 为 #22(b) 装的那一列 `snapshotAt`：**新鲜度标记与幂等判据是同一列**。
// 闸门语义本身的用例（日界、逐类粒度）在 `lib/freshness.test.ts`，这里只测"挡下时不动作"。

const findMany = vi.fn();
const executeRawUnsafe = vi.fn();
const fetchQuotes = vi.fn();
const snapshotRefreshedToday = vi.fn();

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

import { refreshAll, refreshSnapshot } from "./market-snapshot";

function codes(n: number) {
  return Array.from({ length: n }, (_, i) => ({ code: String(600000 + i) }));
}
function quoteMap(rows: { code: string }[]) {
  return Object.fromEntries(rows.map((r) => [r.code, { price: 10.5, changePct: 1.2 }]));
}

describe("刷新腿的当日幂等闸门（#23）", () => {
  beforeEach(() => {
    findMany.mockReset().mockResolvedValue(codes(2));
    executeRawUnsafe.mockReset().mockResolvedValue(1);
    fetchQuotes.mockReset();
    snapshotRefreshedToday.mockReset().mockResolvedValue(null); // 默认：今日没刷过 ⇒ 放行
  });

  it("今日已刷过 ⇒ 零次出网、零条写库，且 snapshotAt 回填库里已有的那个时刻", async () => {
    const existing = new Date("2026-10-01T18:20:00.000Z"); // 北京 10-02 02:20
    snapshotRefreshedToday.mockResolvedValue(existing);
    const r = await refreshSnapshot("fund");
    expect(fetchQuotes).not.toHaveBeenCalled();
    expect(executeRawUnsafe).not.toHaveBeenCalled();
    expect(findMany).not.toHaveBeenCalled(); // 连"要刷哪些代码"都不必查
    expect(r.skipped).toBe(true);
    expect(r.updated).toBe(0);
    expect(r.failedBatches).toBe(0);
    // 关键：不得因为"有人问了一次"就把自己说成刚刷过
    expect(r.snapshotAt).toBe(existing.toISOString());
    expect(r.skippedReason).toContain("今日已刷新");
    expect(r.skippedReason).toContain("force");
  });

  it("🔁 反向：今日没刷过 ⇒ 照常跑完整刷新，并写入一个新时刻", async () => {
    fetchQuotes.mockResolvedValue(quoteMap(codes(2)));
    const r = await refreshSnapshot("stock");
    expect(fetchQuotes).toHaveBeenCalledTimes(1);
    expect(executeRawUnsafe).toHaveBeenCalledTimes(1);
    expect(r.skipped).toBeUndefined();
    expect(r.updated).toBe(2);
    expect(r.snapshotAt).not.toBeNull();
    expect(Date.parse(String(r.snapshotAt))).toBeGreaterThan(Date.now() - 60_000);
  });

  it("🔁 反向：?force=1 越过闸门，连那次判据读库都不发生（主人手测前要重刷数据）", async () => {
    snapshotRefreshedToday.mockResolvedValue(new Date());
    fetchQuotes.mockResolvedValue(quoteMap(codes(2)));
    const r = await refreshSnapshot("bond", { force: true });
    expect(snapshotRefreshedToday).not.toHaveBeenCalled();
    expect(r.skipped).toBeUndefined();
    expect(fetchQuotes).toHaveBeenCalledTimes(1);
  });

  it("type=all 时逐类各自判：被挡的类不出网，缺快照的类照常补", async () => {
    snapshotRefreshedToday.mockImplementation(async (t: unknown) =>
      t === "stock" || t === "fund" ? new Date() : null,
    );
    fetchQuotes.mockResolvedValue(quoteMap(codes(2)));
    const rs = await refreshAll(["stock", "fund", "bond", "crypto", "hk"]);
    expect(rs.filter((r) => r.skipped).map((r) => r.type)).toEqual(["stock", "fund"]);
    // 只有"今日还没刷过"的三类各发一次批量行情
    expect(fetchQuotes).toHaveBeenCalledTimes(3);
    expect(rs.find((r) => r.type === "bond")?.skipped).toBeUndefined();
  });

  it("单飞不被闸门带没：同类型并发共享同一次结果", async () => {
    fetchQuotes.mockResolvedValue(quoteMap(codes(2)));
    const [a, b] = await Promise.all([refreshSnapshot("stock"), refreshSnapshot("stock")]);
    expect(fetchQuotes).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
  });
});
