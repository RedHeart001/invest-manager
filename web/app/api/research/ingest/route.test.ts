import { beforeEach, describe, expect, it, vi } from "vitest";

// 刀 2（#22(a)）：研报回调的**语义白名单**——不查 type 枚举（2026-09-14 的决定仍然有效），
// 查的是"这个标的存在吗"：有既有研报行 **或** 在 Product 里 → 收；两者都无 → 400 且不写库。
// 成对断言（C34）：既断"垃圾回调被挡"，也断"Product 里查不到的在途研报必须照收"——
// 后者防的就是 09-14 那条事故（hk 列表未到货时 Product hk 为 0 行，正是现状 CR9-26②）。

const count = vi.fn();
const findFirst = vi.fn();
const ingestResearch = vi.fn();
const broadcast = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    researchReport: { count: (...a: unknown[]) => count(...a) },
    product: { findFirst: (...a: unknown[]) => findFirst(...a) },
  },
}));

vi.mock("@/lib/research", () => ({
  ingestResearch: (...a: unknown[]) => ingestResearch(...a),
}));

vi.mock("@/lib/sse", () => ({
  broadcast: (...a: unknown[]) => broadcast(...a),
}));

import { POST } from "./route";

function req(body: unknown) {
  return { json: async () => body } as unknown as Parameters<typeof POST>[0];
}

describe("research ingest 语义白名单（刀 2 / #22(a)）", () => {
  beforeEach(() => {
    count.mockReset().mockResolvedValue(0);
    findFirst.mockReset().mockResolvedValue(null);
    ingestResearch.mockReset().mockResolvedValue({ id: "r1", status: "done", rating: "买入" });
    broadcast.mockReset();
  });

  it("未知标的且无在途行 → 400，且不写库、不广播", async () => {
    const res = await POST(req({ type: "bogus", code: "600519", status: "done" }));
    expect(res.status).toBe(400);
    expect(ingestResearch).not.toHaveBeenCalled();
    expect(broadcast).not.toHaveBeenCalled();
  });

  it("核验按 (type, code) 成对查，不是只查 code", async () => {
    await POST(req({ type: "bogus", code: "600519", status: "done" }));
    expect(count).toHaveBeenCalledWith({ where: { type: "bogus", code: "600519" } });
    expect(findFirst).toHaveBeenCalledWith({
      where: { type: "bogus", code: "600519" },
      select: { code: true },
    });
  });

  it("Product 里有的标的 → 200 且落库", async () => {
    findFirst.mockResolvedValue({ code: "600519" });
    const res = await POST(req({ type: "stock", code: "600519", status: "done" }));
    expect(res.status).toBe(200);
    expect(ingestResearch).toHaveBeenCalledTimes(1);
  });

  it("🔁 反向：Product 里查不到（如 hk 列表未到货），但存在我们自己发起的行 → 必须照收", async () => {
    count.mockResolvedValue(1); // 在途 running 行
    findFirst.mockResolvedValue(null); // Product 里没有这个标的
    const res = await POST(req({ type: "hk", code: "00700", status: "done" }));
    expect(res.status).toBe(200);
    expect(ingestResearch).toHaveBeenCalledTimes(1); // 拒掉它就会让研报永久 running
  });

  it("🔁 反向：查库本身报错时按放行处理（不能把在途研报挡在门外）", async () => {
    count.mockRejectedValue(new Error("SQLITE_BUSY"));
    const res = await POST(req({ type: "stock", code: "600519", status: "done" }));
    expect(res.status).toBe(200);
    expect(ingestResearch).toHaveBeenCalledTimes(1);
  });

  it("既有契约不动：缺 code → 400，缺 type → 400，非法 JSON → 400", async () => {
    expect((await POST(req({ type: "stock" }))).status).toBe(400);
    expect((await POST(req({ code: "600519" }))).status).toBe(400);
    const bad = {
      json: async () => {
        throw new SyntaxError("bad json");
      },
    } as unknown as Parameters<typeof POST>[0];
    expect((await POST(bad)).status).toBe(400);
  });
});
