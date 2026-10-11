/**
 * #63（2026-10-12）离线单测：`/api/quote` 这条 BFF 腿的**预算与失败语义**。
 *
 * 为什么单独一个文件：本仓库既有 route 测试只覆盖 `research/ingest`／`watchlist`／
 * `market/refresh`，而 `/api/quote` 是**全局最热**的一条代理腿，此前：
 *   ① 预算写死 15s，与 ds 侧一条 stock `get_quote` 的最坏路径（`_em_request` 的
 *      `acquire()` 默认 20s ＋ 多 host 两轮 × 每发 15s）差一个量级 ⇒ 上游抖动时
 *      多 host 降级还没跑完就被掐断；
 *   ② 裸 `catch {}` 把「超时」与「连不上」压成同一句「服务没启动」（违 R16；
 *      10-11 夜 R13 实测字面 `code=600519 503 in 15792ms`，ds 侧同发 12 次全 200）。
 *
 * ⚠️ 断言打在**接线面**（真的传给 `fetch` 的那个毫秒数、真的回给调用方的文案），
 * 而不是只调纯函数——#38 那一课：纯函数绿不等于循环用了它。
 *
 * 运行方式（零出网、不起服务）：
 *     npx vitest run app/api/quote/route.test.ts
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";

import { QUOTE_TIMEOUT_MS, unreachableMessage } from "@/lib/data-service";

import { GET } from "./route";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

/** 只带 `searchParams` 的最小请求（与 market/refresh 的 route 测试同构） */
function req(query: string) {
  const url = new URL(`http://localhost:3000/api/quote${query}`);
  return { nextUrl: { searchParams: url.searchParams } } as unknown as NextRequest;
}

/** 记下 `AbortSignal.timeout(ms)` 实际收到的毫秒数——预算的**接线面**读数 */
function spyTimeout(): number[] {
  const seen: number[] = [];
  vi.spyOn(AbortSignal, "timeout").mockImplementation((ms?: number) => {
    seen.push(ms as number);
    return new AbortController().signal;
  });
  return seen;
}

describe("/api/quote BFF 预算（#63）", () => {
  it("传给 fetch 的超时 ≥ 30000ms（≥ ds acquire 的 20s 默认，留出多 host 余量）", async () => {
    const seen = spyTimeout();
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ type: "stock", code: "600519", price: 1 }), {
        status: 200,
      }),
    ) as unknown as typeof fetch;

    const res = await GET(req("?type=stock&code=600519"));

    expect(res.status).toBe(200);
    expect(seen).toHaveLength(1);
    // 🔁（C34）：把 route 里这处退回 `15_000` ⇒ 恰好这一枚红（15000 < 30000）。
    expect(seen[0]).toBeGreaterThanOrEqual(30_000);
    // 与导出的单一来源常量锁步：改常量而忘改 route 也会红。
    expect(seen[0]).toBe(QUOTE_TIMEOUT_MS);
  });
});

describe("/api/quote BFF 失败语义（#63，R16）", () => {
  it("超时 → 文案含 timeout，不再谎称 unreachable", async () => {
    spyTimeout();
    globalThis.fetch = vi.fn(() => {
      const e = new Error("The operation was aborted due to timeout");
      e.name = "TimeoutError";
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    const res = await GET(req("?type=stock&code=600519"));
    const body = (await res.json()) as { error: string };

    expect(res.status).toBe(503);
    expect(body.error).toMatch(/timeout/);
    expect(body.error).not.toMatch(/unreachable/);
  });

  it("连接被拒 → 文案为 unreachable（与超时可区分）", async () => {
    spyTimeout();
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError("fetch failed"))) as unknown as typeof fetch;

    const res = await GET(req("?type=stock&code=600519"));
    const body = (await res.json()) as { error: string };

    expect(res.status).toBe(503);
    expect(body.error).toMatch(/unreachable/);
  });

  it("route 的 503 文案与 `unreachableMessage` 同源（不许第二份措辞）", async () => {
    spyTimeout();
    const e = new Error("The operation was aborted due to timeout");
    e.name = "TimeoutError";
    globalThis.fetch = vi.fn(() => Promise.reject(e)) as unknown as typeof fetch;

    const res = await GET(req("?type=stock&code=600519"));
    const body = (await res.json()) as { error: string };

    expect(body.error).toBe(unreachableMessage(e, QUOTE_TIMEOUT_MS));
  });
});

describe("/api/quote 入参守卫（C5/C7-6，零出网）", () => {
  it("非法 type → 400 且不调用 fetch", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const res = await GET(req("?type=option&code=600519"));

    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("非法 code 字符集 → 400 且不调用 fetch", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const res = await GET(req("?type=stock&code=..%2Fetc"));

    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
