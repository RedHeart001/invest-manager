import { beforeEach, describe, expect, it, vi } from "vitest";

// 回归测试（2026-09-19 集成验收发现）：KlineDaily.date 的原生 INSERT 参数必须与
// Prisma 的 DateTime 存储同构（**Unix 毫秒整数**）。此前传 ISO 字符串会存成 text，
// 与 Prisma 生成的 `date >= ? / <= ?`（数字比较）不匹配 → 行在日期范围查询里被漏掉
// （实测：R13 交叉验证失败、详情页少一根 K 线、缓存天数虚高）。

const findMany = vi.fn();
const executeRawUnsafe = vi.fn();
const dsGet = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    klineDaily: { findMany: (...a: unknown[]) => findMany(...a) },
    $executeRawUnsafe: (...a: unknown[]) => executeRawUnsafe(...a),
  },
}));
vi.mock("@/lib/data-service", () => ({ dsGet: (...a: unknown[]) => dsGet(...a) }));

import { getKlineRange } from "./kline";

describe("KlineDaily 原生写入的日期格式（回归）", () => {
  beforeEach(() => {
    findMany.mockReset();
    executeRawUnsafe.mockReset();
    dsGet.mockReset();
    executeRawUnsafe.mockResolvedValue(1);
    // findMany 调用序列：① 存在性检查（空 → 全视为新行）② upsert 后读库
    findMany.mockResolvedValue([]);
    dsGet.mockResolvedValue({
      source: "akshare",
      candles: [{ date: "2026-09-18", open: 1, high: 2, low: 0.5, close: 1.5, volume: 100 }],
    });
  });

  it("INSERT 的 date 参数为毫秒整数（非 ISO 字符串）", async () => {
    await getKlineRange("stock", "TESTDATEFMT1", "2026-09-01", "2026-09-19");

    const insertCalls = executeRawUnsafe.mock.calls.filter((c) =>
      String(c[0]).includes('INSERT OR IGNORE INTO "KlineDaily"'),
    );
    expect(insertCalls.length).toBeGreaterThanOrEqual(1);
    const args = insertCalls[0].slice(1) as unknown[];
    const dateArg = args[3]; // 列序：id,type,code,date,...
    expect(typeof dateArg).toBe("number");
    expect(Number.isInteger(dateArg)).toBe(true);
    expect(dateArg).toBe(new Date("2026-09-18T00:00:00.000Z").getTime());
  });
});
