import { describe, expect, it } from "vitest";

// CR-09：快照批量写用 COALESCE 保留旧值，避免部分降级把另一列为 null 的字段擦空。
// 用纯函数 buildSnapshotUpdate 断言 SQL 与绑定参数（不触碰真实 DB）。
import {
  EM_BATCH_DELAY_MS,
  EM_SNAPSHOT_TYPES,
  buildSnapshotUpdate,
} from "./market-snapshot";

describe("buildSnapshotUpdate（CR-09）", () => {
  const rows = [
    { code: "600519", price: 1500, changePct: null },
    { code: "000001", price: null, changePct: -1.2 },
  ];

  it("两个字段都用 COALESCE 保留旧值", () => {
    const { sql } = buildSnapshotUpdate("stock", rows);
    expect(sql).toContain('COALESCE(CASE "code" WHEN ? THEN ? WHEN ? THEN ? END, "lastPrice")');
    expect(sql).toContain('COALESCE(CASE "code" WHEN ? THEN ? WHEN ? THEN ? END, "lastChangePct")');
  });

  it("绑定参数顺序：price 组 → changePct 组 → type → codes", () => {
    const { params } = buildSnapshotUpdate("stock", rows);
    expect(params).toEqual([
      "600519", 1500,        // price 组（第 1 行）
      "000001", null,        // price 组（第 2 行）
      "600519", null,        // changePct 组（第 1 行）
      "000001", -1.2,        // changePct 组（第 2 行）
      "stock",               // WHERE type
      "600519", "000001",    // WHERE code IN
    ]);
  });

  it("参数个数 = 2N(price) + 2N(changePct) + 1(type) + N(codes)", () => {
    const { params } = buildSnapshotUpdate("stock", rows);
    expect(params.length).toBe(2 * rows.length + 2 * rows.length + 1 + rows.length);
  });

  it("占位符个数与参数个数一致（防错位）", () => {
    const { sql, params } = buildSnapshotUpdate("stock", rows);
    const placeholders = (sql.match(/\?/g) ?? []).length;
    expect(placeholders).toBe(params.length);
  });

  it("空行集不产生 SQL 占位符错配（调用方已短路，此处仅保证纯函数可用）", () => {
    const { sql, params } = buildSnapshotUpdate("stock", []);
    expect(params).toEqual(["stock"]);
    expect((sql.match(/\?/g) ?? []).length).toBe(1);
  });
});

// CR9-9（2026-09-27）：限速集合与批间隔按**真实出网源**判定，不再按类型名猜。
// 旧集合只有 stock/bond ⇒ hk 与 fund 的场内部分是漏网的（实测见 market-snapshot.ts 注释）。
describe("东财族批次限速（CR9-9）", () => {
  it("会打东财 ulist 的四类全在集合内（本轮补 fund / hk）", () => {
    expect([...EM_SNAPSHOT_TYPES].sort()).toEqual(["bond", "fund", "hk", "stock"]);
  });

  it("🔁 非东财族不得被限速：crypto 走 CoinGecko、us 不参与快照", () => {
    expect(EM_SNAPSHOT_TYPES.has("crypto")).toBe(false);
    expect(EM_SNAPSHOT_TYPES.has("us")).toBe(false);
  });

  it("批间隔不低于源族桶自己的放行下限（min_interval 5s / rate_per_min 12）", () => {
    expect(EM_BATCH_DELAY_MS).toBeGreaterThanOrEqual(5000);
  });
});
