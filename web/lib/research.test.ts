import { beforeEach, describe, expect, it, vi } from "vitest";

// CR6-P1-1 回归测试：/research/start 用 409 表达"被拒"，而 dsPost 对任何
// 非 2xx 都抛 DataServiceError。修复前该异常直接落入"提交失败"分支，
// 把当日限次/并发去重误写成 failed，且 rejected 分支与 watcher 登记成为死代码。

const upsert = vi.fn();
const findUnique = vi.fn();
const update = vi.fn();

vi.mock("./prisma", () => ({
  prisma: {
    researchReport: {
      findUnique: (...a: unknown[]) => findUnique(...a),
      upsert: (...a: unknown[]) => upsert(...a),
      update: (...a: unknown[]) => update(...a),
    },
  },
}));

vi.mock("./chat", () => ({
  appendMessage: vi.fn(),
}));

vi.mock("./sse", () => ({
  broadcast: vi.fn(),
}));

const dsPost = vi.fn();
vi.mock("./data-service", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./data-service")>();
  return {
    ...actual,
    dsPost: (...a: unknown[]) => dsPost(...a),
  };
});

import { DataServiceError } from "./data-service";
import { startResearch } from "./research";

describe("startResearch 409 分流（CR6-P1-1）", () => {
  beforeEach(() => {
    upsert.mockReset();
    findUnique.mockReset();
    update.mockReset();
    dsPost.mockReset();
    findUnique.mockResolvedValue(null); // 库中无当日记录
  });

  it("todayDone 409 → 返回 rejected，且不写 failed 行", async () => {
    dsPost.mockRejectedValue(
      new DataServiceError("该标的今日已完成深度研究", 409, {
        rejected: "该标的今日已完成深度研究",
        todayDone: true,
      }),
    );

    const res = await startResearch("stock", "600000");

    expect(res.status).toBe("rejected");
    if (res.status === "rejected") {
      expect(res.reason).toBe("该标的今日已完成深度研究");
    }
    expect(upsert).not.toHaveBeenCalled();
  });

  it("并发去重 409 → 返回 running 且登记 watcher（不写 failed）", async () => {
    dsPost.mockRejectedValue(
      new DataServiceError("已有任务在执行", 409, {
        rejected: "该标的已有研究任务在执行",
      }),
    );

    const res = await startResearch("stock", "600000", "浦发银行", "session-1");

    expect(res.status).toBe("running");
    if (res.status === "running") {
      expect(res.reason).toBe("该标的已有研究任务在执行");
    }
    expect(upsert).not.toHaveBeenCalled();
  });

  it("非 409（如 500）→ 仍落库 failed（原语义不变）", async () => {
    dsPost.mockRejectedValue(new DataServiceError("boom", 500, { detail: "boom" }));
    upsert.mockResolvedValue({ error: "boom" });

    const res = await startResearch("stock", "600000");

    expect(res.status).toBe("rejected");
    expect(upsert).toHaveBeenCalledTimes(1);
    const arg = upsert.mock.calls[0][0] as { create: { status: string } };
    expect(arg.create.status).toBe("failed");
  });

  it("无错误（正常提交）→ 走 running 并写 running 行", async () => {
    dsPost.mockResolvedValue({ taskId: "t-1" });
    upsert.mockResolvedValue({
      id: "r1",
      type: "stock",
      code: "600000",
      date: new Date("2026-09-18T00:00:00.000Z"),
      rating: null,
      summary: null,
      status: "running",
      fullReport: null,
      error: null,
      updatedAt: new Date("2026-09-18T00:00:00.000Z"),
    });

    const res = await startResearch("stock", "600000");

    expect(res.status).toBe("running");
    expect(upsert).toHaveBeenCalledTimes(1);
  });
});
