import { describe, expect, it } from "vitest";

import { isFlatOhlcSeries } from "./kline-shape";

type C = { open: number; high: number; low: number; close: number };

const bar = (v: number, spread = 0): C => ({
  open: v - spread,
  high: v + spread,
  low: v - spread,
  close: v,
});

// 2026-09-27 15:38 实测形态：东财分钟线挂掉、降级到腾讯后同一请求返回 267 根，
// 其中 OHLC 四值完全相等的根数 = 267/267（腾讯分钟 bar 只给该分钟最后一笔价）。
const tencentMinuteShape = (n: number): C[] =>
  Array.from({ length: n }, (_, i) => bar(1250 - i * 0.05));

describe("isFlatOhlcSeries（CR9-42 退化判据）", () => {
  it("实测形态：267 根四值全相等 → 判为退化序列", () => {
    expect(isFlatOhlcSeries(tencentMinuteShape(267))).toBe(true);
  });

  it("带真实区间的 K 线序列 → 不得判为退化", () => {
    expect(isFlatOhlcSeries([bar(10, 0.5), bar(11, 0.4), bar(12, 0.6)])).toBe(false);
  });

  it("🔁 成对边界：267 根里有 1 根带区间 → 仍是合法 K 线（every 而非 some）", () => {
    const mixed = tencentMinuteShape(267);
    mixed[100] = bar(1240, 0.3);
    expect(isFlatOhlcSeries(mixed)).toBe(false);
    // 同一份数据去掉那根不等的 bar 后必须翻转为 true——防实现退化成"多数相等即退化"
    expect(isFlatOhlcSeries(mixed.filter((_, i) => i !== 100))).toBe(true);
  });

  it("空序列 → false（不得因空数据改渲染形态，空白另有回落链路）", () => {
    expect(isFlatOhlcSeries([])).toBe(false);
  });

  it("单根且四值相等 → true（与 lib/kline.ts 日线缓存的旧判据逐字等价）", () => {
    expect(isFlatOhlcSeries([bar(7)])).toBe(true);
    expect(isFlatOhlcSeries([bar(7, 0.1)])).toBe(false);
  });
});
