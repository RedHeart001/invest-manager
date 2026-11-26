import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";

/**
 * CR10-49：健康检查按 `refreshRunId` 读对应那一轮刷新进度。
 *
 * 普通轮（五类）与 us 发布后的独立刷新会并发写同一份进度文件；ds 在刷新腿失败时
 * 靠这里读回“跑到第几类”。读错轮次＝归因说谎，所以这条接线也要钉住。
 */

const queryRaw = vi.fn();
const refreshProgressView = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: { $queryRaw: (...args: unknown[]) => queryRaw(...args) },
}));
vi.mock("@/lib/refresh-progress", () => ({
  refreshProgressView: (...args: unknown[]) => refreshProgressView(...args),
}));

import { GET } from "./route";

function req(query = "") {
  const url = new URL(`http://localhost:3000/api/health${query}`);
  return { nextUrl: url } as unknown as NextRequest;
}

beforeEach(() => {
  queryRaw.mockReset().mockResolvedValue([{ 1: 1 }]);
  refreshProgressView.mockReset().mockReturnValue({ runId: "daily-2026-11-26", outcome: "running" });
});

describe("CR10-49：/api/health 的 refreshRunId", () => {
  it("带 refreshRunId ⇒ 只读那一轮进度", async () => {
    const res = await GET(req("?refreshRunId=daily-2026-11-26"));
    expect(res.status).toBe(200);
    expect(refreshProgressView).toHaveBeenCalledWith("daily-2026-11-26");
    expect(await res.json()).toEqual({
      status: "ok",
      db: "ok",
      refresh: { runId: "daily-2026-11-26", outcome: "running" },
    });
  });

  it("不带 refreshRunId ⇒ 沿用旧行为（最近写入的一轮）", async () => {
    const res = await GET(req());
    expect(res.status).toBe(200);
    expect(refreshProgressView).toHaveBeenCalledWith(undefined);
  });

  it("空 refreshRunId 按缺省处理，不拿空串当轮次键", async () => {
    await GET(req("?refreshRunId="));
    expect(refreshProgressView).toHaveBeenCalledWith(undefined);
  });

  it("库不可用 ⇒ 503 仍带同一轮进度，且不回显异常细节", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    queryRaw.mockRejectedValueOnce(
      new Error("connect failed: postgres://user:secret@db:5432/app"),
    );
    const res = await GET(req("?refreshRunId=us-snap-1"));
    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body).toEqual({
      status: "degraded",
      db: "unavailable",
      refresh: { runId: "daily-2026-11-26", outcome: "running" },
    });
    expect(JSON.stringify(body)).not.toContain("secret");
    expect(err).toHaveBeenCalled();
    err.mockRestore();
  });
});
