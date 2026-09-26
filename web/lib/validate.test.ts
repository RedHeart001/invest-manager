import { describe, expect, it } from "vitest";

import { CODE_SET, QUOTE_TYPES, checkSubject } from "./validate";

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

// CR9-10（2026-09-26 接线）：checkSubject 是"出网前判"这一步的单一实现——
// /api/events 与内置工具执行路径此前各自缺判，把任意串直送 data-service。
describe("checkSubject（CR9-10：type + code 成对闸门）", () => {
  it("成对合法 → 原样归一化返回", () => {
    expect(checkSubject("hk", "00700")).toEqual({ type: "hk", code: "00700" });
  });

  it("缺 type → 回落 stock（与 /api/quote 的 ?? \"stock\" 同口径），code 两侧空白被裁掉", () => {
    expect(checkSubject(null, "  600519  ")).toEqual({ type: "stock", code: "600519" });
  });

  it("type 非法 → error 点名 type，且不看 code", () => {
    const r = checkSubject("stockx", "600519");
    expect("error" in r).toBe(true);
    if ("error" in r) expect(r.error).toContain("unsupported type");
  });

  it("code 非法 → error 点名 code（空值显式写 (空)）", () => {
    for (const bad of ["", null, "贵州茅台", "a".repeat(21)]) {
      const r = checkSubject("stock", bad);
      expect("error" in r).toBe(true);
      if ("error" in r) expect(r.error).toContain("invalid code");
    }
  });

  it("反向对照：合法入参不得报错（证明不是恒假桩）", () => {
    expect("error" in checkSubject("fund", "110022")).toBe(false);
    expect("error" in checkSubject("us", "AAPL")).toBe(false);
  });
});
