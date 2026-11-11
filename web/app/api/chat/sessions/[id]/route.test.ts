/**
 * CR10-20 离线单测：`/api/chat/sessions/[id]` 的 DELETE 来源守卫（纵深防御补齐，本件是该路由首枚测试）。
 * GET（读接口）刻意不挂＝排除面断言守着。守卫挡在 `await ctx.params` 之前（解析路径参数也算解析）。
 * 运行：`npx vitest run "app/api/chat/sessions/[id]/route.test.ts"`（零出网，@/lib/* 全替身）
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROUTE_SRC = readFileSync(path.join(HERE, "route.ts"), "utf-8");

const deleteSession = vi.fn().mockResolvedValue(undefined);
const getMessages = vi.fn().mockResolvedValue([]);
const findUnique = vi.fn();

vi.mock("@/lib/chat", () => ({
  deleteSession: (...a: unknown[]) => deleteSession(...a),
  getMessages: (...a: unknown[]) => getMessages(...a),
}));
vi.mock("@/lib/prisma", () => ({
  prisma: { chatSession: { findUnique: (...a: unknown[]) => findUnique(...a) } },
}));

import { DELETE, GET } from "./route";

let paramsAwaits = 0;
/** thenable 替身：只有真被 await 才计数＝证明守卫挡在解析路径参数之前 */
function ctx(id = "s-1") {
  return {
    params: {
      then: (resolve: (v: { id: string }) => void) => {
        paramsAwaits += 1;
        resolve({ id });
      },
    },
  } as unknown as { params: Promise<{ id: string }> };
}
function req(headers: Record<string, string> = {}) {
  return {
    nextUrl: { origin: "http://localhost:3000" },
    headers: new Headers(headers),
  } as unknown as NextRequest;
}

beforeEach(() => {
  paramsAwaits = 0;
  deleteSession.mockClear().mockResolvedValue(undefined);
  getMessages.mockClear().mockResolvedValue([]);
  findUnique.mockClear().mockResolvedValue({ id: "s-1", title: "新会话", createdAt: new Date() });
});

describe("CR10-20：/api/chat/sessions/[id] 的 DELETE 守卫", () => {
  it("🔁 尺自己的牙齿＝在内存里摘掉守卫行，字面判据必须失效", () => {
    const stripped = ROUTE_SRC.split("\n")
      .filter((line) => !line.includes("blocked") && !line.includes("request-origin"))
      .join("\n");
    expect(stripped.indexOf("checkRequestOrigin(req)")).toBe(-1);
    expect(stripped).not.toContain("{ status: 403 }");
    expect(ROUTE_SRC).toContain("checkRequestOrigin(req)");
  });

  it("接线＝DELETE 的守卫排在 await ctx.params 之前；GET 段不含守卫（读接口排除面）", () => {
    const getSeg = ROUTE_SRC.slice(
      ROUTE_SRC.indexOf("export async function GET"),
      ROUTE_SRC.indexOf("export async function DELETE"),
    );
    const delSeg = ROUTE_SRC.slice(ROUTE_SRC.indexOf("export async function DELETE"));
    expect(getSeg).not.toContain("checkRequestOrigin");
    const guardAt = delSeg.indexOf("checkRequestOrigin(req)");
    expect(guardAt).toBeGreaterThan(-1);
    expect(guardAt).toBeLessThan(delSeg.indexOf("await ctx.params"));
  });

  it("跨站 Origin ⇒ 403、不删、路径参数一次都不解析", async () => {
    const res = await DELETE(req({ origin: "http://evil.example" }), ctx());
    expect(res.status).toBe(403);
    expect(deleteSession).not.toHaveBeenCalled();
    expect(paramsAwaits).toBe(0);
  });

  it("🔁 无 Origin（本机脚本那一形）⇒ 放行真删", async () => {
    const res = await DELETE(req(), ctx());
    expect(res.status).toBe(200);
    expect(deleteSession).toHaveBeenCalledWith("s-1");
    expect(paramsAwaits).toBe(1);
  });

  it("同源 Origin ⇒ 200", async () => {
    const res = await DELETE(req({ origin: "http://localhost:3000" }), ctx());
    expect(res.status).toBe(200);
    expect(deleteSession).toHaveBeenCalledTimes(1);
  });

  it("会话不存在（P2025）⇒ 404，不被守卫吃掉", async () => {
    deleteSession.mockRejectedValueOnce({ code: "P2025" });
    const res = await DELETE(req(), ctx("missing"));
    expect(res.status).toBe(404);
  });

  it("GET 不受影响＝照常返回历史", async () => {
    const res = await GET(req(), ctx());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { id: string; messages: unknown[] };
    expect(body.id).toBe("s-1");
    expect(getMessages).toHaveBeenCalledWith("s-1");
  });
});