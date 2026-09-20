import { beforeEach, describe, expect, it, vi } from "vitest";

// G2 缩水保护回归（2026-09-20 集成验收发现）：全量替换语义是"新载荷 = 完整集合"，
// 但主源限流降级到覆盖度更低的备源时（转债：东财 1052 → 新浪 cov_spot 329），
// 直接替换会把主数据**缩小**（静默劣化）。此处验证：新载荷明显缩水时保留旧数据。

const count = vi.fn();
const executeRawUnsafe = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    product: { count: (...a: unknown[]) => count(...a) },
    $executeRawUnsafe: (...a: unknown[]) => executeRawUnsafe(...a),
    $transaction: vi.fn(),
  },
}));

const dsGet = vi.fn();
vi.mock("@/lib/data-service", () => ({ dsGet: (...a: unknown[]) => dsGet(...a) }));
vi.mock("./market-snapshot", () => ({ refreshSnapshot: vi.fn() }));

import { syncType } from "./sync";

function products(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    type: "bond",
    code: String(100000 + i),
    name: `债${i}`,
  }));
}

describe("sync 降级缩水保护（G2 回归）", () => {
  beforeEach(() => {
    count.mockReset();
    executeRawUnsafe.mockReset().mockResolvedValue(0);
    dsGet.mockReset();
  });

  it("新载荷显著缩水（< 70%）→ 保留旧数据并报错", async () => {
    count.mockResolvedValue(1052); // 库内现有
    dsGet.mockResolvedValue({ count: 329, products: products(329) }); // 备源降级
    const r = await syncType("bond");
    expect(r.error).toContain("shrunk");
    expect(r.count).toBeUndefined();
    // 未执行任何替换写入
    const wrote = executeRawUnsafe.mock.calls.some((c) => String(c[0]).includes("INSERT INTO"));
    expect(wrote).toBe(false);
  });

  it("新载荷正常（≥ 70% 现有）→ 正常全量替换", async () => {
    count.mockResolvedValue(1052);
    dsGet.mockResolvedValue({ count: 1053, products: products(1053) });
    const r = await syncType("bond");
    expect(r.count).toBe(1053);
    expect(r.error).toBeUndefined();
  });

  it("库内为空（首次同步）→ 不触发缩水保护", async () => {
    count.mockResolvedValue(0);
    dsGet.mockResolvedValue({ count: 329, products: products(329) });
    const r = await syncType("bond");
    expect(r.count).toBe(329);
    expect(r.error).toBeUndefined();
  });

  it("空载荷 → 仍走 C1 空载荷保护", async () => {
    count.mockResolvedValue(1052);
    dsGet.mockResolvedValue({ count: 0, products: [] });
    const r = await syncType("bond");
    expect(r.error).toContain("empty payload");
  });
});
