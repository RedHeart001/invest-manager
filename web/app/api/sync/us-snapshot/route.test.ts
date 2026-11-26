import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";

/**
 * CR10-49：DS → Web 的 us 完整候选发布入口。
 *
 * 这一层只负责**输入形状与响应码**；幂等与保护本身由 `publishProducts` 的 SQLite
 * 事务证明（`lib/sync-publish.test.ts`）。因此这里把 `publishProducts` 钉成可编程桩，
 * 逐条验证：合法载荷原样送达、非法载荷零发布、可预期拒绝 400、意外故障 500、
 * token/origin 守卫在解析载荷之前。
 */

const h = vi.hoisted(() => {
  class PublishRejected extends Error {}
  return {
    publishProducts: vi.fn(),
    PublishRejected,
  };
});
const publishProducts = h.publishProducts;
vi.mock("@/lib/sync", () => ({
  publishProducts: (...args: unknown[]) => h.publishProducts(...args),
  PublishRejected: h.PublishRejected,
}));

import { POST } from "./route";

type ReqOptions = {
  token?: string;
  origin?: string;
  json?: () => Promise<unknown>;
};

function req(body: unknown, opts: ReqOptions = {}) {
  const url = new URL("http://localhost:3000/api/sync/us-snapshot");
  const headers = new Headers();
  if (opts.token !== undefined) headers.set("x-write-token", opts.token);
  if (opts.origin) headers.set("origin", opts.origin);
  return {
    nextUrl: url,
    headers,
    json: opts.json ?? (async () => body),
  } as unknown as NextRequest;
}

function product(code: string, over: Record<string, unknown> = {}) {
  return {
    type: "us",
    code,
    name: `Name ${code}`,
    pinyin: null,
    pinyinInitials: null,
    exchange: "NASDAQ",
    tags: ["半导体"],
    ...over,
  };
}

function payload(over: Record<string, unknown> = {}) {
  return {
    snapshotId: "20261126-020000-abcdef",
    acquisitionComplete: true,
    count: 2,
    products: [product("AAA"), product("BBB")],
    ...over,
  };
}

const OK = {
  ok: true as const,
  type: "us",
  count: 2,
  snapshotId: "20261126-020000-abcdef",
  alreadyPublished: false,
  tookMs: 1,
};

beforeEach(() => {
  process.env.WRITE_TOKEN = "synthetic-write-token";
  publishProducts.mockReset();
  publishProducts.mockResolvedValue(OK);
});

afterEach(() => {
  delete process.env.WRITE_TOKEN;
  delete process.env.ALLOWED_ORIGINS;
});

describe("CR10-49：us 候选发布入口 · 守卫", () => {
  it.each([undefined, "wrong-token"])("无/错 token ⇒ 401，且不解析载荷、不发布", async (token) => {
    const json = vi.fn(async () => payload());
    const res = await POST(req(payload(), { token, json }));
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ error: "unauthorized" });
    expect(json).not.toHaveBeenCalled();
    expect(publishProducts).not.toHaveBeenCalled();
  });

  it("跨站 Origin ⇒ 403，且不发布", async () => {
    const res = await POST(
      req(payload(), { token: "synthetic-write-token", origin: "http://evil.example" }),
    );
    expect(res.status).toBe(403);
    expect((await res.json()).error).toContain("cross-site");
    expect(publishProducts).not.toHaveBeenCalled();
  });

  it("同源 Origin 放行；ALLOWED_ORIGINS 白名单也放行", async () => {
    const same = await POST(
      req(payload(), { token: "synthetic-write-token", origin: "http://localhost:3000" }),
    );
    expect(same.status).toBe(200);
    publishProducts.mockClear();

    process.env.ALLOWED_ORIGINS = "http://ops.example:8080";
    const allowed = await POST(
      req(payload(), { token: "synthetic-write-token", origin: "http://ops.example:8080" }),
    );
    expect(allowed.status).toBe(200);
    expect(publishProducts).toHaveBeenCalledTimes(1);
  });

  it("非法 JSON ⇒ 400，且不发布", async () => {
    const res = await POST(
      req(null, {
        token: "synthetic-write-token",
        json: async () => {
          throw new SyntaxError("bad json");
        },
      }),
    );
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "invalid JSON body" });
    expect(publishProducts).not.toHaveBeenCalled();
  });
});

