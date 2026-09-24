import { describe, expect, it, vi } from "vitest";

// CR7-2/A2-②（2026-09-24 拍板）：normalizeRange 区分「缺参回落默认」与
// 「格式非法报错」。此前非法格式（紧凑 8 位等）被静默当 null 回落 90 天——
// 调用方以为传了窗口，实际拿到默认值，正是 CR7-2 的缺陷模式。
// 反向验证：回退 normalizeRange 的非法格式分支 → 「非法格式→error」断言精确失败
// （缺参回落断言不受影响）。
vi.mock("@/lib/prisma", () => ({ prisma: {} }));
vi.mock("@/lib/data-service", () => ({ dsGet: vi.fn() }));

import { normalizeRange } from "./kline";

describe("normalizeRange（CR7-2/A2-②：非法格式必须报错，不得静默回落）", () => {
  it("缺参 → 回落默认（start=90 天前，end=今日）", () => {
    const r = normalizeRange(null, null);
    expect("error" in r).toBe(false);
    if (!("error" in r)) {
      expect(r.end).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(r.start).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });

  it("合法 ISO → 原样通过", () => {
    const r = normalizeRange("2026-01-01", "2026-06-30");
    expect(r).toEqual({ start: "2026-01-01", end: "2026-06-30" });
  });

  it("紧凑 8 位（旧缺陷形态）→ error", () => {
    const r = normalizeRange("20260101", null);
    expect("error" in r).toBe(true);
    if ("error" in r) expect(r.error).toContain("invalid start");
  });

  it("end 非法 → error（点名 end）", () => {
    const r = normalizeRange(null, "2026/06/30");
    expect("error" in r).toBe(true);
    if ("error" in r) expect(r.error).toContain("invalid end");
  });

  it("空字符串视为缺参（回落默认），不报错", () => {
    // URLSearchParams.get() 缺参返回 null；`?start=` 返回空串——两者语义同"没传"
    const r = normalizeRange("", "");
    expect("error" in r).toBe(false);
  });

  it("start > end 仍报错（原有校验保留）", () => {
    const r = normalizeRange("2026-06-30", "2026-01-01");
    expect("error" in r).toBe(true);
    if ("error" in r) expect(r.error).toContain("start must be <= end");
  });
});
