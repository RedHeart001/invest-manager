import { beforeEach, describe, expect, it, vi } from "vitest";

// CR-05：kline 头/尾缺口必须用**独立**复查窗口——此前共用 lastChecked，
// 头部补全成功会立即压制同请求的尾部增量（本次拿不到最新一日）。

const findMany = vi.fn();
const create = vi.fn();
const dsGet = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: { klineDaily: { findMany: (...a: unknown[]) => findMany(...a), create: (...a: unknown[]) => create(...a) } },
}));
vi.mock("@/lib/data-service", () => ({ dsGet: (...a: unknown[]) => dsGet(...a) }));

import { getKlineRange } from "./kline";

function iso(daysAgo: number): string {
  const d = new Date(Date.now() + 8 * 3600_000 - daysAgo * 86_400_000);
  return d.toISOString().slice(0, 10);
}

function candle(date: string) {
  return { date: new Date(`${date}T00:00:00.000Z`), open: 1, high: 1, low: 1, close: 1, volume: 1, source: "akshare" };
}

describe("getKlineRange 头/尾缺口独立窗口（CR-05）", () => {
  beforeEach(() => {
    findMany.mockReset();
    create.mockReset();
    dsGet.mockReset();
    create.mockResolvedValue({});
  });

  it("同时存在头缺口与尾缺口时：两次都回源（头不压制尾）", async () => {
    // 用唯一 code 避免 globalThis 里的复查窗口在用例间串扰
    const code = `CR05-${Date.now()}-a`;
    const cachedMin = iso(30);
    const cachedMax = iso(2);
    const start = iso(365);
    const end = iso(0);

    // 第一次 findMany（读已有缓存）返回 [cachedMin..cachedMax]
    // 第二次 findMany（写回后读库）返回更全的集合
    findMany
      .mockResolvedValueOnce([candle(cachedMin), candle(cachedMax)])
      .mockResolvedValueOnce([candle(start), candle(cachedMin), candle(cachedMax), candle(end)]);

    dsGet.mockResolvedValue({ source: "akshare", candles: [candle(iso(300))] });

    await getKlineRange("stock", code, start, end);

    // 头缺口 + 尾缺口各一次回源 → dsGet 至少被调用 2 次
    expect(dsGet.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("仅头缺口、无尾缺口时：只回头部一次", async () => {
    const code = `CR05-${Date.now()}-b`;
    const cachedMin = iso(30);
    const end = iso(2); // 与 cachedMax 相同 → 无尾缺口
    const start = iso(365);

    findMany
      .mockResolvedValueOnce([candle(cachedMin), candle(end)])
      .mockResolvedValueOnce([candle(start), candle(cachedMin), candle(end)]);
    dsGet.mockResolvedValue({ source: "akshare", candles: [candle(start)] });

    await getKlineRange("stock", code, start, end);
    expect(dsGet.mock.calls.length).toBe(1);
  });
});
