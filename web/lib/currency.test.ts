import { describe, expect, it } from "vitest";

import { priceWithCurrency } from "./currency";

// CR7-4/B2c：币种落地。文案拍板 `419.00 港币`（后缀中文单位）。
describe("priceWithCurrency（CR7-4/B2c）", () => {
  it("HKD → 追加「港币」", () => {
    expect(priceWithCurrency("419.00", "HKD")).toBe("419.00 港币");
  });

  it("USD → 追加「美元」", () => {
    expect(priceWithCurrency("189.50", "USD")).toBe("189.50 美元");
  });

  it("CNY → 原样（A 股语境不加单位）", () => {
    expect(priceWithCurrency("1688.00", "CNY")).toBe("1688.00");
  });

  it("缺失/null → 原样（A股/场内基金等既有展示不变）", () => {
    expect(priceWithCurrency("12.34", null)).toBe("12.34");
    expect(priceWithCurrency("12.34", undefined)).toBe("12.34");
  });

  it("未知币种 → 透传原文（不猜标签）", () => {
    expect(priceWithCurrency("1.00", "BTC")).toBe("1.00 BTC");
  });
});
