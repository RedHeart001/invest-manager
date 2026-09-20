import { beforeEach, describe, expect, it, vi } from "vitest";

// G4（批次 D）：FTS/LIKE 无结果时的 LLM 兜底召回。
// 验证：无结果 → 调 LLM 抽关键词重查；LLM 未配置/失败 → 静默返回空不阻塞。

const scoreProduct = vi.fn();
vi.mock("./score", () => ({
  scoreProduct: (...a: unknown[]) => scoreProduct(...a),
  parseTags: () => [],
}));
vi.mock("./quote-enrich", () => ({ fetchQuotesByType: async () => new Map() }));
vi.mock("./prisma", () => ({
  prisma: {
    $queryRawUnsafe: vi.fn(async () => []),
    product: { findMany: vi.fn(async () => []) },
    watchlist: { findMany: vi.fn(async () => []) },
    searchClickLog: { groupBy: vi.fn(async () => []) },
  },
}));

const chatJson = vi.fn();
vi.mock("./llm", () => ({ chatJson: (...a: unknown[]) => chatJson(...a) }));

import { searchProducts } from "./search";

describe("searchProducts LLM 兜底（G4）", () => {
  beforeEach(() => {
    scoreProduct.mockReset();
    chatJson.mockReset();
  });

  it("首查无结果 → 调 LLM 抽关键词并重查", async () => {
    // 第一次所有候选打分为 0（无结果）；兜底关键词命中
    let call = 0;
    scoreProduct.mockImplementation((q: string) => {
      call += 1;
      // 仅兜底关键词 "茅台" 命中
      return q === "茅台" ? 90 : 0;
    });
    chatJson.mockResolvedValue({ keywords: ["茅台"] });

    // 让候选召回返回一个产品（否则 scoreQuery 无输入）
    const { prisma } = await import("./prisma");
    (prisma.product.findMany as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: "1", type: "stock", code: "600519", name: "贵州茅台", pinyin: "guizhoumaotai", pinyinInitials: "gzmt", exchange: "SH", tags: "[]" },
    ]);

    const res = await searchProducts({ q: "白酒龙头那家" });
    expect(chatJson).toHaveBeenCalledTimes(1);
    expect(res.some((r) => r.code === "600519")).toBe(true);
    void call;
  });

  it("LLM 未配置（chatJson 返回 null）→ 返回空，不抛错", async () => {
    scoreProduct.mockReturnValue(0);
    chatJson.mockResolvedValue(null);
    const res = await searchProducts({ q: "无法识别的查询" });
    expect(res).toEqual([]);
  });

  it("LLM 抽取关键词为空 → 不重查仍返回空", async () => {
    scoreProduct.mockReturnValue(0);
    chatJson.mockResolvedValue({ keywords: [] });
    const res = await searchProducts({ q: "xxx" });
    expect(res).toEqual([]);
  });

  it("首查有结果 → 不触发兜底（不调 LLM）", async () => {
    scoreProduct.mockReturnValue(80);
    const { prisma } = await import("./prisma");
    (prisma.product.findMany as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: "1", type: "stock", code: "600519", name: "贵州茅台", pinyin: "gzmt", pinyinInitials: "gzmt", exchange: "SH", tags: "[]" },
    ]);
    const res = await searchProducts({ q: "贵州茅台" });
    expect(res.length).toBeGreaterThan(0);
    expect(chatJson).not.toHaveBeenCalled();
  });
});