describe("CR10-49：us 候选发布入口 · 载荷校验", () => {
  const bad: Array<[string, unknown]> = [
    ["body 不是对象", [1, 2]],
    ["body 为 null", null],
    ["缺 snapshotId", payload({ snapshotId: undefined })],
    ["snapshotId 为空", payload({ snapshotId: "   " })],
    ["snapshotId 含路径字符", payload({ snapshotId: "../etc/passwd" })],
    ["snapshotId 过长", payload({ snapshotId: `a${"b".repeat(80)}` })],
    ["acquisitionComplete 缺失", payload({ acquisitionComplete: undefined })],
    ["acquisitionComplete=false", payload({ acquisitionComplete: false })],
    ["acquisitionComplete 非布尔 true", payload({ acquisitionComplete: "true" })],
    [
      "intentionalSubset 无产品口径声明",
      payload({ intentionalSubset: true, productPolicySubset: false }),
    ],
    ["products 非数组", payload({ products: "AAA" })],
    ["products 为空", payload({ products: [], count: 0 })],
    ["count 与 products.length 不一致", payload({ count: 3 })],
    ["product 非对象", payload({ products: [product("AAA"), "BBB"] })],
    ["product type 非 us", payload({ products: [product("AAA", { type: "stock" })] })],
    ["product code 为空", payload({ products: [product("   ")] })],
    ["product name 为空", payload({ products: [product("AAA", { name: "" })] })],
    ["pinyin 非字符串", payload({ products: [product("AAA", { pinyin: 1 })] })],
    ["exchange 过长", payload({ products: [product("AAA", { exchange: "x".repeat(41) })] })],
    ["tags 非数组", payload({ products: [product("AAA", { tags: "半导体" })] })],
    ["tags 含空项", payload({ products: [product("AAA", { tags: ["ok", "  "] })] })],
    [
      "products 超过上限",
      payload({ products: Array.from({ length: 30_001 }, () => product("X")) }),
    ],
  ];

  it.each(bad)("%s ⇒ 400，且不发布", async (_name, body) => {
    const res = await POST(req(body, { token: "synthetic-write-token" }));
    expect(res.status).toBe(400);
    const json = (await res.json()) as { ok?: boolean; error?: string };
    expect(json.ok).toBe(false);
    expect(typeof json.error).toBe("string");
    expect(publishProducts).not.toHaveBeenCalled();
  });

  it("合法载荷规范化后交给 publishProducts，并显式带 snapshotId", async () => {
    const body = payload({
      snapshotId: "  snap-trimmed  ",
      source: "sina-us-category-list",
      degraded: true,
      note: "行业口径",
      intentionalSubset: true,
      productPolicySubset: true,
      declaredCount: 3,
      acquiredCount: 3,
      products: [
        product("AAA", { pinyin: "aa", pinyinInitials: "A", tags: null }),
        product("BBB", { tags: undefined }),
        product("CCC", { tags: [] }),
      ],
      count: 3,
    });
    const res = await POST(req(body, { token: "synthetic-write-token" }));
    expect(res.status).toBe(200);
    expect(publishProducts).toHaveBeenCalledTimes(1);
    const [type, data, opts] = publishProducts.mock.calls[0] as [
      string,
      Record<string, unknown>,
      { snapshotId?: string },
    ];
    expect(type).toBe("us");
    expect(opts).toEqual({ snapshotId: "snap-trimmed" });
    expect(data).toMatchObject({
      count: 3,
      source: "sina-us-category-list",
      degraded: true,
      note: "行业口径",
      intentionalSubset: true,
      acquisitionComplete: true,
      productPolicySubset: true,
      declaredCount: 3,
      acquiredCount: 3,
      snapshotId: "snap-trimmed",
    });
    const products = data.products as Array<Record<string, unknown>>;
    expect(products).toHaveLength(3);
    expect(products[0]).toMatchObject({ type: "us", code: "AAA", tags: null });
    expect(products[1].tags).toBeUndefined();
    expect(products[2].tags).toEqual([]);
  });

  it("返回发布回执：alreadyPublished 透传，tookMs 由本层计时", async () => {
    publishProducts.mockResolvedValueOnce({ ...OK, alreadyPublished: true });
    const res = await POST(req(payload(), { token: "synthetic-write-token" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({
      ok: true,
      type: "us",
      snapshotId: OK.snapshotId,
      count: 2,
      alreadyPublished: true,
    });
  });
});

describe("CR10-49：us 候选发布入口 · 发布结果映射", () => {
  it("可预期拒绝（缩水/空载荷/完整性）⇒ 400，不重试同一份", async () => {
    publishProducts.mockResolvedValueOnce({
      ok: false,
      rejected: true,
      type: "us",
      error: "payload shrunk (2 < 10 的 70%)，已保留现有数据",
      tookMs: 1,
    });
    const res = await POST(req(payload(), { token: "synthetic-write-token" }));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({
      ok: false,
      error: "payload shrunk (2 < 10 的 70%)，已保留现有数据",
      rejected: true,
    });
  });

  it("意外故障（SQLite/事务）⇒ 500，让 DS 按同一 snapshotId 重试", async () => {
    publishProducts.mockResolvedValueOnce({
      ok: false,
      rejected: false,
      type: "us",
      error: "database is locked",
      tookMs: 1,
    });
    const res = await POST(req(payload(), { token: "synthetic-write-token" }));
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({
      ok: false,
      error: "database is locked",
      rejected: false,
    });
  });

  it("publishProducts 抛异常 ⇒ 500 固定文案，不回显路径/SQL 细节", async () => {
    const warn = vi.spyOn(console, "error").mockImplementation(() => undefined);
    publishProducts.mockRejectedValueOnce(
      new Error("ENOENT: E:\\person_projects\\secret\\runtime\\x.json"),
    );
    const res = await POST(req(payload(), { token: "synthetic-write-token" }));
    expect(res.status).toBe(500);
    const body = (await res.json()) as { ok: boolean; error: string };
    expect(body).toEqual({ ok: false, error: "us snapshot publish failed" });
    expect(JSON.stringify(body)).not.toContain("secret");
    expect(warn).toHaveBeenCalled();
  });
});
