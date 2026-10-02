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

import { syncType } from "./sync";

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
