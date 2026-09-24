import { describe, expect, it } from "vitest";

import { buildProfile, type ProductLike, type QuoteEnriched } from "./profile";

function product(over: Partial<ProductLike> = {}): ProductLike {
  return {
    type: "stock",
    name: "贵州茅台",
    code: "600519",
    exchange: "SH",
    tags: [],
    ...over,
  };
}

describe("buildProfile（规则模板画像）", () => {
  it("股票：交易所 + 市值 + 估值字段齐全", () => {
    const quote = {
      type: "stock",
      code: "600519",
      price: 1271.63,
      marketCap: 2.1e12,
      peTtm: 22.3,
      pb: 8.1,
    } as QuoteEnriched;
    const text = buildProfile(product(), quote);
    expect(text).toContain("沪市A股");
    expect(text).toContain("总市值 2.10 万亿");
    expect(text).toContain("PE(TTM) 22.30");
    expect(text).toContain("PB 8.10");
  });

  it("股票：字段缺失逐项降级，不编造", () => {
    const text = buildProfile(product({ exchange: "SZ" }), null);
    expect(text).toBe("深市A股");
  });

  it("全部字段缺失 → 降级文案", () => {
    const text = buildProfile(product({ exchange: null }), null);
    expect(text).toBe("暂无画像数据（字段缺失）");
  });

  it("场外基金：类型标签 + 净值 4 位小数", () => {
    const text = buildProfile(
      product({ type: "fund", exchange: "", tags: ["混合型-偏股"] }),
      { type: "fund", code: "000001", price: 1.262 } as QuoteEnriched,
    );
    expect(text).toBe("混合型-偏股 · 场外基金 · 单位净值 1.2620");
  });

  it("场内基金：标注场内", () => {
    const text = buildProfile(
      product({ type: "fund", exchange: "SZ", code: "159915", tags: [] }),
      null,
    );
    expect(text).toContain("场内基金");
  });

  it("可转债：不重复'可转债'标签", () => {
    const text = buildProfile(
      product({ type: "bond", tags: ["可转债"] }),
      null,
    );
    expect(text).toBe("可转债 · 沪市");
  });

  it("加密货币：市值排名", () => {
    const text = buildProfile(product({ type: "crypto", exchange: "crypto" }), {
      type: "crypto",
      code: "BTC",
      price: 60000,
      marketCapRank: 1,
    } as QuoteEnriched);
    expect(text).toBe("加密货币 · 市值排名第 1");
  });

  it("CR7-4/B2b：港股画像非空且带币种与估值", () => {
    const text = buildProfile(product({ type: "hk", exchange: "HK" }), {
      type: "hk",
      code: "00700",
      price: 419,
      currency: "HKD",
      marketCap: 3.9e12,
      peTtm: 22.5,
      pb: 4.1,
    } as QuoteEnriched);
    expect(text).toContain("港股");
    expect(text).toContain("计价：港币");
    expect(text).toContain("总市值 3.90 万亿");
    expect(text).toContain("PE(TTM) 22.50");
    expect(text).not.toBe("暂无画像数据（字段缺失）");
  });

  it("CR7-4/B2b：美股画像非空（yfinance 无估值字段时逐项降级）", () => {
    const text = buildProfile(product({ type: "us", exchange: "NASDAQ" }), {
      type: "us",
      code: "AAPL",
      price: 189.5,
      currency: "USD",
    } as QuoteEnriched);
    expect(text).toContain("美股");
    expect(text).toContain("计价：美元");
    expect(text).not.toBe("暂无画像数据（字段缺失）");
  });
});
