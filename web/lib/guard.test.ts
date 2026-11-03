/**
 * G7 最小版（BACKLOG-PLAN §2.3）：`requireWriteToken` 三态 + 两条路由的接线断言。
 * 接线一半沿 jsx-key-guard/hotspot-prompt 的源码字面先例：只测纯函数会出现
 * "函数对但没人挂它"的全绿假象（R18 第四钻教训）。
 * 排除面也是断言（牙齿）：浏览器端入口 /api/hotspots/run 与 /api/research/start
 * 不许挂本守卫——浏览器持不了 secret，挂上 = 设 token 那一刻按钮死。
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextRequest } from "next/server";
import { afterEach, describe, expect, it } from "vitest";

import { requireWriteToken } from "./guard";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = (rel: string) => readFileSync(path.join(ROOT, rel), "utf-8");

function reqWith(headers: Record<string, string>): NextRequest {
  return { headers: new Headers(headers) } as NextRequest;
}

const savedToken = process.env.WRITE_TOKEN;
afterEach(() => {
  // 控制组纪律：env 是进程内共享态，逐测复原，不许漏给下一枚
  if (savedToken === undefined) delete process.env.WRITE_TOKEN;
  else process.env.WRITE_TOKEN = savedToken;
});

describe("requireWriteToken（三态）", () => {
  it("WRITE_TOKEN 未设 ⇒ 放行（本机默认态，零破坏）", () => {
    delete process.env.WRITE_TOKEN;
    expect(requireWriteToken(reqWith({}))).toBeNull();
  });

  it("WRITE_TOKEN 设空串 ⇒ 视同未设，放行", () => {
    process.env.WRITE_TOKEN = "";
    expect(requireWriteToken(reqWith({}))).toBeNull();
  });

  it("已设 + 无任何凭据头 ⇒ unauthorized", () => {
    process.env.WRITE_TOKEN = "secret-1";
    expect(requireWriteToken(reqWith({}))).toBe("unauthorized");
  });

  it("已设 + Authorization: Bearer 正确 ⇒ 放行", () => {
    process.env.WRITE_TOKEN = "secret-1";
    expect(requireWriteToken(reqWith({ authorization: "Bearer secret-1" }))).toBeNull();
  });

  it("已设 + x-write-token 正确 ⇒ 放行", () => {
    process.env.WRITE_TOKEN = "secret-1";
    expect(requireWriteToken(reqWith({ "x-write-token": "secret-1" }))).toBeNull();
  });

  it("已设 + token 错 ⇒ unauthorized（Bearer 与 x-write-token 两头形态都验）", () => {
    process.env.WRITE_TOKEN = "secret-1";
    expect(requireWriteToken(reqWith({ authorization: "Bearer wrong" }))).toBe("unauthorized");
    expect(requireWriteToken(reqWith({ "x-write-token": "wrong" }))).toBe("unauthorized");
  });

  it("已设 + Authorization 不带 Bearer 前缀 ⇒ unauthorized（不做裸值兜底）", () => {
    process.env.WRITE_TOKEN = "secret-1";
    expect(requireWriteToken(reqWith({ authorization: "secret-1" }))).toBe("unauthorized");
  });
});

describe("G7 接线（源码字面断言）", () => {
  const DS_ROUTES = ["app/api/sync/route.ts", "app/api/market/refresh/route.ts"];
  // CR10-12：浏览器端入口从两枚扩到六枚（chat / chat/sessions / search-click / watchlist 是本轮新挂来源守卫的那四枚）
  const BROWSER_ROUTES = [
    "app/api/hotspots/run/route.ts",
    "app/api/research/start/route.ts",
    "app/api/chat/route.ts",
    "app/api/chat/sessions/route.ts",
    "app/api/search/click/route.ts",
    "app/api/watchlist/route.ts",
  ];

  it.each(DS_ROUTES)("%s 挂了 requireWriteToken，且在 checkRequestOrigin 之后", (rel) => {
    const s = src(rel);
    expect(s).toContain('import { requireWriteToken } from "@/lib/guard"');
    const originAt = s.indexOf("checkRequestOrigin(req)");
    const guardAt = s.indexOf("requireWriteToken(req)");
    expect(originAt).toBeGreaterThan(-1);
    expect(guardAt).toBeGreaterThan(originAt);
    expect(s).toContain("{ status: 401 }");
  });

  it.each(BROWSER_ROUTES)("%s 不挂 requireWriteToken（浏览器端入口，排除面牙齿）", (rel) => {
    expect(src(rel)).not.toContain("requireWriteToken");
  });
});
