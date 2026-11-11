/**
 * CR10-12／CR10-20 离线单测：`/api/chat/sessions` 的 POST＋PUT 来源守卫。
 *
 * POST 是简单请求 ⇒ 外站 `sendBeacon` 就能打进来，而这一枚**body 解析失败也照建会话**
 * （`route.ts` 里那句 `catch` 把"没有 body"当默认标题「新会话」）＝拒绝服务式的垃圾行制造机。
 * PUT 在 CR10-12 时判为非简单请求（浏览器必先预检、全站零 CORS 头 ⇒ 外站驱动不到）缓办；
 * CR10-20（2026-11-12 主人拍板）补齐＝纵深防御。原"PUT 刻意没挂⇒跨站走 400"那枚反向读数已翻面成 403。
 *
 * 运行：`npx vitest run app/api/chat/sessions/route.test.ts`（零出网，`@/lib/*` 全替身）
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROUTE_SRC = readFileSync(path.join(HERE, "route.ts"), "utf-8");

const createSession = vi.fn().mockResolvedValue({ id: "s-1", title: "新会话" });
const appendMessage = vi.fn().mockResolvedValue(undefined);
const listSessions = vi.fn().mockResolvedValue([]);

vi.mock("@/lib/chat", () => ({
  createSession: (...a: unknown[]) => createSession(...a),
  appendMessage: (...a: unknown[]) => appendMessage(...a),
  listSessions: (...a: unknown[]) => listSessions(...a),
}));
vi.mock("@/lib/prisma", () => ({
  prisma: { chatSession: { findUnique: vi.fn().mockResolvedValue({ id: "s-1" }) } },
}));

import { POST, PUT } from "./route";

let jsonCalls = 0;
function req(body: unknown, headers: Record<string, string> = {}) {
  return {
    nextUrl: { origin: "http://localhost:3000", searchParams: new URLSearchParams() },
    headers: new Headers(headers),
    json: async () => {
      jsonCalls += 1;
      return body;
    },
  } as unknown as NextRequest;
}

beforeEach(() => {
  jsonCalls = 0;
  createSession.mockClear();
  appendMessage.mockClear();
});

describe("CR10-12／CR10-20：/api/chat/sessions 的 POST＋PUT 守卫", () => {
  it("🔁 尺自己的牙齿＝在内存里摘掉守卫行，三条字面判据必须同时失效", () => {
    const stripped = ROUTE_SRC
      .split("\n")
      .filter((line) => !line.includes("blocked") && !line.includes("request-origin"))
      .join("\n");
    expect(stripped.indexOf("checkRequestOrigin(req)")).toBe(-1);
    expect(stripped).not.toContain("{ status: 403 }");
    expect(ROUTE_SRC).toContain("checkRequestOrigin(req)");
  });

  it("接线＝两枚写 handler 各自的守卫都排在第一次读 body 之前（逐 handler 切片）", () => {
    const postSeg = ROUTE_SRC.slice(
      ROUTE_SRC.indexOf("export async function POST"),
      ROUTE_SRC.indexOf("export async function PUT"),
    );
    const putSeg = ROUTE_SRC.slice(ROUTE_SRC.indexOf("export async function PUT"));
    expect(postSeg.indexOf("checkRequestOrigin(req)")).toBeLessThan(postSeg.indexOf("req.json("));
    const putGuardAt = putSeg.indexOf("checkRequestOrigin(req)");
    expect(putGuardAt).toBeGreaterThan(-1);
    expect(putGuardAt).toBeLessThan(putSeg.indexOf("req.json("));
  });

  it("跨站 Origin ⇒ 403 且一行会话都不建", async () => {
    const res = await POST(req({ title: "垃圾行" }, { origin: "http://evil.example" }));
    expect(res.status).toBe(403);
    expect(jsonCalls).toBe(0);
    expect(createSession).not.toHaveBeenCalled();
  });

  it("🔁 无 Origin ⇒ 放行（本机脚本与 `test-p2.mjs` 这类回环不许被挡）", async () => {
    const res = await POST(req({ title: "新会话" }));
    expect(res.status).toBe(200);
    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it("PUT 跨站 Origin ⇒ 403 且 body 一次都不读（CR10-20 翻面：原「刻意没挂⇒400」那枚读数作废）", async () => {
    const res = await PUT(req({}, { origin: "http://evil.example" }));
    expect(res.status).toBe(403);
    expect(jsonCalls).toBe(0);
    expect(appendMessage).not.toHaveBeenCalled();
  });

  it("🔁 PUT 无 Origin（本机脚本那一形）⇒ 放行，走既有校验档", async () => {
    const res = await PUT(req({ sessionId: "s-1", role: "user", content: "你好" }));
    expect(res.status).toBe(200);
    expect(appendMessage).toHaveBeenCalledTimes(1);
  });
});
