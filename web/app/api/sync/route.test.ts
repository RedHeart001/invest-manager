import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";

const syncType = vi.fn();
const syncAll = vi.fn();
vi.mock("@/lib/sync", () => ({
  SYNC_TYPES: ["stock", "fund", "bond", "hk", "us", "crypto"],
  syncType: (...args: unknown[]) => syncType(...args),
  syncAll: (...args: unknown[]) => syncAll(...args),
}));

import { POST } from "./route";

function req(type: string, token?: string) {
  const url = new URL(`http://localhost:3000/api/sync?type=${type}`);
  return { nextUrl: url, headers: new Headers(token ? { "x-write-token": token } : {}) } as unknown as NextRequest;
}

beforeEach(() => {
  process.env.WRITE_TOKEN = "synthetic-write-token";
  syncType.mockReset();
  syncAll.mockReset();
});
afterEach(() => { delete process.env.WRITE_TOKEN; });

describe("/api/sync WRITE_TOKEN（CR10-32）", () => {
  it.each([undefined, "wrong-token"])("无/错 token ⇒ 401，且无同步副作用", async (token) => {
    const res = await POST(req("stock", token));
    expect(res.status).toBe(401);
    expect(syncType).not.toHaveBeenCalled();
    expect(syncAll).not.toHaveBeenCalled();
  });

  it("正确 x-write-token 穿过 guard；非法参数 400 且不启动任务", async () => {
    const res = await POST(req("bogus", "synthetic-write-token"));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "unsupported type: bogus" });
    expect(syncType).not.toHaveBeenCalled();
    expect(syncAll).not.toHaveBeenCalled();
  });
});
