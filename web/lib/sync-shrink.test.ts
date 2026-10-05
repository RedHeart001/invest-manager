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
// #23 的当日闸门默认放行（本文件测的是缩水保护，不是闸门）：不 mock 它会去打
// `prisma.product.findFirst`，而上面的 prisma 桩里没有这个方法。
vi.mock("./freshness", () => ({ listSyncedToday: vi.fn(async () => null) }));

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

  // CR9-31（2026-09-27）：data-service 现在会声明「这批来自哪个源、是否降级」，
  // 消费侧就必须把这件事说出来——R16 要求降级可感知且可判定，不能只留条数。
  it("上游已声明降级 → 诊断带真实来源与原话，不再只是猜测", async () => {
    count.mockResolvedValue(1059);
    dsGet.mockResolvedValue({
      count: 327,
      products: products(327),
      source: "sina-bond-cov-spot",
      degraded: true,
      note: "东财转债全量列表不可用，已降级至新浪 cov_spot 快照：本次 327 只",
    });
    const r = await syncType("bond");
    expect(r.error).toContain("sina-bond-cov-spot");
    expect(r.error).toContain("已降级至新浪 cov_spot 快照");
    expect(r.error).not.toContain("疑似");
  });

  it("🔁 载荷未声明来源（无降级/旧形态）→ 保留原有「疑似」口径", async () => {
    count.mockResolvedValue(1059);
    dsGet.mockResolvedValue({ count: 327, products: products(327) });
    const r = await syncType("bond");
    expect(r.error).toContain("疑似");
  });

  it("降级但条数过了 70% 闸 → 成功结果里仍要留痕", async () => {
    count.mockResolvedValue(1000);
    dsGet.mockResolvedValue({
      count: 800,
      products: products(800),
      source: "sina-bond-cov-spot",
      degraded: true,
      note: "覆盖面低于东财全量",
    });
    const r = await syncType("bond");
    expect(r.count).toBe(800);
    expect(r.error).toBeUndefined();
    expect(r.note).toContain("list degraded source=sina-bond-cov-spot");
  });

  // #35／CR9-63（主人 10-05 取「甲」）：缩水有两种成因——上游劣化（本闸要挡）与
  // 上游自己声明的有意子集（`us`＝只取前排 N 页＋剔无行业）。过去两者共用 degraded 一个布尔，
  // 于是第二次起的每一次 us 同步都被挡回，美股主数据事实上停止更新。
  it("上游声明『有意子集』→ 缩水闸放行，且这笔账留在 note 里", async () => {
    count.mockResolvedValue(300); // 库里旧的 300 行（改动前的 ds 写入）
    dsGet.mockResolvedValue({
      count: 179,
      products: products(179),
      source: "sina-us-category-list",
      degraded: true,
      note: "美股主数据按甲方案只取前排 15 页",
      intentionalSubset: true,
    });
    const r = await syncType("bond");
    expect(r.error).toBeUndefined();
    expect(r.count).toBe(179);
    expect(r.note).toContain("按上游声明放行有意子集（旧 300 → 新 179）");
    // 放行不等于把覆盖面可见性顶掉：degraded 那句必须还在（R16）
    expect(r.note).toContain("list degraded source=sina-us-category-list");
    const wrote = executeRawUnsafe.mock.calls.some((c) => String(c[0]).includes("INSERT INTO"));
    expect(wrote).toBe(true);
  });

  it("🔁 声明了却回 0 行 → 仍走 C1 空载荷保护（放行通道不覆盖空载荷）", async () => {
    count.mockResolvedValue(300);
    dsGet.mockResolvedValue({ count: 0, products: [], intentionalSubset: true });
    const r = await syncType("bond");
    expect(r.error).toContain("empty payload");
    expect(r.count).toBeUndefined();
    const wrote = executeRawUnsafe.mock.calls.some((c) => String(c[0]).includes("INSERT INTO"));
    expect(wrote).toBe(false);
  });
});
