import { describe, expect, it } from "vitest";

import { extractResearchTarget } from "./research-target";

describe("extractResearchTarget（研报意图标的提取）", () => {
  it("A股 6 位代码优先", () => {
    expect(extractResearchTarget("深度分析 600519")).toEqual({ type: "stock", code: "600519" });
  });

  it("A股优先于同时出现的美股代码", () => {
    expect(extractResearchTarget("对比 000001 和 AAPL 做个研报")).toEqual({
      type: "stock",
      code: "000001",
    });
  });

  it("识别美股 ticker", () => {
    expect(extractResearchTarget("全面评估 AAPL")).toEqual({ type: "us", code: "AAPL" });
  });

  it("常规缩写不当成美股代码（回归修复）", () => {
    for (const w of ["ETF", "IPO", "GDP", "CPI", "ROE", "PE", "PB", "QDII"]) {
      expect(extractResearchTarget(`深度分析一下 ${w} 基金有哪些`)).toBeNull();
    }
  });

  it("无可识别标的返回 null", () => {
    expect(extractResearchTarget("帮我做个深度分析")).toBeNull();
  });
});
