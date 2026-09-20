import { describe, expect, it, vi } from "vitest";

// CR6-P1-3：护栏单测。providers 侧已剔除 null OHLC，这里验证 web 侧兜底：
// 单行脏数据（null / NaN / 非法日期）必须被跳过，不得进 upsertCandles。
vi.mock("@/lib/prisma", () => ({ prisma: {} }));
vi.mock("@/lib/data-service", () => ({ dsGet: vi.fn() }));

import { isUsableCandle } from "./kline";

describe("isUsableCandle（K 线脏行护栏，CR6-P1-3）", () => {
  const ok = { date: "2026-09-17", open: 1, high: 2, low: 0.5, close: 1.5 };

  it("合法行 → true", () => {
    expect(isUsableCandle(ok)).toBe(true);
  });

  it("OHLC 含 null → false", () => {
    // provider 未过滤时可能产出 null（schema 列为 NOT NULL）
    expect(isUsableCandle({ ...ok, open: null as unknown as number })).toBe(false);
    expect(isUsableCandle({ ...ok, close: null as unknown as number })).toBe(false);
  });

  it("OHLC 含 NaN / Infinity → false", () => {
    expect(isUsableCandle({ ...ok, high: NaN })).toBe(false);
    expect(isUsableCandle({ ...ok, low: Infinity })).toBe(false);
  });

  it("日期格式非法 → false", () => {
    expect(isUsableCandle({ ...ok, date: "2026/09/17" })).toBe(false);
    expect(isUsableCandle({ ...ok, date: "2026-09-17 09:30" })).toBe(false);
  });
});
