import { beforeEach, describe, expect, it, vi } from "vitest";

// G5（批次 D）：Watchlist 自选 API（此前只读不通写）。
// 验证：POST 白名单校验 + upsert；DELETE 校验 + 删除；GET 列表。

const upsert = vi.fn();
const deleteMany = vi.fn();
const findMany = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    watchlist: {
      upsert: (...a: unknown[]) => upsert(...a),
      deleteMany: (...a: unknown[]) => deleteMany(...a),
      findMany: (...a: unknown[]) => findMany(...a),
    },
  },
}));

import { DELETE, GET, POST } from "./route";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROUTE_SRC = readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), "route.ts"),
  "utf-8",
);

function postReq(body: unknown, headers: Record<string, string> = {}) {
  return {
    json: async () => body,
    headers: new Headers(headers),
    nextUrl: { origin: "http://localhost:3000", searchParams: new URLSearchParams() },
  } as unknown as Parameters<typeof POST>[0];
}
function delReq(url: string, headers: Record<string, string> = {}) {
  return {
    nextUrl: { origin: "http://localhost:3000", searchParams: new URLSearchParams(url.split("?")[1] ?? "") },
    headers: new Headers(headers),
  } as unknown as Parameters<typeof DELETE>[0];
}

describe("watchlist API（G5）", () => {
  beforeEach(() => {
    upsert.mockReset().mockResolvedValue({});
    deleteMany.mockReset().mockResolvedValue({ count: 1 });
    findMany.mockReset().mockResolvedValue([]);
  });

  it("POST 合法 → upsert 并返回 ok", async () => {
    const res = await POST(postReq({ type: "stock", code: "600519", name: "贵州茅台" }));
    expect(res.status).toBe(200);
    expect(upsert).toHaveBeenCalledTimes(1);
    const arg = upsert.mock.calls[0][0] as { where: { type_code: { type: string; code: string } } };
    expect(arg.where.type_code).toEqual({ type: "stock", code: "600519" });
  });

  it("POST 非法 type → 400", async () => {
    const res = await POST(postReq({ type: "option", code: "600519" }));
    expect(res.status).toBe(400);
    expect(upsert).not.toHaveBeenCalled();
  });

  it("POST 非法 code 字符集 → 400", async () => {
    const res = await POST(postReq({ type: "stock", code: "../../etc/passwd" }));
    expect(res.status).toBe(400);
  });

  it("DELETE 合法 → 删除", async () => {
    const res = await DELETE(delReq("?type=stock&code=600519"));
    expect(res.status).toBe(200);
    expect(deleteMany).toHaveBeenCalledWith({ where: { type: "stock", code: "600519" } });
  });

  it("DELETE 非法 type → 400", async () => {
    const res = await DELETE(delReq("?type=bad&code=600519"));
    expect(res.status).toBe(400);
    expect(deleteMany).not.toHaveBeenCalled();
  });

  it("GET → 返回 items", async () => {
    findMany.mockResolvedValue([{ type: "stock", code: "600519", name: "贵州茅台" }]);
    const res = await GET();
    const body = (await res.json()) as { items: unknown[] };
    expect(res.status).toBe(200);
    expect(body.items).toHaveLength(1);
  });

  // ---- CR10-12：来源守卫（看板那枚「watchlist 两枚写腿」的 POST 那半） ----
  it("🔁 尺自己的牙齿＝在内存里摘掉守卫行，两条字面判据必须同时失效", () => {
    const stripped = ROUTE_SRC.split("\n")
      .filter((line) => !line.includes("blocked") && !line.includes("request-origin"))
      .join("\n");
    expect(stripped.indexOf("checkRequestOrigin(req)")).toBe(-1);
    expect(stripped).not.toContain("{ status: 403 }");
    expect(ROUTE_SRC).toContain("checkRequestOrigin(req)");
  });

  it("接线＝两枚写 handler 各自的守卫都排在解析之前（逐 handler 切片，不是整文件 indexOf）", () => {
    const postSeg = ROUTE_SRC.slice(
      ROUTE_SRC.indexOf("export async function POST"),
      ROUTE_SRC.indexOf("export async function DELETE"),
    );
    const delSeg = ROUTE_SRC.slice(ROUTE_SRC.indexOf("export async function DELETE"));
    expect(postSeg.indexOf("checkRequestOrigin(req)")).toBeLessThan(postSeg.indexOf("req.json("));
    const delGuardAt = delSeg.indexOf("checkRequestOrigin(req)");
    expect(delGuardAt).toBeGreaterThan(-1);
    expect(delGuardAt).toBeLessThan(delSeg.indexOf("req.nextUrl.searchParams"));
  });

  it("POST 跨站 Origin → 403 且不 upsert", async () => {
    const res = await POST(postReq({ type: "stock", code: "600519" }, { origin: "http://evil.example" }));
    expect(res.status).toBe(403);
    expect(upsert).not.toHaveBeenCalled();
  });

  it("🔁 POST 无 Origin（本机脚本那一形）→ 放行，守卫不许把它们打死", async () => {
    const res = await POST(postReq({ type: "stock", code: "600519", name: "贵州茅台" }));
    expect(res.status).toBe(200);
    expect(upsert).toHaveBeenCalledTimes(1);
  });

  it("DELETE 跨站 Origin → 403 且不删（CR10-20 翻面：原「刻意没挂⇒200」那枚读数作废）", async () => {
    const res = await DELETE(delReq("?type=stock&code=600519", { origin: "http://evil.example" }));
    expect(res.status).toBe(403);
    expect(deleteMany).not.toHaveBeenCalled();
  });

  it("🔁 DELETE 无 Origin（本机脚本那一形）→ 放行真删，守卫不许把它们打死", async () => {
    const res = await DELETE(delReq("?type=stock&code=600519"));
    expect(res.status).toBe(200);
    expect(deleteMany).toHaveBeenCalledTimes(1);
  });

  it("DELETE 同源 Origin → 200", async () => {
    const res = await DELETE(delReq("?type=stock&code=600519", { origin: "http://localhost:3000" }));
    expect(res.status).toBe(200);
    expect(deleteMany).toHaveBeenCalledTimes(1);
  });
});
