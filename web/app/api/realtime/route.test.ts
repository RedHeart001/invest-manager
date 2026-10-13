/**
 * CR9-92（OPT-3 1a）离线单测：`/api/realtime` 这条 BFF 腿的预算、透传与入参守卫。
 *
 * 运行方式（零出网、不起服务）：
 *     npx vitest run app/api/realtime/route.test.ts
 *
 * ⚠️ 断言打在**接线面**（真的传给 `fetch` 的毫秒数与那串 `parts`），不是只调纯函数
 * （`#38` 那一课；`/api/quote/route.test.ts` 同形）。
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";

import { REALTIME_BUDGET_MS } from "@/lib/realtime";

import { GET } from "./route";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

function req(query: string) {
  const url = new URL(`http://localhost:3000/api/realtime${query}`);
  return { nextUrl: { searchParams: url.searchParams } } as unknown as NextRequest;
}

const OK_BODY = {
  type: "stock",
  code: "600519",
  observedAt: "2026-10-13T09:31:02",
  parts: ["price", "intraday"],
  price: { price: 1250, source: "tencent", timestamp: "2026-10-13T09:31:00", currency: "CNY" },
  intraday: { interval: "1m", date: "2026-10-13", bars: 3, lastAt: "2026-10-13 09:32", source: "tencent", points: [] },
  crossChecked: true,
  verifyVerdict: "agree",
  consensus: { verdict: "agree", diffPct: 0.0, thresholdPct: 0.5, provisional: true, basis: "f" },
  hasTodayData: true,
  intradayDateIsToday: true,
  wired: true,
  sources: [],
  degraded: false,
  note: null,
};

function stubFetch(status = 200, body: unknown = OK_BODY) {
  const seen: string[] = [];
  globalThis.fetch = vi.fn(async (input: unknown) => {
    seen.push(String(input));
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return seen;
}

function spyTimeout(): number[] {
  const seen: number[] = [];
  vi.spyOn(AbortSignal, "timeout").mockImplementation((ms?: number) => {
    seen.push(ms as number);
    return new AbortController().signal;
  });
  return seen;
}

describe("/api/realtime 预算（CR9-88 的 §B 契约）", () => {
  it("传给 fetch 的超时就是 `REALTIME_BUDGET_MS`，且它 ≥ ds 串行跑腿的最坏 9s（3 条腿 × 3s）", async () => {
    const seen = spyTimeout();
    stubFetch();
    const res = await GET(req("?type=stock&code=600519"));
    expect(res.status).toBe(200);
    expect(seen).toEqual([REALTIME_BUDGET_MS]);
    // 🔁（C34）：把 `REALTIME_BUDGET_MS` 改小到 9000 以下 ⇒ 恰好这一枚红
    expect(REALTIME_BUDGET_MS).toBeGreaterThanOrEqual(3 * 3_000);
  });

  it("预算不许长成第二条 20s 排队：它盖住最坏跑腿就够了（实时区那条红线的 web 侧那半）", () => {
    expect(REALTIME_BUDGET_MS).toBeLessThan(20_000);
  });
});

describe("/api/realtime 透传（两个节奏住在请求上）", () => {
  it("`parts` 原样带到 ds：只问现价那一跳不能悄悄变成两条腿都跑", async () => {
    spyTimeout();
    const seen = stubFetch();
    await GET(req("?type=stock&code=600519&parts=price"));
    expect(seen[0]).toContain("parts=price");
    expect(seen[0]).not.toContain("parts=price%2Cintraday");
  });

  it("不带 `parts` 时默认两条腿都取（10-13 A 窗那类一次取全的调用方不必改写法）", async () => {
    spyTimeout();
    const seen = stubFetch();
    await GET(req("?type=stock&code=600519"));
    expect(seen[0]).toContain("parts=price%2Cintraday");
  });
});

describe("/api/realtime 入参守卫（C5/C7-6，零出网）", () => {
  it("非法 type → 400 且一次 fetch 都不发", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const res = await GET(req("?type=option&code=600519"));
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("非法 code 字符集 → 400 且一次 fetch 都不发", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const res = await GET(req("?type=stock&code=..%2Fetc"));
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("/api/realtime 失败语义", () => {
  it("ds 的 400（没登记腿的类型／写了不存在的腿）保持 400，不许压成 502", async () => {
    spyTimeout();
    stubFetch(400, { detail: "unsupported parts" });
    const res = await GET(req("?type=nope&code=600519&parts=price,intraday"));
    expect(res.status).toBe(400);
  });

  it("ds 500/连不上 → 502，body 里带那句原因（R16：失败原因如实）", async () => {
    spyTimeout();
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError("fetch failed"))) as unknown as typeof fetch;
    const res = await GET(req("?type=stock&code=600519"));
    const body = (await res.json()) as { error: string };
    expect(res.status).toBe(502);
    expect(body.error).toMatch(/unreachable/);
  });

  it("ds 正常响应整份透传（`hasTodayData` 的三态不许在这一层被归一成布尔）", async () => {
    spyTimeout();
    stubFetch(200, { ...OK_BODY, hasTodayData: null, intradayDateIsToday: null, parts: ["price"] });
    const res = await GET(req("?type=stock&code=600519&parts=price"));
    const body = (await res.json()) as typeof OK_BODY;
    expect(body.hasTodayData).toBeNull();
    expect(body.intradayDateIsToday).toBeNull();
    expect(body.parts).toEqual(["price"]);
  });
});
