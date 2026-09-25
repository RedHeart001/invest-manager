import { beforeEach, describe, expect, it, vi } from "vitest";

// D1（CR7-11）：ingestDigests 两条此前只靠集成测试覆盖的语义——
// ① (date,title) 200 字截断去重（库内与入库双侧一致）
// ② P2002 唯一约束竞态分支（并发 ingest 的"先读后写"兜底，CR-11）
// prisma 全 mock，不触真实库。

const findMany = vi.fn();
const create = vi.fn();
const productFindMany = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    hotspotDigest: { findMany: (...a: unknown[]) => findMany(...a), create: (...a: unknown[]) => create(...a) },
    product: { findMany: (...a: unknown[]) => productFindMany(...a) },
  },
}));

import { ingestDigests } from "./hotspots";

const dbRow = (over: Record<string, unknown> = {}) => ({
  id: "r1",
  date: new Date("2026-09-25T00:00:00.000Z"),
  title: "t",
  summary: "",
  boardTags: "[]",
  sourceUrls: "[]",
  relatedCodes: "[]",
  newsSource: null,
  engine: null,
  degraded: false,
  note: null,
  createdAt: new Date(),
  updatedAt: new Date(),
  ...over,
});

beforeEach(() => {
  findMany.mockReset();
  create.mockReset();
  productFindMany.mockReset();
  productFindMany.mockResolvedValue([]); // resolveRelated：无成分股/基金
});

describe("ingestDigests（D1：去重与竞态）", () => {
  it("① 库内已有前 200 字相同的长标题 → 截断去重命中，skipped", async () => {
    const longTitle = "长".repeat(250);
    findMany.mockResolvedValue([{ title: longTitle }]); // 库内存的是未截断原串
    create.mockResolvedValue(dbRow());
    const res = await ingestDigests({
      date: "2026-09-25",
      items: [{ title: longTitle.slice(0, 200) }], // 新批次标题被截断到 200
    });
    expect(res.skipped).toBe(1);
    expect(res.inserted).toBe(0);
    expect(create).not.toHaveBeenCalled();
  });

  it("①b 同批内重复标题 → 第二条 skipped", async () => {
    findMany.mockResolvedValue([]);
    create.mockResolvedValue(dbRow());
    const res = await ingestDigests({
      date: "2026-09-25",
      items: [{ title: "同一条新闻" }, { title: "同一条新闻" }],
    });
    expect(res.inserted).toBe(1);
    expect(res.skipped).toBe(1);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("② create 抛 P2002（并发先读后写竞态）→ 按已存在处理，不重复卡片", async () => {
    findMany.mockResolvedValue([]); // 读时库里没有
    create.mockRejectedValueOnce({ code: "P2002" }); // 写时撞唯一约束
    create.mockResolvedValue(dbRow());
    const res = await ingestDigests({
      date: "2026-09-25",
      items: [{ title: "竞态标题" }, { title: "后续正常标题" }],
    });
    expect(res.inserted).toBe(1); // 第二条正常入库
    expect(res.skipped).toBe(1); // P2002 的那条跳过
  });

  it("②b 非 P2002 错误原样上抛（不吞真实故障）", async () => {
    findMany.mockResolvedValue([]);
    create.mockRejectedValueOnce(new Error("db down"));
    await expect(
      ingestDigests({ date: "2026-09-25", items: [{ title: "x" }] }),
    ).rejects.toThrow("db down");
  });

  it("③ 非法 date 前置拒绝", async () => {
    await expect(
      ingestDigests({ date: "20260925", items: [] }),
    ).rejects.toThrow("invalid date");
  });
});
