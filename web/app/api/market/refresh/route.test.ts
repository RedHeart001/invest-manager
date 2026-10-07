/**
 * CR9-68（#40 甲的另一半）离线单测：`/api/market/refresh` 这条腿的**接线本身**。
 *
 * 为什么欠这一份（10-06 断言强度审计登记为待拍板 #40 的 (a)）：全仓 `find web/app -name "*.test.ts*"`
 * 只有 `research/ingest` 与 `watchlist` 两枚 route 测试，而这个端点是**每日刷新腿本体**
 * （刀 3/甲-1 之后 ds 链式打的就是它）。`route.ts:56/:60/:61/:67` 那四个调用点
 * ——起跑落 `running`、逐类落 `done`、收尾落 `completed`/`failed`——此前零断言，
 * 摘掉任何一行 ① 都无感。
 *
 * 与 `lib/market-snapshot-onresult.test.ts` 的分工：那一份钉"`refreshAll` 会逐类回调"，
 * 这一份钉"**这个 route 把哪个函数当作回调交了出去**"。
 *
 * 运行方式（零出网、不起服务）：
 *     npx vitest run app/api/market/refresh/route.test.ts
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";

const log: string[] = [];
const refreshAll = vi.fn();
const startRefreshProgress = vi.fn();
const recordRefreshResult = vi.fn();
const finishRefreshProgress = vi.fn();

vi.mock("@/lib/market-snapshot", () => ({
  refreshAll: (types: string[], opts: { onResult?: (r: unknown) => void }) => refreshAll(types, opts),
}));
vi.mock("@/lib/refresh-progress", () => ({
  startRefreshProgress: (types: string[]) => startRefreshProgress(types),
  recordRefreshResult: (r: unknown) => recordRefreshResult(r),
  finishRefreshProgress: (outcome: string) => finishRefreshProgress(outcome),
}));

import { POST } from "./route";

/** 只带 `searchParams` 的最小请求：无 Origin 头＝`checkRequestOrigin` 放行（curl/测试同档） */
function req(query: string, headers: Record<string, string> = {}) {
  const url = new URL(`http://localhost:3000/api/market/refresh${query}`);
  return {
    nextUrl: { searchParams: url.searchParams, origin: url.origin },
    headers: new Headers(headers),
  } as unknown as NextRequest;
}

// 这份名单**镜像 route 里的 `SNAPSHOT_TYPES`**（#46／CR9-74 收进 us）：下面三条断言都从它派生，
// 所以"route 少给一类 / 多给一类"都会红在这里；新增类型时只有这一行需要跟着改。
const TYPES = ["stock", "fund", "bond", "crypto", "hk", "us"];

/** 替身 `refreshAll`：逐类"跑完"并按生产契约回调那一个函数（回调谁由 route 决定） */
function emulateRound(types: string[], opts: { onResult?: (r: unknown) => void }) {
  return Promise.resolve(
    types.map((type) => {
      const r = { type, total: 1, updated: 1, failedBatches: 0, tookMs: 1, snapshotAt: null };
      opts.onResult?.(r);
      return r;
    }),
  );
}

beforeEach(() => {
  log.length = 0;
  refreshAll.mockReset();
  startRefreshProgress.mockReset().mockImplementation((types: string[]) => log.push(`start:${types.join(",")}`));
  recordRefreshResult.mockReset().mockImplementation((r: { type?: string }) => log.push(`record:${r?.type}`));
  finishRefreshProgress.mockReset().mockImplementation((o: string) => log.push(`finish:${o}`));
  refreshAll.mockImplementation((types: string[], opts: { onResult?: (r: unknown) => void }) =>
    emulateRound(types, opts),
  );
});

describe("/api/market/refresh 的进度接线（CR9-68／#40 甲）", () => {
  it("`?type=all` ⇒ 起跑先把全部类型落进状态位（顺序就是执行顺序；#46 收了 us ⇒ 六类）", async () => {
    await POST(req("?type=all"));
    expect(startRefreshProgress).toHaveBeenCalledTimes(1);
    expect(startRefreshProgress.mock.calls[0][0]).toEqual(TYPES);
  });

  it("🔁 route 交出去的那个回调**就是** `recordRefreshResult`：每一类各记一次（条数跟着 TYPES，不再手写）", async () => {
    await POST(req("?type=all"));
    expect(recordRefreshResult).toHaveBeenCalledTimes(TYPES.length);
    expect(recordRefreshResult.mock.calls.map((c) => c[0].type)).toEqual(TYPES);
  });

  it("🔁 次序＝起跑 → 逐类 → 收尾 `completed`（收尾跑到逐类前面＝进度会说谎）", async () => {
    await POST(req("?type=all"));
    expect(log).toEqual([
      `start:${TYPES.join(",")}`,
      ...TYPES.map((t) => `record:${t}`),
      "finish:completed",
    ]);
  });

  it("`refreshAll` 抛 ⇒ 收尾必须落 `failed` 而不是留在 `running`，并回 500", async () => {
    refreshAll.mockRejectedValueOnce(new Error("ds down"));
    const res = await POST(req("?type=all"));
    expect(res.status).toBe(500);
    expect(log[log.length - 1]).toBe("finish:failed");
    expect(log[0]).toBe(`start:${TYPES.join(",")}`);
  });

  it("单类型也走 `refreshAll`（分两条路就会有一类刷新没有进度记录——route 注释里的原话）", async () => {
    await POST(req("?type=fund"));
    expect(refreshAll).toHaveBeenCalledTimes(1);
    expect(refreshAll.mock.calls[0][0]).toEqual(["fund"]);
    expect(log).toEqual(["start:fund", "record:fund", "finish:completed"]);
  });

  it("🔁 `?force=1` 透传进 `refreshAll` 的 opts（闸门真正的出口在这条 opts 上，不在 URL 上）", async () => {
    await POST(req("?type=fund&force=1"));
    expect((refreshAll.mock.calls[0][1] as { force?: boolean }).force).toBe(true);
  });

  it("默认不带 `force`（夜跑链那一次是普通请求，不能顺手把闸门打开）", async () => {
    await POST(req("?type=fund"));
    expect((refreshAll.mock.calls[0][1] as { force?: boolean }).force).toBe(false);
  });

  it("不支持的 type ⇒ 400 且**一个字节都不写**状态位（被拒的请求不该留下「这一轮开始了」）", async () => {
    const res = await POST(req("?type=bogus"));
    expect(res.status).toBe(400);
    expect(refreshAll).not.toHaveBeenCalled();
    expect(startRefreshProgress).not.toHaveBeenCalled();
    expect(finishRefreshProgress).not.toHaveBeenCalled();
  });

  it("跨站 Origin ⇒ 403 同样零进度（CSRF 那道闸仍在写状态位之前）", async () => {
    const res = await POST(req("?type=all", { origin: "http://evil.example" }));
    expect(res.status).toBe(403);
    expect(startRefreshProgress).not.toHaveBeenCalled();
    expect(refreshAll).not.toHaveBeenCalled();
  });
});
