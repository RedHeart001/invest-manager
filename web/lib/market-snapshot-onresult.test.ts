/**
 * CR9-68（#40 甲）离线单测：`refreshAll` 的**逐类回调接线**——从调用点读，不从纯函数读。
 *
 * 为什么单独一个文件（#38/#40 那一课的第三次落地）：`market-snapshot.ts:326` 那句
 * `onResult?.(r)` 是 CR9-60「边跑边落盘」与 CR9-61「完成账本」**唯一的写入动作**，
 * 而落地时 ① 里**没有任何一条断言驱动过它**——`refresh-progress.test.ts` 那 14 条全部
 * 直接调用三个导出，唯一驱动 `refreshAll` 的 `market-snapshot-gate.test.ts:107` 不传第二个参数，
 * pacing 套件整份走的是单类型 `refreshSnapshot`。⇒ 把那一行整行摘掉，① 一条不红，
 * 而后果是闸门静默退回"只看 `snapshotAt`"、CR9-64 的盖章从未发生。
 *
 * 运行方式（零出网、不落任何真文件——`refresh-progress` 整个被 mock 掉）：
 *     npx vitest run lib/market-snapshot-onresult.test.ts
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const findMany = vi.fn();
const executeRawUnsafe = vi.fn();
const fetchQuotes = vi.fn();
const snapshotRefreshedToday = vi.fn();
const hasCompletionLedger = vi.fn();
const completedToday = vi.fn();
const lastCompletedAt = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    product: {
      findMany: (...a: unknown[]) => findMany(...a),
      findFirst: vi.fn(async () => null),
    },
    $executeRawUnsafe: (...a: unknown[]) => executeRawUnsafe(...a),
  },
}));
vi.mock("./data-service", () => ({ fetchQuotes: (...a: unknown[]) => fetchQuotes(...a) }));
vi.mock("./freshness", () => ({
  snapshotRefreshedToday: (...a: unknown[]) => snapshotRefreshedToday(...a),
}));
// 本文件钉的是"回调有没有被调用"，落盘那一半由 refresh-progress 自己的 14 条钉
vi.mock("./refresh-progress", () => ({
  hasCompletionLedger: () => hasCompletionLedger(),
  completedToday: (...a: unknown[]) => completedToday(...a),
  lastCompletedAt: (...a: unknown[]) => lastCompletedAt(...a),
}));

import { refreshAll } from "./market-snapshot";
import type { SnapshotResult } from "./market-snapshot";

/** 每类一行标的、一条报价 ⇒ 一类恰好一个批次，跑完就回调 */
function oneRow() {
  return [{ code: "600519" }];
}

describe("refreshAll 的逐类回调接线（CR9-68／#40 甲）", () => {
  beforeEach(() => {
    findMany.mockReset().mockResolvedValue(oneRow());
    executeRawUnsafe.mockReset().mockResolvedValue(1);
    fetchQuotes.mockReset().mockResolvedValue({
      quotes: { "600519": { price: 1258.62, changePct: 0.5 } },
      usesEastmoney: true,
    });
    snapshotRefreshedToday.mockReset().mockResolvedValue(null);
    hasCompletionLedger.mockReset().mockReturnValue(true);
    completedToday.mockReset().mockReturnValue(false);
    lastCompletedAt.mockReset().mockReturnValue(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("🔁 每完成一类回调一次：次数与顺序都等于 `types`（摘掉那行就红在这里）", async () => {
    const seen: string[] = [];
    await refreshAll(["stock", "bond", "crypto"], {
      onResult: (r) => seen.push(r.type),
    });
    expect(seen).toEqual(["stock", "bond", "crypto"]);
  });

  it("回调拿到的就是**那一类**的结果对象，不是最后一份（顺序错位比不调用更难发现）", async () => {
    const objs: SnapshotResult[] = [];
    const results = await refreshAll(["stock", "bond"], { onResult: (r) => objs.push(r) });
    expect(objs).toHaveLength(2);
    expect(objs[0]).toBe(results[0]);
    expect(objs[1]).toBe(results[1]);
    expect(objs.map((r) => r.type)).toEqual(["stock", "bond"]);
  });

  it("🔁 被 #23 挡下的那一类同样要回调（`skipped` 那份也得进 `done`，否则进度里「这一类没数」）", async () => {
    snapshotRefreshedToday.mockResolvedValue(new Date("2026-10-06T03:00:00Z"));
    // 账本里只有 stock ⇒ stock 被挡、bond 走「放行续跑」那一支（CR9-61 的两半判据）
    completedToday.mockImplementation((t: unknown) => t === "stock");
    lastCompletedAt.mockReturnValue("2026-10-06T03:00:00.000Z");
    const seen: SnapshotResult[] = [];
    await refreshAll(["stock", "bond"], { onResult: (r) => seen.push(r) });
    expect(seen).toHaveLength(2);
    expect(seen[0].skipped).toBe(true);
    expect(seen[1].skipped).toBeUndefined();
    expect(seen[1].resumed).toBe(true);
    expect(fetchQuotes).toHaveBeenCalledTimes(1); // 被挡那类一次网都没出，但回调照旧发生
  });

  it("🔁 `force` 是原样透传给每一类的（解构时把它留在 `inner` 里＝第二类起就重新过闸）", async () => {
    snapshotRefreshedToday.mockResolvedValue(new Date("2026-10-06T03:00:00Z"));
    completedToday.mockReturnValue(true);
    await refreshAll(["stock", "bond"], { force: true, onResult: () => {} });
    expect(snapshotRefreshedToday).not.toHaveBeenCalled();
    expect(fetchQuotes).toHaveBeenCalledTimes(2);
  });

  it("不传第二个参数仍要跑完（旧调用点与单类型分支不许因为加了回调而变成必填）", async () => {
    const results = await refreshAll(["stock"]);
    expect(results).toHaveLength(1);
    expect(results[0].updated).toBe(1);
  });

  it("中途一类炸掉 ⇒ 前面已完成的类**回调已经发生过**（这就是「边跑边落盘」存在的全部理由）", async () => {
    findMany
      .mockResolvedValueOnce(oneRow())
      .mockRejectedValueOnce(new Error("prisma down"));
    const seen: string[] = [];
    await expect(
      refreshAll(["stock", "bond"], { onResult: (r) => seen.push(r.type) }),
    ).rejects.toThrow("prisma down");
    expect(seen).toEqual(["stock"]); // 没有那行 ⇒ 这里会是 []，而整轮证据一起没了
  });
});
