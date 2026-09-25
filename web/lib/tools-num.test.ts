import { describe, expect, it, vi } from "vitest";

// D1（CR7-11）：tools.ts 的 numOrNull 是 C4 唯一防线（缺价必须 null，不得上报 0 元）
// 与 9 个工具的成功/降级分支中最易错的部分——provider 返回 "-" / "" / NaN 时。
// 本文件聚焦 numOrNull 纯函数；工具全分支由集成测试覆盖。

vi.mock("@/lib/prisma", () => ({ prisma: {} }));
vi.mock("./data-service", () => ({ dsGet: vi.fn() }));
vi.mock("./kline", () => ({ getKlineRange: vi.fn(), normalizeRange: vi.fn(() => ({})) }));
vi.mock("./hotspots", () => ({ listDigests: vi.fn() }));
vi.mock("./phases", () => ({ detectPhases: vi.fn() }));
vi.mock("./research", () => ({ getLatestReport: vi.fn(), startResearch: vi.fn() }));
vi.mock("./search", () => ({ searchProducts: vi.fn() }));

import { numOrNull } from "./tools";

describe("numOrNull（D1：C4 缺价防线）", () => {
  it("正常数值放行并保留 2 位精度", () => {
    expect(numOrNull(419.00)).toBe(419);
    expect(numOrNull("3.14159")).toBe(3.14);
    expect(numOrNull(0.001)).toBe(0);
  });

  it("缺价形态必须为 null（绝不上报 0 元）", () => {
    expect(numOrNull(null)).toBe(null);
    expect(numOrNull(undefined)).toBe(null);
    expect(numOrNull("")).toBe(null); // provider 返回 "-" 常被剥成空串
    expect(numOrNull("-")).toBe(null); // "-" 是 Number("-")=NaN → null
    expect(numOrNull("--")).toBe(null);
  });

  it("非有限数值拦截（NaN/Infinity/对象）", () => {
    expect(numOrNull(NaN)).toBe(null);
    expect(numOrNull(Infinity)).toBe(null);
    expect(numOrNull(-Infinity)).toBe(null);
    expect(numOrNull({})).toBe(null);
    expect(numOrNull("12.5x")).toBe(null);
  });

  it("0 是合法值：真 0（如涨跌为 0）不得误杀", () => {
    expect(numOrNull(0)).toBe(0);
    expect(numOrNull("0")).toBe(0);
    expect(numOrNull("0.00")).toBe(0);
  });
});
