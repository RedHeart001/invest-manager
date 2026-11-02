/**
 * CR10-9 离线单测：`/api/research/start` 的来源守卫接线。
 *
 * 为什么欠这一份：一条研报任务＝`research/tasks.py` 起 daemon 线程＋4 路采集＋最多 12 发
 * LLM，而本路由此前是同族里**唯一既花钱又零来源守卫**的 POST（只 3 枚 400 字面校验）。
 * 纯函数 `checkRequestOrigin` 自己已有测，这里钉的是"**这个 route 有没有挂它、挂在花钱之前吗**"
 * ——沿 `lib/guard.test.ts` 的源码字面先例：只测纯函数会出现"函数对但没人挂它"的全绿假象。
 *
 * 覆盖面按字面（第二枚用例钉住它，防止日后把它当成鉴权补齐）：无 Origin/Referer **放行**，
 * 所以本机脚本（`web/scripts/test-p5.mjs`、curl）行为不变——本闸只拦浏览器跨站那一形。
 *
 * 运行方式（零出网、不起服务）：
 *     npx vitest run app/api/research/start/route.test.ts
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));

const startResearch = vi.fn();
vi.mock("@/lib/research", () => ({
  startResearch: (...args: unknown[]) => startResearch(...args),
}));

import { POST } from "./route";

const ROUTE_SRC = readFileSync(path.join(HERE, "route.ts"), "utf-8");

/** 最小请求：`json()` 由测试给，`nextUrl.origin` 是被比对的"本站" */
let jsonCalls = 0;
function req(
  body: unknown,
  headers: Record<string, string> = {},
  self: string = "http://localhost:3000",
) {
  return {
    nextUrl: { origin: self, searchParams: new URLSearchParams() },
    headers: new Headers(headers),
    json: async () => {
      jsonCalls += 1;
      return body;
    },
  } as unknown as NextRequest;
}

beforeEach(() => {
  jsonCalls = 0;
  startResearch.mockReset().mockResolvedValue({ id: "r-1", status: "queued" });
});

describe("CR10-9：/api/research/start 的来源守卫", () => {
  it("🔁 尺自己的牙齿＝把守卫从源码串里摘掉，上面三条字面判据必须同时失效", () => {
    // 生产文件一个字不动（在内存里造"没挂守卫"那一形）：摘掉 import 行与含 `blocked`
    // 的那四行 ⇒ 接线断言若写成常真，这里就会露馅。
    const stripped = ROUTE_SRC.split("\n")
      .filter((line) => !line.includes("blocked") && !line.includes("request-origin"))
      .join("\n");
    expect(stripped).not.toContain('import { checkRequestOrigin } from "@/lib/request-origin"');
    expect(stripped.indexOf("checkRequestOrigin(req)")).toBe(-1);
    expect(stripped).not.toContain("{ status: 403 }");
    // 反向：真文件里这三条都在（否则本用例自己就是假阳）
    expect(ROUTE_SRC).toContain("checkRequestOrigin(req)");
  });

  it("接线＝挂了 `checkRequestOrigin`，且位置在任何一次 `startResearch` 之前（挡在花钱之前）", () => {
    expect(ROUTE_SRC).toContain('import { checkRequestOrigin } from "@/lib/request-origin"');
    const originAt = ROUTE_SRC.indexOf("checkRequestOrigin(req)");
    const spendAt = ROUTE_SRC.indexOf("startResearch(");
    expect(originAt).toBeGreaterThan(-1);
    expect(spendAt).toBeGreaterThan(-1);
    expect(originAt).toBeLessThan(spendAt);
    expect(ROUTE_SRC).toContain("{ status: 403 }");
  });

  it("🔁 排除面维持＝仍不挂 `requireWriteToken`（浏览器调用方持不住密钥，挂＝设值那一刻详情页按钮死）", () => {
    expect(ROUTE_SRC).not.toContain("requireWriteToken");
  });

  it("跨站 Origin ⇒ 403 且 `startResearch` 一次都没被调（上游额度一根没动）", async () => {
    const res = await POST(req({ type: "stock", code: "600519" }, { origin: "http://evil.example" }));
    expect(res.status).toBe(403);
    expect(startResearch).not.toHaveBeenCalled();
  });

  it("🔁 无 Origin（curl／`web/scripts/test-p5.mjs` 这类本机脚本）⇒ 放行，守卫不许把它们打死", async () => {
    const res = await POST(req({ type: "stock", code: "600519" }));
    expect(res.status).toBe(200);
    expect(startResearch).toHaveBeenCalledTimes(1);
  });

  it("同源 Origin ⇒ 放行（本站按钮那一形不变）", async () => {
    const res = await POST(
      req({ type: "stock", code: "600519" }, { origin: "http://localhost:3000" }),
    );
    expect(res.status).toBe(200);
    expect(startResearch).toHaveBeenCalledTimes(1);
  });

  it("被 403 拒掉的请求连 body 都不解析（非法 type/code 也到不了 400 那一档）", async () => {
    const res = await POST(req({ type: "bogus", code: "x".repeat(99) }, { origin: "http://evil.example" }));
    expect(res.status).toBe(403);
    expect(jsonCalls).toBe(0);
    expect(startResearch).not.toHaveBeenCalled();
  });
});
