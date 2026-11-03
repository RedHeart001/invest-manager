/**
 * CR10-12 离线单测：`/api/chat` 的来源守卫接线。
 *
 * 为什么这一枚最重：POST 是简单请求 ⇒ 外站页面用 `sendBeacon`／`no-cors`＋`text/plain` 装 JSON
 * 就能打进来（`Request.json()` 不看 Content-Type），而打进来一发＝一次真 LLM 调用（`MAX_TOOL_ROUNDS=4`
 * 轮工具循环），正文命中 `INTENT_RE` 还要 `startResearch` 起整轮研报（4 路采集＋最多 12 发 LLM）。
 * 全站此前只有四枚 POST 挂了守卫，这一枚是**最该挂而没挂**的那一枚。
 *
 * 🔁 覆盖面按字面（第 4 条钉住）＝无 Origin/Referer **放行**，所以本机脚本与同源 UI 行为不变；
 * 本闸只拦浏览器跨站那一形，**不是鉴权**（完整身份鉴权＝G7，`requireWriteToken` 仍不挂＝浏览器持不住密钥）。
 *
 * 运行（零出网、不起服务；`@/lib/*` 全部替身，`chatStream` 一根 token 都不发）：
 *     npx vitest run app/api/chat/route.test.ts
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROUTE_SRC = readFileSync(path.join(HERE, "route.ts"), "utf-8");

const appendMessage = vi.fn().mockResolvedValue(undefined);
const createSession = vi.fn().mockResolvedValue({ id: "s-1" });
const getMessages = vi.fn().mockResolvedValue([]);
const startResearch = vi.fn().mockResolvedValue({ status: "queued" });
const chatStreamCalls: unknown[] = [];

vi.mock("@/lib/llm", () => ({
  LlmNotConfiguredError: class LlmNotConfiguredError extends Error {},
  chatStream: (arg: unknown) => {
    chatStreamCalls.push(arg);
    return (async function* nothing() {})();
  },
}));
vi.mock("@/lib/gateway", () => ({
  buildSystemPrompt: () => ({ prompt: "SYS", activeSkills: [] }),
  executeAgentTool: vi.fn(),
  getAgentTools: async () => [],
}));
vi.mock("@/lib/skills", () => ({
  skillRouterMode: () => "keyword",
  createSkillLoader: () => ({ def: null, run: () => ({ ok: true, summary: "" }), loaded: () => [] }),
}));
vi.mock("@/lib/chat", () => ({
  appendMessage: (...a: unknown[]) => appendMessage(...a),
  createSession: (...a: unknown[]) => createSession(...a),
  getMessages: (...a: unknown[]) => getMessages(...a),
}));
vi.mock("@/lib/chat-history", () => ({ repairToolPairing: (m: unknown[]) => m }));
vi.mock("@/lib/research", () => ({ startResearch: (...a: unknown[]) => startResearch(...a) }));
vi.mock("@/lib/research-target", () => ({ extractResearchTarget: () => null }));
vi.mock("@/lib/context-budget", () => ({ trimContext: (m: unknown[]) => m }));
vi.mock("@/lib/prisma", () => ({ prisma: { chatSession: { findUnique: vi.fn() } } }));

import { POST } from "./route";

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
  chatStreamCalls.length = 0;
  appendMessage.mockClear();
  createSession.mockClear();
  startResearch.mockClear();
});

describe("CR10-12：/api/chat 的来源守卫", () => {
  it("🔁 尺自己的牙齿＝在内存里摘掉守卫行，三条字面判据必须同时失效", () => {
    const stripped = ROUTE_SRC
      .split("\n")
      .filter((line) => !line.includes("blocked") && !line.includes("request-origin"))
      .join("\n");
    expect(stripped).not.toContain('import { checkRequestOrigin } from "@/lib/request-origin"');
    expect(stripped.indexOf("checkRequestOrigin(req)")).toBe(-1);
    expect(stripped).not.toContain("{ status: 403 }");
    expect(ROUTE_SRC).toContain("checkRequestOrigin(req)");
  });

  it("接线＝守卫排在第一次读 body 之前，因而也排在 `startResearch` 之前", () => {
    const guardAt = ROUTE_SRC.indexOf("checkRequestOrigin(req)");
    expect(guardAt).toBeGreaterThan(-1);
    expect(guardAt).toBeLessThan(ROUTE_SRC.indexOf("req.json("));
    expect(guardAt).toBeLessThan(ROUTE_SRC.indexOf("startResearch("));
    expect(ROUTE_SRC).toContain("{ status: 403 }");
  });

  it("🔁 排除面维持＝仍不挂 `requireWriteToken`（浏览器调用方持不住密钥）", () => {
    expect(ROUTE_SRC).not.toContain("requireWriteToken");
  });

  it("跨站 Origin ⇒ 403，且 body 一次都没解析、会话与消息一行都没写", async () => {
    const res = await POST(req({ message: "深度分析 600519" }, { origin: "http://evil.example" }));
    expect(res.status).toBe(403);
    expect(jsonCalls).toBe(0);
    expect(appendMessage).not.toHaveBeenCalled();
    expect(createSession).not.toHaveBeenCalled();
    expect(startResearch).not.toHaveBeenCalled();
    expect(chatStreamCalls).toHaveLength(0);
  });

  it("🔁 无 Origin（curl／`web/scripts/test-p2.mjs` 这类本机脚本）⇒ 照旧放行", async () => {
    const res = await POST(req({ message: "今天 A 股怎么走" }));
    expect(res.status).toBe(200);
    expect(appendMessage).toHaveBeenCalledWith("s-1", "user", "今天 A 股怎么走");
  });

  it("同源 Origin ⇒ 放行（本站聊天框那一形不变）", async () => {
    const res = await POST(req({ message: "你好" }, { origin: "http://localhost:3000" }));
    expect(res.status).toBe(200);
    expect(appendMessage).toHaveBeenCalledTimes(1);
  });
});
