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
  return reqQuery(`?type=${type}`, token);
}

function reqQuery(query: string, token?: string) {
  const url = new URL(`http://localhost:3000/api/sync${query}`);
  return {
    nextUrl: url,
    headers: new Headers(token ? { "x-write-token": token } : {}),
  } as unknown as NextRequest;
}

const TOKEN = "synthetic-write-token";

beforeEach(() => {
  process.env.WRITE_TOKEN = TOKEN;
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
    const res = await POST(req("bogus", TOKEN));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "unsupported type: bogus" });
    expect(syncType).not.toHaveBeenCalled();
    expect(syncAll).not.toHaveBeenCalled();
  });
});

describe("CR10-49：?types= 普通轮名单", () => {
  it("按请求顺序传五类，us 不在普通轮名单里", async () => {
    syncAll.mockResolvedValueOnce([
      { type: "fund", tookMs: 1 },
      { type: "stock", tookMs: 1 },
      { type: "bond", tookMs: 1 },
      { type: "crypto", tookMs: 1 },
      { type: "hk", tookMs: 1 },
    ]);
    const res = await POST(reqQuery("?types=fund,stock,bond,crypto,hk", TOKEN));
    expect(res.status).toBe(200);
    expect(syncType).not.toHaveBeenCalled();
    expect(syncAll).toHaveBeenCalledTimes(1);
    expect(syncAll.mock.calls[0]).toEqual([
      ["fund", "stock", "bond", "crypto", "hk"],
      { force: false },
    ]);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(body.collecting).toBeUndefined();
    expect(body.results).toHaveLength(5);
  });

  it("重复类型去重且保持首次出现顺序", async () => {
    syncAll.mockResolvedValueOnce([
      { type: "stock", tookMs: 1 },
      { type: "fund", tookMs: 1 },
    ]);
    const res = await POST(reqQuery("?types=stock,fund,stock", TOKEN));
    expect(res.status).toBe(200);
    expect(syncAll.mock.calls[0][0]).toEqual(["stock", "fund"]);
  });

  it.each([
    ["空名单", "?types=", "unsupported types: (empty)"],
    ["全是空白", "?types=%20,%20", "unsupported types: (empty)"],
    ["混入未知类型", "?types=stock,bogus", "unsupported types: bogus"],
  ])("%s ⇒ 400，不启动任何同步", async (_name, query, error) => {
    const res = await POST(reqQuery(query, TOKEN));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error });
    expect(syncType).not.toHaveBeenCalled();
    expect(syncAll).not.toHaveBeenCalled();
  });

  it("?type= 优先于 ?types=（单类手动入口不被名单覆盖）", async () => {
    syncType.mockResolvedValueOnce({ type: "us", collecting: true, jobState: "waiting", tookMs: 1 });
    const res = await POST(reqQuery("?type=us&types=stock,fund", TOKEN));
    expect(res.status).toBe(200);
    expect(syncAll).not.toHaveBeenCalled();
    expect(syncType).toHaveBeenCalledTimes(1);
    expect(syncType.mock.calls[0]).toEqual(["us", { force: false }]);
  });

  it("?force=1 透传到 syncAll/syncType", async () => {
    syncAll.mockResolvedValueOnce([{ type: "stock", tookMs: 1 }]);
    await POST(reqQuery("?types=stock,fund&force=1", TOKEN));
    expect(syncAll.mock.calls[0][1]).toEqual({ force: true });

    syncType.mockResolvedValueOnce({ type: "stock", tookMs: 1 });
    await POST(reqQuery("?type=stock&force=1", TOKEN));
    expect(syncType.mock.calls[0][1]).toEqual({ force: true });
  });
});

describe("CR10-49：collecting 既不是成功也不是失败", () => {
  it("us 仍在采集 ⇒ 整轮 ok=false，但顶层 collecting/collectingTypes 显式分流", async () => {
    const results = [
      { type: "stock", tookMs: 1 },
      { type: "us", collecting: true, jobState: "collecting", tookMs: 1 },
    ];
    syncAll.mockResolvedValueOnce(results);
    const res = await POST(reqQuery("?types=stock,us", TOKEN));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.ok).toBe(false);
    expect(body.collecting).toBe(true);
    expect(body.collectingTypes).toEqual(["us"]);
    expect(body.note).toContain("持久化采集");
    expect(body.results).toEqual(results);
    // collecting 不是 error：结果里没有失败文案，DS 靠 ok/collecting 分账。
    expect(body.results[1].error).toBeUndefined();
  });

  it("全部正常 ⇒ ok=true，且不出现 collecting 键（旧消费方形态不变）", async () => {
    syncAll.mockResolvedValueOnce([
      { type: "stock", tookMs: 1, skipped: true },
      { type: "fund", tookMs: 1 },
    ]);
    const res = await POST(reqQuery("?types=stock,fund", TOKEN));
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect("collecting" in body).toBe(false);
    expect("collectingTypes" in body).toBe(false);
    expect("note" in body).toBe(false);
  });

  it("collecting 与真实失败并存 ⇒ ok=false，只把 collecting 类型列进 collectingTypes", async () => {
    syncAll.mockResolvedValueOnce([
      { type: "bond", tookMs: 1, error: "upstream 502" },
      { type: "us", collecting: true, jobState: "waiting", tookMs: 1 },
    ]);
    const res = await POST(reqQuery("?types=bond,us", TOKEN));
    const body = await res.json();
    expect(body.ok).toBe(false);
    expect(body.collectingTypes).toEqual(["us"]);
    expect(body.results[0].error).toBe("upstream 502");
  });
});
