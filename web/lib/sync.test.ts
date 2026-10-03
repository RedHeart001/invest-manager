import { beforeEach, describe, expect, it, vi } from "vitest";

// 刀 3/甲-1（2026-10-02）：把"列表腿只写主数据、不写价格"钉成契约。
//
// 背景（10-01 实网窗口实测）：一轮同步 wall ≥1800s 打穿 ds 侧回调预算，而耗时主项不是取
// 5 张列表（只占头一分钟），是同步事务末尾那份快照刷新——**fund 的 280 个净值批次单独
// ≈1,700s**。⇒ 现在刷新拆成第二条腿，由 ds 在同步腿收尾后链式打
// `POST /api/market/refresh?type=all`，两条腿各拿各的预算。
//
// 拆腿的代价也必须被钉住：`_syncTypeInner` 是整表删旧插新，新行的
// `lastPrice/lastChangePct/snapshotAt` 全为 null ⇒ 从列表落库到刷新腿跑完之间，
// 分类浏览是"**无价**"而不是"吃陈旧价"。这两者在用户眼里不同，所以 #22(b) 的文案判据
// 用 `snapshotAt ?? updatedAt` 双列——本文件的断言就是那句判据的数据前提。

const count = vi.fn();
const executeRawUnsafe = vi.fn();
const transaction = vi.fn();
const refreshSnapshot = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    product: { count: (...a: unknown[]) => count(...a) },
    $executeRawUnsafe: (...a: unknown[]) => executeRawUnsafe(...a),
    $transaction: (...a: unknown[]) => transaction(...a),
  },
}));

const dsGet = vi.fn();
vi.mock("@/lib/data-service", () => ({ dsGet: (...a: unknown[]) => dsGet(...a) }));
// 刷新腿拆出去之后，本模块**不应再引用**它——留着 mock 是为了能断"没被调用"
vi.mock("./market-snapshot", () => ({ refreshSnapshot: (...a: unknown[]) => refreshSnapshot(...a) }));
// #23 当日幂等闸门的磁盘判据（`MAX(updatedAt)` 是否落在北京今日）——闸门语义的用例点名控制它
const listSyncedToday = vi.fn();
vi.mock("./freshness", () => ({ listSyncedToday: (...a: unknown[]) => listSyncedToday(...a) }));

import { SYNC_TYPES, syncType } from "./sync";

function products(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    type: "stock",
    code: String(600000 + i),
    name: `股${i}`,
  }));
}

