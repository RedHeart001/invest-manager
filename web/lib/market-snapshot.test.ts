import { describe, expect, it } from "vitest";

// CR-09：快照批量写用 COALESCE 保留旧值，避免部分降级把另一列为 null 的字段擦空。
// 用纯函数 buildSnapshotUpdate 断言 SQL 与绑定参数（不触碰真实 DB）。
import {
  EM_BATCH_DELAY_MS,
  EM_SNAPSHOT_TYPES,
  buildSnapshotUpdate,
  shouldPaceBatch,
} from "./market-snapshot";

describe("buildSnapshotUpdate（CR-09 ＋ 刀 1 的 snapshotAt）", () => {
  const rows = [
    { code: "600519", price: 1500, changePct: null },
    { code: "000001", price: null, changePct: -1.2 },
  ];
  // 固定时刻：断言"整批共享同一个时刻"时必须可比对，不能用 new Date() 现取
  const at = new Date("2026-10-01T08:30:00.000Z");

  it("两个字段都用 COALESCE 保留旧值", () => {
    const { sql } = buildSnapshotUpdate("stock", rows, at);
    expect(sql).toContain('COALESCE(CASE "code" WHEN ? THEN ? WHEN ? THEN ? END, "lastPrice")');
    expect(sql).toContain('COALESCE(CASE "code" WHEN ? THEN ? WHEN ? THEN ? END, "lastChangePct")');
  });

  it("刀1：snapshotAt 与价格同时写入（整批一个时刻，SET 子句里赋值）", () => {
    const { sql, params } = buildSnapshotUpdate("stock", rows, at);
    expect(sql).toContain('"snapshotAt" = ?');
    // 整批共享 ⇒ 只绑定一次，且值就是调用方传入的那个时刻
    expect(params.filter((p) => p instanceof Date)).toEqual([at]);
  });

  it("🔁 刀1 反向：时刻由调用方决定，函数自己不取 now（否则无法断言「一轮一个时刻」）", () => {
    const later = new Date(at.getTime() + 3_600_000);
    const a = buildSnapshotUpdate("stock", rows, at).params;
    const b = buildSnapshotUpdate("stock", rows, later).params;
    // 同一批行、不同传入时刻 ⇒ 参数只在快照时刻上不同，其余完全一致
    expect(a.filter((p) => !(p instanceof Date))).toEqual(b.filter((p) => !(p instanceof Date)));
    expect(a).not.toEqual(b);
  });

  it("绑定参数顺序：price 组 → changePct 组 → snapshotAt → type → codes", () => {
    const { params } = buildSnapshotUpdate("stock", rows, at);
    expect(params).toEqual([
      "600519", 1500,        // price 组（第 1 行）
      "000001", null,        // price 组（第 2 行）
      "600519", null,        // changePct 组（第 1 行）
      "000001", -1.2,        // changePct 组（第 2 行）
      at,                    // SET snapshotAt（整批共享，位置必须与 SQL 里的 ? 同序）
      "stock",               // WHERE type
      "600519", "000001",    // WHERE code IN
    ]);
  });

  it("参数个数 = 2N(price) + 2N(changePct) + 1(snapshotAt) + 1(type) + N(codes)", () => {
    const { params } = buildSnapshotUpdate("stock", rows, at);
    expect(params.length).toBe(2 * rows.length + 2 * rows.length + 1 + 1 + rows.length);
  });

  it("占位符个数与参数个数一致（防错位）", () => {
    const { sql, params } = buildSnapshotUpdate("stock", rows, at);
    const placeholders = (sql.match(/\?/g) ?? []).length;
    expect(placeholders).toBe(params.length);
  });

  it("空行集不产生 SQL 占位符错配（调用方已短路，此处仅保证纯函数可用）", () => {
    const { sql, params } = buildSnapshotUpdate("stock", [], at);
    // 刀1 后：SET 里多一个整批共享的 snapshotAt ⇒ 参数 [时刻, type]、占位符 2 个，仍自洽
    expect(params).toEqual([at, "stock"]);
    expect((sql.match(/\?/g) ?? []).length).toBe(2);
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

// CR9-67（丙，主人 2026-10-06 给字）：**睡不睡的判据从"这一类"改成"这一批"**。
// 上面那张表（CR9-9 的实测结论）从这一刀起只剩一个用途＝**回落**，所以它的断言原样保留，
// 新的一套住在下面。两枚钻子分别打在"标记被忽略"（回退成每类型判据）与"标记恒 False"上，
// 清单见 `docs/FIX-LEDGER.md` 待拍板 #39 末段。
describe("逐批限速判据 shouldPaceBatch（CR9-67／丙）", () => {
  it("ds 说这批不打东财 ⇒ 不睡（fund 的场外净值批次＝10-06 实测每轮那 249 个白等的 5 秒）", () => {
    expect(shouldPaceBatch("fund", false)).toBe(false);
  });

  it("🔁 ds 说这批要打 ⇒ 照旧睡满 5 秒（丙不许顺手把真碰东财的批次也放开）", () => {
    expect(shouldPaceBatch("fund", true)).toBe(true);
    expect(shouldPaceBatch("stock", true)).toBe(true);
  });

  it("问不出路由（老 ds 没这个键／那次取数没成功）⇒ 退回旧的每类型表：既不是一律睡也不是一律不睡", () => {
    expect(shouldPaceBatch("fund", null)).toBe(true);
    expect(shouldPaceBatch("stock", null)).toBe(true);
    expect(shouldPaceBatch("crypto", null)).toBe(false);
    expect(shouldPaceBatch("us", null)).toBe(false);
  });

  it("🔁 标记优先于类型名：stock 被告知不打东财也不睡、crypto 被告知要打就睡（判据只有一套真值）", () => {
    expect(shouldPaceBatch("stock", false)).toBe(false);
    expect(shouldPaceBatch("crypto", true)).toBe(true);
  });
});
