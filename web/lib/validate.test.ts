import { describe, expect, it } from "vitest";

import { CODE_SET, QUOTE_TYPES } from "./validate";

// C5（CR7-6）：code/type 校验单一来源。此前正则硬写在 research/start 与
// watchlist 两处，kline/quote 主路由只判非空 → 任意串直传 ds 耗东财额度。
describe("validate（C5 单一来源）", () => {
  it("CODE_SET：合法形态放行", () => {
    expect(CODE_SET.test("600519")).toBe(true);
    expect(CODE_SET.test("00700")).toBe(true);
    expect(CODE_SET.test("AAPL")).toBe(true);
    expect(CODE_SET.test("sh600519")).toBe(true);
    expect(CODE_SET.test("BTC-USD")).toBe(true);
  });

  it("CODE_SET：非法形态拦截（空串/超长/路径/空白/中文）", () => {
    expect(CODE_SET.test("")).toBe(false);
    expect(CODE_SET.test("a".repeat(21))).toBe(false);
    expect(CODE_SET.test("../etc/passwd")).toBe(false); // 含 / 与超长
    expect(CODE_SET.test("600519 x")).toBe(false);
    expect(CODE_SET.test("贵州茅台")).toBe(false);
  });

  it("QUOTE_TYPES：六类产品类型齐全", () => {
    expect([...QUOTE_TYPES]).toEqual(["stock", "fund", "bond", "crypto", "hk", "us"]);
  });

  it("QUOTE_TYPES：非法类型不在白名单", () => {
    expect(QUOTE_TYPES.includes("stockx" as never)).toBe(false);
    expect(QUOTE_TYPES.includes("" as never)).toBe(false);
  });
});
