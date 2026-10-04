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
// CR9-61（乙＝可续跑）：闸门的第二半判据住在刷新腿的进度状态位里，所以它也必须被自己控住——
// 默认"账本存在 且 这一类今天跑完过"，让上面那批 #23 的既有用例照旧按旧语义走。
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
vi.mock("./refresh-progress", () => ({
  hasCompletionLedger: () => hasCompletionLedger(),
  completedToday: (...a: unknown[]) => completedToday(...a),
  lastCompletedAt: (...a: unknown[]) => lastCompletedAt(...a),
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
    hasCompletionLedger.mockReset().mockReturnValue(true); // 默认：完成账本存在（本刀之后的常态）
    completedToday.mockReset().mockReturnValue(true); // 默认：这一类今日真跑完过 ⇒ 挡
    lastCompletedAt.mockReset().mockReturnValue("2026-10-04T18:20:00.000Z");
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

  // ---------- CR9-61（乙＝可续跑）：闸门的第二半判据 ----------

  it("CR9-61：今日有快照时刻**且**账本说这一类跑完过 ⇒ 挡下，原因里带『整轮跑完于』", async () => {
    snapshotRefreshedToday.mockResolvedValue(new Date("2026-10-03T18:20:00.000Z"));
    const r = await refreshSnapshot("stock");
    expect(r.skipped).toBe(true);
    expect(fetchQuotes).not.toHaveBeenCalled();
    expect(r.skippedReason).toContain("整轮跑完于");
  });

  it("CR9-61🔁：今日有快照时刻但账本里没有它 ⇒ 放行续跑（这正是 10-04 fund 那 35/280 批的形态）", async () => {
    snapshotRefreshedToday.mockResolvedValue(new Date("2026-10-03T18:08:00.000Z"));
    completedToday.mockReturnValue(false); // 被打断的那一类：库里时刻是今日，整轮却没跑完
    fetchQuotes.mockResolvedValue(quoteMap(codes(2)));
    const r = await refreshSnapshot("fund");
    expect(r.skipped).toBeUndefined();
    expect(r.resumed).toBe(true);
    expect(fetchQuotes).toHaveBeenCalledTimes(1); // 续跑＝真的再取数，不是又挡一次
    expect(executeRawUnsafe).toHaveBeenCalledTimes(1);
  });

  it("CR9-61：续跑粒度是整类重跑，而**跑完这一次就把账本补上** ⇒ 同日再触发被挡（不会成环）", async () => {
    snapshotRefreshedToday.mockResolvedValue(new Date("2026-10-03T18:08:00.000Z"));
    fetchQuotes.mockResolvedValue(quoteMap(codes(2)));
    completedToday.mockReturnValueOnce(false).mockReturnValue(true); // 第一次没跑完记录，重跑后补上
    const first = await refreshSnapshot("fund");
    const second = await refreshSnapshot("fund");
    expect(first.resumed).toBe(true);
    expect(second.skipped).toBe(true);
    expect(fetchQuotes).toHaveBeenCalledTimes(1); // 只补一次，不自动重试成环（CR9-28 那条不改判）
  });

  it("CR9-61🔁：账本是空的（这台机还没跑过含本刀的轮）⇒ 退回旧判据挡下，原因说清为什么", async () => {
    snapshotRefreshedToday.mockResolvedValue(new Date("2026-10-03T18:20:00.000Z"));
    hasCompletionLedger.mockReturnValue(false);
    const r = await refreshSnapshot("stock");
    expect(r.skipped).toBe(true);
    expect(fetchQuotes).not.toHaveBeenCalled(); // 部署当天不许变成"整轮重刷"（那是凭空多烧的额度）
    expect(r.skippedReason).toContain("完成账本还是空的");
    expect(completedToday).not.toHaveBeenCalled(); // 空账本这条分支根本不该去问第二类判据
  });

  it("CR9-61🔁：?force=1 时第二半判据一次都不问（越过闸门就是越过，不再逐条自查）", async () => {
    snapshotRefreshedToday.mockResolvedValue(new Date());
    fetchQuotes.mockResolvedValue(quoteMap(codes(2)));
    await refreshSnapshot("bond", { force: true });
    expect(hasCompletionLedger).not.toHaveBeenCalled();
    expect(completedToday).not.toHaveBeenCalled();
    expect(lastCompletedAt).not.toHaveBeenCalled();
  });
});
