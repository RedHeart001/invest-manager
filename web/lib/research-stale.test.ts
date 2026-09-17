import { describe, expect, it } from "vitest";

import { STALE_RUNNING_MS, isStaleRunning } from "./research-stale";

describe("isStaleRunning（研报 running 陈旧判定，CR5-3）", () => {
  const now = new Date("2026-09-17T12:00:00.000Z").getTime();
  const iso = (msAgo: number) => new Date(now - msAgo).toISOString();

  it("running 且超过阈值 → 陈旧", () => {
    expect(isStaleRunning({ status: "running", updatedAt: iso(STALE_RUNNING_MS + 1000) }, now)).toBe(
      true,
    );
  });

  it("running 但未超阈值 → 不陈旧（正常执行中）", () => {
    expect(isStaleRunning({ status: "running", updatedAt: iso(60_000) }, now)).toBe(false);
  });

  it("阈值边界：恰好等于 → 不陈旧（严格大于）", () => {
    expect(isStaleRunning({ status: "running", updatedAt: iso(STALE_RUNNING_MS) }, now)).toBe(false);
  });

  it("非 running 状态一律不陈旧", () => {
    const old = iso(STALE_RUNNING_MS * 10);
    expect(isStaleRunning({ status: "done", updatedAt: old }, now)).toBe(false);
    expect(isStaleRunning({ status: "failed", updatedAt: old }, now)).toBe(false);
    expect(isStaleRunning({ status: "none", updatedAt: old }, now)).toBe(false);
  });

  it("缺 updatedAt → 不陈旧（无法判定时不误报）", () => {
    expect(isStaleRunning({ status: "running" }, now)).toBe(false);
    expect(isStaleRunning({ status: "running", updatedAt: null }, now)).toBe(false);
  });

  it("updatedAt 非法 → 不陈旧（防 NaN 比较）", () => {
    expect(isStaleRunning({ status: "running", updatedAt: "not-a-date" }, now)).toBe(false);
  });
});
