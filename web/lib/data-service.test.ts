import { afterEach, describe, expect, it, vi } from "vitest";

import { dsGet, dsPost } from "./data-service";

// CR6-P3-3：区分"超时"（AbortSignal.timeout → TimeoutError）与"连不上"，
// 此前 catch 一律报 "data-service unreachable"，超时语义被吞。
const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("dsGet/dsPost 错误语义（CR6-P3-3）", () => {
  it("TimeoutError → 文案含 timeout 与毫秒数", async () => {
    globalThis.fetch = vi.fn(() => {
      const e = new Error("The operation was aborted due to timeout");
      e.name = "TimeoutError";
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    await expect(dsGet("/x", {}, 1234)).rejects.toThrow(/timeout after 1234ms/);
  });

  it("AbortError（手动取消）→ 同样归为超时类", async () => {
    globalThis.fetch = vi.fn(() => {
      const e = new Error("aborted");
      e.name = "AbortError";
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    await expect(dsGet("/x", {}, 500)).rejects.toThrow(/timeout/);
  });

  it("连接被拒绝 → 文案为 unreachable", async () => {
    globalThis.fetch = vi.fn(() => {
      const e = new TypeError("fetch failed");
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    await expect(dsGet("/x")).rejects.toThrow(/unreachable/);
  });

  it("dsPost 同样区分（TimeoutError）", async () => {
    globalThis.fetch = vi.fn(() => {
      const e = new Error("timeout");
      e.name = "TimeoutError";
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    await expect(dsPost("/x", {}, 2000)).rejects.toThrow(/timeout after 2000ms/);
  });
});
