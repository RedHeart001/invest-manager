import { createServer, type Server } from "node:http";

import { Agent, setGlobalDispatcher } from "undici";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  dsGet,
  dsPost,
  PRODUCTS_BUDGET_MS,
  QUOTE_TIMEOUT_MS,
  TRANSPORT_CEILING_MS,
  US_PRODUCTS_BUDGET_MS,
  unreachableMessage,
} from "./data-service";

// CR6-P3-3：区分"超时"（AbortSignal.timeout → TimeoutError）与"连不上"，
// 此前 catch 一律报 "data service unreachable"，超时语义被吞。
const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("dsGet/dsPost 错误语义（CR6-P3-3）", () => {
  it("TimeoutError → 文案含 timeout 与毫秒数", async () => {
    globalThis.fetch = vi.fn(() => {
      const e = new Error("The operation was aborted due to timeout");
      e.name = "TimeoutError";
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    await expect(dsGet("/x", {}, 1234)).rejects.toThrow(/timeout after 1234ms/);
  });

  it("AbortError（手动取消）→ 同样归为超时类", async () => {
    globalThis.fetch = vi.fn(() => {
      const e = new Error("aborted");
      e.name = "AbortError";
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    await expect(dsGet("/x", {}, 500)).rejects.toThrow(/timeout/);
  });

  it("连接被拒绝 → 文案为 unreachable", async () => {
    globalThis.fetch = vi.fn(() => {
      const e = new TypeError("fetch failed");
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    await expect(dsGet("/x")).rejects.toThrow(/unreachable/);
  });

  it("dsPost 同样区分（TimeoutError）", async () => {
    globalThis.fetch = vi.fn(() => {
      const e = new Error("timeout");
      e.name = "TimeoutError";
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    await expect(dsPost("/x", {}, 2000)).rejects.toThrow(/timeout after 2000ms/);
  });

  // 2026-11-07 新增：undici 传输层超时经 dsGet 的端到端形态。
  // 本轮 stock 同步失败的真身＝这个形态被误报成 unreachable。
  it("dsGet：UND_ERR_HEADERS_TIMEOUT 不再被报成 unreachable（R16）", async () => {
    globalThis.fetch = vi.fn(() => {
      const e = new TypeError("fetch failed");
      (e as unknown as { cause: unknown }).cause = { code: "UND_ERR_HEADERS_TIMEOUT" };
      return Promise.reject(e);
    }) as unknown as typeof fetch;

    const err = await dsGet("/products", { type: "stock" }, 600_000).then(
      () => null,
      (e: unknown) => e as Error,
    );
    expect(err).not.toBeNull();
    expect(err?.message).not.toMatch(/unreachable/);
    expect(err?.message).toContain("UND_ERR_HEADERS_TIMEOUT");
  });
});

describe("unreachableMessage 三档（#63 / 2026-11-07 补 UND_ERR_*）", () => {
  it("UND_ERR_HEADERS_TIMEOUT（TypeError）→ 不许再说 unreachable，且要带出 code", () => {
    const e = Object.assign(new TypeError("fetch failed"), {
      cause: { code: "UND_ERR_HEADERS_TIMEOUT" },
    });
    const msg = unreachableMessage(e, 600_000);
    expect(msg).not.toMatch(/unreachable/);
    expect(msg).toMatch(/UND_ERR_HEADERS_TIMEOUT/);
    // 刻意不许写调用方的预算数——掐断它的不是这个数（见函数注释）
    expect(msg).not.toMatch(/600000|600_000/);
  });

  it("UND_ERR_BODY_TIMEOUT / UND_ERR_CONNECT_TIMEOUT 同档", () => {
    for (const code of ["UND_ERR_BODY_TIMEOUT", "UND_ERR_CONNECT_TIMEOUT"]) {
      const e = Object.assign(new TypeError("fetch failed"), { cause: { code } });
      expect(unreachableMessage(e, 1000)).toContain(code);
    }
  });

  it("真·连不上（ECONNREFUSED）仍报 unreachable——这一档不许被上面的改动吃掉", () => {
    const e = Object.assign(new TypeError("fetch failed"), {
      cause: { code: "ECONNREFUSED" },
    });
    expect(unreachableMessage(e, 30_000)).toMatch(/unreachable/);
  });

  it("裸 TypeError（无 cause）仍报 unreachable（既有行为不回退）", () => {
    expect(unreachableMessage(new TypeError("fetch failed"), 30_000)).toMatch(/unreachable/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 这一组是**真证据**：本地 server + 真 undici dispatcher，不用 mock。
// 判据不是"没抛错"，而是"上限按设定值生效"——这正是本轮修的那个旋钮。
// 时长控制在 ~1s，不拖慢门禁。装的动作在生产里由 `web/instrumentation.ts` 执行，
// 这里直接装同一组参数，验的是**机制**（那边只多了动态 import 的壳）。
// ─────────────────────────────────────────────────────────────────────────────
/** 起一个"迟迟不发响应头"的本地 server —— 只用来量传输层上限，零外网。 */
function slowHeadersServer(delayMs: number): Promise<{ server: Server; url: string }> {
  return new Promise((resolve) => {
    const server = createServer((_req, res) => {
      setTimeout(() => {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end('{"ok":true}');
      }, delayMs);
    });
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      resolve({ server, url: `http://127.0.0.1:${port}/slow` });
    });
  });
}

async function fetchOutcome(url: string): Promise<{ ms: number; code: string | null }> {
  const t0 = Date.now();
  try {
    const r = await fetch(url);
    await r.text();
    return { ms: Date.now() - t0, code: null };
  } catch (e) {
    const cause = (e as { cause?: { code?: string } })?.cause;
    return { ms: Date.now() - t0, code: cause?.code ?? (e as Error)?.name ?? "unknown" };
  }
}

describe("传输层上限真的生效（A 方案的核心断言）", () => {
  it("headersTimeout 调小 ⇒ 请求在上限处被掐断，成因是 UND_ERR_HEADERS_TIMEOUT", async () => {
    const { server, url } = await slowHeadersServer(2500);
    const original = new Agent();
    try {
      // 与生产同一条安装路径（instrumentation.ts 落的就是这两个参数）
      setGlobalDispatcher(new Agent({ headersTimeout: 600, bodyTimeout: 600 }));
      const out = await fetchOutcome(url);
      // 600ms 上限、2500ms 延迟 ⇒ 必须在上限附近断，绝不能等到 2500ms
      expect(out.code).toBe("UND_ERR_HEADERS_TIMEOUT");
      expect(out.ms).toBeLessThan(2000);
      // 两条改动合起来才闭环：这个成因要被译成"超时"而不是"连不上"
      const e = Object.assign(new TypeError("fetch failed"), { cause: { code: out.code } });
      expect(unreachableMessage(e, 600)).toMatch(/transport timeout/);
    } finally {
      setGlobalDispatcher(original);
      server.close();
    }
  }, 15_000);

  it("调大后能撑过默认 300s 之外：6000ms 上限 + 2500ms 延迟 ⇒ 成功", async () => {
    const { server, url } = await slowHeadersServer(2500);
    const original = new Agent();
    try {
      setGlobalDispatcher(new Agent({ headersTimeout: 6000, bodyTimeout: 6000 }));
      const out = await fetchOutcome(url);
      expect(out.code).toBeNull(); // 没被掐断
      expect(out.ms).toBeGreaterThanOrEqual(2400);
    } finally {
      setGlobalDispatcher(original);
      server.close();
    }
  }, 15_000);

  it("默认常量 > 全仓最大 ds 预算（不变量：传输层不许先于业务预算到期）", () => {
    // 11-12 美股乙：最大预算从生产常量算（us 1_800_000），不抄第二份数——
    // 将来谁调大任一预算而不看 TRANSPORT_CEILING_MS，会在这里红。
    const MAX_DS_BUDGET_MS = Math.max(PRODUCTS_BUDGET_MS, US_PRODUCTS_BUDGET_MS, QUOTE_TIMEOUT_MS);
    expect(TRANSPORT_CEILING_MS).toBeGreaterThan(MAX_DS_BUDGET_MS);
  });
});
