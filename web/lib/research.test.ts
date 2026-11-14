import { beforeEach, describe, expect, it, vi } from "vitest";

// CR6-P1-1 回归测试：/research/start 用 409 表达"被拒"，而 dsPost 对任何
// 非 2xx 都抛 DataServiceError。修复前该异常直接落入"提交失败"分支，
// 把当日限次/并发去重误写成 failed，且 rejected 分支与 watcher 登记成为死代码。

const upsert = vi.fn();
const findUnique = vi.fn();
const update = vi.fn();
const reportRow = () => ({
  id: "r-cleanup", type: "stock", code: "600000",
  date: new Date("2026-09-18T00:00:00.000Z"), rating: "中性", summary: "完成",
  status: "done", fullReport: null, error: null,
  updatedAt: new Date("2026-09-18T00:00:00.000Z"),
});

vi.mock("./prisma", () => ({
  prisma: {
    researchReport: {
      findUnique: (...a: unknown[]) => findUnique(...a),
      upsert: (...a: unknown[]) => upsert(...a),
      update: (...a: unknown[]) => update(...a),
    },
  },
}));

const appendMessage = vi.fn();
vi.mock("./chat", () => ({
  appendMessage: (...a: unknown[]) => appendMessage(...a),
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
import { ingestResearch, startResearch } from "./research";

describe("startResearch 409 分流（CR6-P1-1）", () => {
  beforeEach(async () => {
    // watcher 挂 globalThis（生产用于跨 HMR 保留）；先 await 消费残留，再重置全部 mock。
    upsert.mockResolvedValue(reportRow());
    await ingestResearch({ type: "stock", code: "600000", report: { ok: true } });
    upsert.mockReset();
    findUnique.mockReset();
    update.mockReset();
    dsPost.mockReset();
    appendMessage.mockReset();
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

  it.each([
    ["HTTP 409", new DataServiceError("容量已满", 409, { rejected: "容量已满", reason: "capacity" })],
    ["HTTP 200", { rejected: "容量已满", reason: "capacity" }],
  ])("CR10-25：全局容量满（%s）→ rejected，不登记 watcher", async (_label, response) => {
    if (response instanceof Error) dsPost.mockRejectedValue(response);
    else dsPost.mockResolvedValue(response);

    const res = await startResearch("stock", "600000", "浦发银行", "session-capacity");

    expect(res).toEqual({ status: "rejected", reason: "容量已满" });
    expect(upsert).not.toHaveBeenCalled();
    upsert.mockResolvedValue({
      id: "r-capacity", type: "stock", code: "600000",
      date: new Date("2026-09-18T00:00:00.000Z"), rating: "中性", summary: "完成",
      status: "done", fullReport: null, error: null,
      updatedAt: new Date("2026-09-18T00:00:00.000Z"),
    });
    await ingestResearch({ type: "stock", code: "600000", report: { ok: true } });
    expect(appendMessage).not.toHaveBeenCalled();
  });

  it("CR10-25🔁：同标的 running 的结构化原因仍登记 watcher", async () => {
    dsPost.mockRejectedValue(new DataServiceError("已有任务在执行", 409, {
      rejected: "该标的已有研究任务在执行", reason: "running",
    }));
    const res = await startResearch("stock", "600000", "浦发银行", "session-running");
    expect(res.status).toBe("running");
    upsert.mockResolvedValue({
      id: "r-running", type: "stock", code: "600000",
      date: new Date("2026-09-18T00:00:00.000Z"), rating: "中性", summary: "完成",
      status: "done", fullReport: null, error: null,
      updatedAt: new Date("2026-09-18T00:00:00.000Z"),
    });
    await ingestResearch({ type: "stock", code: "600000", report: { ok: true } });
    expect(appendMessage).toHaveBeenCalledWith("session-running", "assistant", expect.any(String));
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
