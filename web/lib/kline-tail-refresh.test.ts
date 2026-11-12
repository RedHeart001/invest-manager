import { beforeEach, describe, expect, it, vi } from "vitest";

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

const row = (date: string, close = 10, source = "akshare") => ({
  date: new Date(`${date}T00:00:00.000Z`), open: close - 1, high: close + 1,
  low: close - 2, close, volume: 100, source,
});
const candle = (date: string, close: number) => ({
  date, open: close - 1, high: close + 1, low: close - 2, close, volume: 200,
});

describe("CR10-27：日 K 尾部复查允许修正缓存末日", () => {
  beforeEach(() => {
    findMany.mockReset();
    executeRawUnsafe.mockReset();
    dsGet.mockReset();
    executeRawUnsafe.mockResolvedValue(1);
  });

  it("回源从缓存末日开始，同日 OHLC 更新且总行数不增", async () => {
    const code = `CR1027-${Date.now()}-update`;
    findMany
      .mockResolvedValueOnce([row("2026-11-10", 9), row("2026-11-11", 10)])
      .mockResolvedValueOnce([]) // upsert 查已有日期
      .mockResolvedValueOnce([row("2026-11-10", 9), row("2026-11-11", 12)]);
    dsGet.mockResolvedValue({ source: "tencent", candles: [candle("2026-11-11", 12)] });

    const result = await getKlineRange("stock", code, "2026-11-10", "2026-11-11");

    expect(dsGet).toHaveBeenCalledWith("/kline", expect.objectContaining({
      start: "20261111", end: "20261111", interval: "1d",
    }), 45_000);
    const [sql, ...params] = executeRawUnsafe.mock.calls[0];
    expect(sql).toContain('ON CONFLICT("type","code","date") DO UPDATE');
    expect(params).toContain(Date.UTC(2026, 10, 11));
    expect(params).toContain(12);
    expect(result.candles).toHaveLength(2);
    expect(result.candles[0].close).toBe(9); // 非尾部历史行不被改写
    expect(result.candles[1].close).toBe(12);
    expect(result.fetchedDays).toBe(1);
  });

  it("30 分钟复查窗口仍生效：同一代码第二次不重复回源", async () => {
    const code = `CR1027-${Date.now()}-window`;
    findMany.mockImplementation(async (args) => {
      if (args?.select) return [];
      return [row("2026-11-11", 10)];
    });
    dsGet.mockResolvedValue({ source: "akshare", candles: [candle("2026-11-11", 11)] });

    await getKlineRange("stock", code, "2026-11-01", "2026-11-11");
    await getKlineRange("stock", code, "2026-11-01", "2026-11-11");

    expect(dsGet).toHaveBeenCalledTimes(1);
    expect(executeRawUnsafe).toHaveBeenCalledTimes(1);
  });

  it("尾部回源失败也进复查窗口：窗口内不连续重试，缓存照常返回（C34）", async () => {
    const code = `CR1027-${Date.now()}-failwin`;
    findMany.mockImplementation(async (args) => {
      if (args?.select) return [];
      return [row("2026-11-11", 10)];
    });
    dsGet.mockRejectedValue(new Error("upstream down"));

    const r1 = await getKlineRange("stock", code, "2026-11-11", "2026-11-11");
    const r2 = await getKlineRange("stock", code, "2026-11-11", "2026-11-11");

    expect(dsGet).toHaveBeenCalledTimes(1);
    expect(r1.note).toContain("增量回源失败");
    expect(r2.note).toContain("增量复查窗口内");
    expect(r2.candles).toHaveLength(1);
  });

  it("同日复查（无头缺口）成功也进窗口：第二次不重复回源（C34）", async () => {
    const code = `CR1027-${Date.now()}-tailwin`;
    findMany.mockImplementation(async (args) => {
      if (args?.select) return [];
      return [row("2026-11-11", 10)];
    });
    dsGet.mockResolvedValue({ source: "akshare", candles: [candle("2026-11-11", 11)] });

    await getKlineRange("stock", code, "2026-11-11", "2026-11-11");
    await getKlineRange("stock", code, "2026-11-11", "2026-11-11");

    expect(dsGet).toHaveBeenCalledTimes(1);
    expect(executeRawUnsafe).toHaveBeenCalledTimes(1);
  });
});
