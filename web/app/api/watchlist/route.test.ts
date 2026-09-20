import { beforeEach, describe, expect, it, vi } from "vitest";

// G5（批次 D）：Watchlist 自选 API（此前只读不通写）。
// 验证：POST 白名单校验 + upsert；DELETE 校验 + 删除；GET 列表。

const upsert = vi.fn();
const deleteMany = vi.fn();
const findMany = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    watchlist: {
      upsert: (...a: unknown[]) => upsert(...a),
      deleteMany: (...a: unknown[]) => deleteMany(...a),
      findMany: (...a: unknown[]) => findMany(...a),
    },
  },
}));

import { DELETE, GET, POST } from "./route";

function postReq(body: unknown) {
  return { json: async () => body } as unknown as Parameters<typeof POST>[0];
}
function delReq(url: string) {
  return { nextUrl: { searchParams: new URLSearchParams(url.split("?")[1] ?? "") } } as unknown as Parameters<typeof DELETE>[0];
}

describe("watchlist API（G5）", () => {
  beforeEach(() => {
    upsert.mockReset().mockResolvedValue({});
    deleteMany.mockReset().mockResolvedValue({ count: 1 });
    findMany.mockReset().mockResolvedValue([]);
  });

  it("POST 合法 → upsert 并返回 ok", async () => {
    const res = await POST(postReq({ type: "stock", code: "600519", name: "贵州茅台" }));
    expect(res.status).toBe(200);
    expect(upsert).toHaveBeenCalledTimes(1);
    const arg = upsert.mock.calls[0][0] as { where: { type_code: { type: string; code: string } } };
    expect(arg.where.type_code).toEqual({ type: "stock", code: "600519" });
  });

  it("POST 非法 type → 400", async () => {
    const res = await POST(postReq({ type: "option", code: "600519" }));
    expect(res.status).toBe(400);
    expect(upsert).not.toHaveBeenCalled();
  });

  it("POST 非法 code 字符集 → 400", async () => {
    const res = await POST(postReq({ type: "stock", code: "../../etc/passwd" }));
    expect(res.status).toBe(400);
  });

  it("DELETE 合法 → 删除", async () => {
    const res = await DELETE(delReq("?type=stock&code=600519"));
    expect(res.status).toBe(200);
    expect(deleteMany).toHaveBeenCalledWith({ where: { type: "stock", code: "600519" } });
  });

  it("DELETE 非法 type → 400", async () => {
    const res = await DELETE(delReq("?type=bad&code=600519"));
    expect(res.status).toBe(400);
    expect(deleteMany).not.toHaveBeenCalled();
  });

  it("GET → 返回 items", async () => {
    findMany.mockResolvedValue([{ type: "stock", code: "600519", name: "贵州茅台" }]);
    const res = await GET();
    const body = (await res.json()) as { items: unknown[] };
    expect(res.status).toBe(200);
    expect(body.items).toHaveLength(1);
  });
});
