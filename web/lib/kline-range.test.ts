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

// CR9-12（2026-09-26）：形态合法但**历法不存在**的日期必须按 A2-② 同一契约报错。
// 原实现只跑 /^\d{4}-\d{2}-\d{2}$/，`2026-02-31` 放行后 dayStart() 得 Invalid Date，
// 下面两个比较全是 NaN 比较（恒 false）⇒ 窗口被上游静默改写（登记时实测：请求 02-31
// 返回从 03-03 起，调用方以为拿到的是 2 月底）。
describe("normalizeRange（CR9-12：形态过 ≠ 历法过，不存在的日期必须报错）", () => {
  it("2026-02-31（2 月没有 31 号）→ error 且点名 start", () => {
    const r = normalizeRange("2026-02-31", null);
    expect("error" in r).toBe(true);
    if ("error" in r) expect(r.error).toContain("invalid start date");
  });

  it("2026-02-30 → error 且点名 end", () => {
    const r = normalizeRange(null, "2026-02-30");
    expect("error" in r).toBe(true);
    if ("error" in r) expect(r.error).toContain("invalid end date");
  });

  it("月份越界 2026-13-01 → error", () => {
    const r = normalizeRange("2026-13-01", null);
    expect("error" in r).toBe(true);
  });

  it("反向对照：非闰年 2026-02-29 拒绝，而闰年 2024-02-29 必须放行", () => {
    // 这条是"判据不是粗暴 day<=28"的证据——否则会把真实存在的闰日也拒掉。
    expect("error" in normalizeRange("2026-02-29", null)).toBe(true);
    const leap = normalizeRange("2024-02-29", "2024-03-01");
    expect(leap).toEqual({ start: "2024-02-29", end: "2024-03-01" });
  });

  it("反向对照：常规合法日期不受影响（证明不是恒假桩）", () => {
    const r = normalizeRange("2026-01-01", "2026-06-30");
    expect(r).toEqual({ start: "2026-01-01", end: "2026-06-30" });
  });
});