/** 从暂存表 INSERT 语句里解析列名（不把 PRODUCT_COLS 的长度/下标抄进断言，避免双份真相） */
function stageInserts(): { cols: string[]; params: unknown[] }[] {
  return executeRawUnsafe.mock.calls
    .map((call) => ({ sql: String(call[0]), params: call.slice(1) }))
    .filter((c) => c.sql.includes('INSERT INTO "Product_stage_stock"'))
    .map((c) => ({
      cols: c.sql
        .slice(c.sql.indexOf("(") + 1, c.sql.indexOf(")"))
        .split(",")
        .map((s) => s.trim().replace(/"/g, "")),
      params: c.params.flat(),
    }));
}

describe("sync 列表腿与刷新腿拆分（刀 3/甲-1 契约）", () => {
  beforeEach(() => {
    count.mockReset().mockResolvedValue(0);
    executeRawUnsafe.mockReset().mockResolvedValue(0);
    transaction.mockReset().mockResolvedValue(undefined);
    dsGet.mockReset();
    refreshSnapshot.mockReset();
    listSyncedToday.mockReset().mockResolvedValue(null); // 默认：今日没同步过 ⇒ 闸门放行
  });

  it("列表写入的行：价格两列为 null，且根本不碰 snapshotAt", async () => {
    dsGet.mockResolvedValue({ count: 3, products: products(3) });
    const r = await syncType("stock");
    expect(r.count).toBe(3);
    expect(r.error).toBeUndefined();

    const inserts = stageInserts();
    expect(inserts.length).toBeGreaterThan(0);
    for (const { cols, params } of inserts) {
      expect(cols).toContain("lastPrice");
      // 列表阶段的列集合里没有快照时刻 ⇒ 新行 snapshotAt 必为 null（刀 1 的不变量）
      expect(cols).not.toContain("snapshotAt");
      const stride = cols.length;
      expect(params.length).toBe(stride * (params.length / stride));
      const priceAt = cols.indexOf("lastPrice");
      const pctAt = cols.indexOf("lastChangePct");
      const rows = params.length / stride;
      expect(rows).toBeGreaterThan(0);
      for (let i = 0; i < rows; i += 1) {
        expect(params[i * stride + priceAt]).toBeNull();
        expect(params[i * stride + pctAt]).toBeNull();
      }
    }
  });

  it("🔁 列表腿全程不触发快照刷新（刷新已移交给 ds 的链式第二条腿）", async () => {
    dsGet.mockResolvedValue({ count: 2, products: products(2) });
    await syncType("stock");
    expect(refreshSnapshot).not.toHaveBeenCalled();
  });

  it("降级留痕的 note 只剩列表这一句（旧的 snapshot updated=… 尾巴随拆腿消失）", async () => {
    count.mockResolvedValue(1000);
    dsGet.mockResolvedValue({
      count: 800,
      products: products(800),
      source: "sina-stock-spot",
      degraded: true,
      note: "东财列表不可用",
    });
    const r = await syncType("stock");
    expect(r.note).toBe("list degraded source=sina-stock-spot：东财列表不可用");
    expect(r.note).not.toContain("snapshot");
  });

  it("同类型并发仍共享一次出网（C17 单飞没被拆腿改动带没）", async () => {
    dsGet.mockResolvedValue({ count: 1, products: products(1) });
    const [a, b] = await Promise.all([syncType("stock"), syncType("stock")]);
    expect(dsGet).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
  });
});

// #23 当日幂等闸门（主人 2026-10-02 拍板"两道叠加"）——治的是"当天成功过之后，
// 重启／手动／探针再来一整轮"。ds 侧那条内存 `lastDate` 保留不动，这里加磁盘这一条。
describe("sync 当日幂等闸门（#23，同步腿这一侧）", () => {
  beforeEach(() => {
    count.mockReset().mockResolvedValue(0);
    executeRawUnsafe.mockReset().mockResolvedValue(0);
    transaction.mockReset().mockResolvedValue(undefined);
    dsGet.mockReset();
    refreshSnapshot.mockReset();
    listSyncedToday.mockReset().mockResolvedValue(null);
  });

  it("今日已落过列表 ⇒ 跳过：零次取数、零条写库 SQL", async () => {
    listSyncedToday.mockResolvedValue(new Date("2026-10-01T18:11:00.000Z")); // 北京 10-02 02:11
    const r = await syncType("stock");
    expect(dsGet).not.toHaveBeenCalled();
    expect(executeRawUnsafe).not.toHaveBeenCalled();
    expect(r.skipped).toBe(true);
    expect(r.count).toBeUndefined();
    expect(r.error).toBeUndefined(); // 跳过**不是**失败：web 的 `ok` 由 !error 导出，不得被它翻假
  });

  it("跳过时说得出「哪个时刻」＋「带 ?force=1 才能重跑」（#21：能做成状态位的别做成日志）", async () => {
    listSyncedToday.mockResolvedValue(new Date("2026-10-01T18:11:00.000Z"));
    const r = await syncType("fund");
    expect(r.note).toContain("今日已同步");
    expect(r.note).toContain("2026-10-02 02:11"); // 北京墙上时间，不是 UTC 那一份
    expect(r.note).toContain("force");
  });

  it("🔁 反向：判据为 null（今日没跑过／昨天跑的）⇒ 照常整跑一轮，闸门不得饿死当天", async () => {
    dsGet.mockResolvedValue({ count: 2, products: products(2) });
    const r = await syncType("stock");
    expect(dsGet).toHaveBeenCalledTimes(1);
    expect(r.skipped).toBeUndefined();
    expect(r.count).toBe(2);
  });

  it("🔁 反向：?force=1 越过闸门（主人手测前要重刷数据，不能被自己的闸门挡住）", async () => {
    listSyncedToday.mockResolvedValue(new Date("2026-10-01T18:11:00.000Z"));
    dsGet.mockResolvedValue({ count: 2, products: products(2) });
    const r = await syncType("stock", { force: true });
    expect(dsGet).toHaveBeenCalledTimes(1);
    expect(r.skipped).toBeUndefined();
    expect(listSyncedToday).not.toHaveBeenCalled(); // 带 force 时连那次读库都不该发生
  });

  it("闸门是逐类的：只挡今天跑过的那一类，失败过的类当天仍可单独重跑", async () => {
    dsGet.mockResolvedValue({ count: 1, products: products(1) });
    listSyncedToday.mockImplementation(async (t: unknown) =>
      t === "stock" ? new Date("2026-10-01T18:11:00.000Z") : null,
    );
    const [stock, hk] = await Promise.all([syncType("stock"), syncType("hk")]);
    expect(stock.skipped).toBe(true);
    expect(hk.skipped).toBeUndefined();
    expect(dsGet).toHaveBeenCalledTimes(1); // 只有 hk 那一次出网
  });
});

describe("美股进同步阶梯（CR9-59／#32 甲，主人 2026-10-04 定案）", () => {
  beforeEach(() => {
    count.mockReset().mockResolvedValue(0);
    executeRawUnsafe.mockReset().mockResolvedValue(0);
    transaction.mockReset().mockResolvedValue(undefined);
    dsGet.mockReset();
    refreshSnapshot.mockReset();
    listSyncedToday.mockReset().mockResolvedValue(null);
  });

  function usProducts(n: number) {
    return Array.from({ length: n }, (_, i) => ({
      type: "us",
      code: ["AAPL", "NVDA", "BRK.B"][i % 3],
      name: `美${i}`,
    }));
  }

  it("us 在 SYNC_TYPES ⇒ 夜跑那轮会带上市名单，并走同一条列表链落库", async () => {
    expect(SYNC_TYPES).toContain("us");
    dsGet.mockResolvedValue({ count: 3, products: usProducts(3) });
    const r = await syncType("us");
    expect(r.error).toBeUndefined();
    expect(r.count).toBe(3);
    // 暂存表名由 SYNC_TYPES 派生 ⇒ 断"这一类真的有自己的暂存表"，而不是靠白名单加了的推定
    const created = executeRawUnsafe.mock.calls.map((c) => String(c[0])).filter((s) => s.includes("Product_stage_us"));
    expect(created.length).toBeGreaterThan(0);
  });

  it("美股的覆盖面声明按 CR9-31 经列表链落到 result.note（R16：子集必须自己说话）", async () => {
    dsGet.mockResolvedValue({
      count: 2,
      products: usProducts(2),
      source: "sina-us-category-list",
      degraded: true,
      note: "只取前排 15 页（上游声明盘子 18241 只）",
    });
    const r = await syncType("us");
    expect(r.note).toContain("list degraded source=sina-us-category-list");
    expect(r.note).toContain("18241");
  });

  it("🔁 未注册的列表类型过不了暂存表那道闸（且一条写库 SQL 都不发）", async () => {
    // 实测出来的**分层**（本轮写这条时我先按"lib 层也拒在出网之前"下断言，红了才知道不是）：
    // 出网闸在**路由层**——`app/api/sync/route.ts` 先过 `SYNC_TYPES` 才调 `syncType`
    // （p2 第 [10] 段那条 `?type=bogus → 400` 断的就是它）；lib 这道 `stageTable()` 抛
    // 是**表名/SQL 注入面**的闸（暂存表名由类型拼出），它跑在取数之后。
    // 所以这里不许断"没出网"，要断的是"没对任意名字的表动过写"。
    dsGet.mockResolvedValue({ count: 1, products: usProducts(1) });
    const r = await syncType("bogus");
    expect(r.error).toContain("invalid sync type");
    const writes = executeRawUnsafe.mock.calls.filter((c) => String(c[0]).includes("INSERT INTO"));
    expect(writes).toHaveLength(0);
  });
});
