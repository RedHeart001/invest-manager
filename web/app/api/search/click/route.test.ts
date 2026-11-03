/**
 * CR10-12 离线单测：`/api/search/click` 的来源守卫。
 *
 * 这一枚往 `SearchClickLog` 写行，而那张表**就是**排序加权读的历史点击信号（`lib/search.ts` 消费）⇒
 * 外站可用 `sendBeacon`（简单请求，不预检）无界插入，既撑行数又把排序信号按它指定的
 * `query/type/code` 加权。长度上限（`:22` 的 `slice`）挡不住"能不能写"，只挡"一行有多长"。
 *
 * 🔁 反向样本同族：无 Origin ⇒ 放行（本机脚本与本站 UI 那一形不变）。
 * 运行：`npx vitest run app/api/search/click/route.test.ts`
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROUTE_SRC = readFileSync(path.join(HERE, "route.ts"), "utf-8");

const create = vi.fn().mockResolvedValue({});
vi.mock("@/lib/prisma", () => ({ prisma: { searchClickLog: { create: (...a: unknown[]) => create(...a) } } }));

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
  create.mockClear();
});

describe("CR10-12：/api/search/click 的来源守卫", () => {
  it("🔁 尺自己的牙齿＝在内存里摘掉守卫行，两条字面判据必须同时失效", () => {
    const stripped = ROUTE_SRC
      .split("\n")
      .filter((line) => !line.includes("blocked") && !line.includes("request-origin"))
      .join("\n");
    expect(stripped.indexOf("checkRequestOrigin(req)")).toBe(-1);
    expect(stripped).not.toContain("{ status: 403 }");
    expect(ROUTE_SRC).toContain("checkRequestOrigin(req)");
  });

  it("接线＝守卫排在第一次读 body 之前", () => {
    expect(ROUTE_SRC.indexOf("checkRequestOrigin(req)")).toBeLessThan(ROUTE_SRC.indexOf("req.json("));
  });

  it("跨站 Origin ⇒ 403，`SearchClickLog` 一行都没写", async () => {
    const res = await POST(
      req({ query: "茅台", type: "stock", code: "600519" }, { origin: "http://evil.example" }),
    );
    expect(res.status).toBe(403);
    expect(jsonCalls).toBe(0);
    expect(create).not.toHaveBeenCalled();
  });

  it("🔁 无 Origin ⇒ 放行并照写（本机脚本与本站 UI 那一形不变）", async () => {
    const res = await POST(req({ query: "茅台", type: "stock", code: "600519" }));
    expect(res.status).toBe(200);
    expect(create).toHaveBeenCalledTimes(1);
  });
});
