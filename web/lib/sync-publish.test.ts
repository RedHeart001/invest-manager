import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * CR10-49 离线单测：`publishProducts` 的发布事务与 `snapshotId` 幂等账本。
 *
 * 这里不用 Prisma 桩去“演”SQL，而是用 Node 自带的 SQLite 真执行 `sync.ts` 发出的
 * 建表/查询/事务语句——要钉的恰恰是“账本与 Product 替换同事务”这件事，桩掉 SQL
 * 就只剩一句自说自话。测试库是 `:memory:`，零仓库写入。
 */

const h = vi.hoisted(() => ({
  db: null as any,
  dsGet: vi.fn(),
  txQueries: 0,
}));

vi.mock("@/lib/data-service", () => ({
  dsGet: (...args: unknown[]) => h.dsGet(...args),
  productsBudgetMs: () => 1000,
}));

vi.mock("./freshness", () => ({
  listSyncedToday: async () => null,
}));

vi.mock("@/lib/prisma", () => {
  const normalize = (params: unknown[]) =>
    params.map((value) => {
      if (value === undefined) return null;
      if (value instanceof Date) return value.toISOString();
      if (typeof value === "boolean") return value ? 1 : 0;
      return value;
    });
  const exec = (sql: string, params: unknown[]) => {
    if (/^\s*(CREATE|DROP|ALTER)\b/i.test(sql)) {
      h.db.exec(sql);
      return;
    }
    h.db.prepare(sql).run(...normalize(params));
  };
  const query = (sql: string, params: unknown[]) => h.db.prepare(sql).all(...normalize(params));
  const tx = {
    $executeRawUnsafe: async (sql: string, ...params: unknown[]) => exec(sql, params),
    $queryRawUnsafe: async (sql: string, ...params: unknown[]) => {
      h.txQueries += 1;
      return query(sql, params);
    },
  };
  return {
    prisma: {
      product: {
        count: async ({ where }: { where: { type: string } }) => {
          const row = h.db
            .prepare(`SELECT COUNT(*) AS n FROM "Product" WHERE "type" = ?`)
            .get(where.type);
          return Number(row.n);
        },
      },
      $executeRawUnsafe: async (sql: string, ...params: unknown[]) => exec(sql, params),
      $queryRawUnsafe: async (sql: string, ...params: unknown[]) => query(sql, params),
      $transaction: async (fn: (client: typeof tx) => Promise<unknown>) => {
        h.db.exec("BEGIN");
        try {
          const out = await fn(tx);
          h.db.exec("COMMIT");
          return out;
        } catch (e) {
          try {
            h.db.exec("ROLLBACK");
          } catch {
            // 回滚失败不遮蔽原始异常
          }
          throw e;
        }
      },
    },
  };
});

import { prisma } from "@/lib/prisma";

import { publishProducts, syncType, type ProductListPayload, type ProductPayload } from "./sync";

const require = createRequire(import.meta.url);
type Statement = {
  all(...params: unknown[]): any[];
  get(...params: unknown[]): any;
  run(...params: unknown[]): any;
};
type Database = {
  exec(sql: string): void;
  prepare(sql: string): Statement;
  close(): void;
};
const { DatabaseSync } = require("node:sqlite") as {
  DatabaseSync: new (file: string) => Database;
};

let dir = "";
let prevMirror: string | undefined;

function product(code: string, over: Partial<ProductPayload> = {}): ProductPayload {
  return {
    type: "us",
    code,
    name: code,
    pinyin: null,
    pinyinInitials: null,
    exchange: "NASDAQ",
    tags: ["半导体"],
    ...over,
  };
}

function payload(
  snapshotId: string,
  codes: string[],
  over: Partial<ProductListPayload> = {},
): ProductListPayload {
  return {
    count: codes.length,
    products: codes.map((code) => product(code)),
    acquisitionComplete: true,
    snapshotId,
    ...over,
  };
}

function rows() {
  return h.db.prepare(`SELECT id, code FROM "Product" WHERE type = 'us' ORDER BY code`).all();
}

function ledger() {
  try {
    return h.db
      .prepare(`SELECT "snapshotId", "type", "count" FROM "Product_snapshot_publication" ORDER BY "snapshotId"`)
      .all();
  } catch (e) {
    // 发布前就被拒绝时账本表可能尚未创建；空账本正是“零写入”的证据。
    if (/no such table/i.test(e instanceof Error ? e.message : String(e))) return [];
    throw e;
  }
}

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sync-publish-"));
  prevMirror = process.env.US_SNAPSHOT_PUBLICATIONS_FILE;
  process.env.US_SNAPSHOT_PUBLICATIONS_FILE = path.join(dir, "us-publications.json");
  h.db = new DatabaseSync(":memory:");
  h.db.exec(`
    CREATE TABLE "Product" (
      "id" TEXT NOT NULL PRIMARY KEY,
      "type" TEXT NOT NULL,
      "code" TEXT NOT NULL,
      "name" TEXT NOT NULL,
      "pinyin" TEXT,
      "pinyinInitials" TEXT,
      "exchange" TEXT,
      "tags" TEXT,
      "sector" TEXT,
      "searchText" TEXT,
      "lastPrice" REAL,
      "lastChangePct" REAL,
      "updatedAt" DATETIME NOT NULL,
      UNIQUE("type", "code")
    );
    CREATE TABLE "Product_fts" ("productId" TEXT, "searchText" TEXT);
  `);
  h.dsGet.mockReset();
  h.txQueries = 0;
});

afterEach(() => {
  try {
    h.db?.close();
  } catch {
    // 已关闭
  }
  h.db = null;
  if (prevMirror === undefined) delete process.env.US_SNAPSHOT_PUBLICATIONS_FILE;
  else process.env.US_SNAPSHOT_PUBLICATIONS_FILE = prevMirror;
  fs.rmSync(dir, { recursive: true, force: true });
  vi.restoreAllMocks();
});

describe("CR10-49：snapshotId 幂等发布", () => {
  it("首次发布写 Product + 同事务账本；同一 snapshotId 重试只回执、不重写 Product", async () => {
    const first = await publishProducts("us", payload("snap-1", ["AAA", "BBB"]), {
      snapshotId: "snap-1",
    });
    expect(first).toMatchObject({ ok: true, type: "us", count: 2, snapshotId: "snap-1" });
    expect(first.ok && first.alreadyPublished).toBeFalsy();
    expect(rows().map((r: any) => r.code)).toEqual(["AAA", "BBB"]);
    expect(ledger()).toEqual([{ snapshotId: "snap-1", type: "us", count: 2 }]);

    const before = rows();
    const second = await publishProducts("us", payload("snap-1", ["CCC"]), {
      snapshotId: "snap-1",
    });
    expect(second).toMatchObject({ ok: true, type: "us", count: 2, snapshotId: "snap-1" });
    expect(second.ok && second.alreadyPublished).toBe(true);
    expect(rows()).toEqual(before); // 不删不插，CCC 不会被写进来
    expect(ledger()).toHaveLength(1);
  });

  it("🔁 快路径未命中、事务内二次检查命中：响应丢失后的重试仍不重复写库", async () => {
    await publishProducts("us", payload("snap-1", ["AAA", "BBB"]), { snapshotId: "snap-1" });
    const before = rows();

    const original = (prisma as any).$queryRawUnsafe.bind(prisma);
    let calls = 0;
    const spy = vi.spyOn(prisma as any, "$queryRawUnsafe").mockImplementation((async (
      sql: string,
      ...params: unknown[]
    ) => {
      calls += 1;
      // 第一次是发布前的快路径：装作还没看到账本；第二次是事务内，必须看到。
      if (calls === 1) return [];
      return original(sql, ...params);
    }) as never);
    try {
      const retry = await publishProducts("us", payload("snap-1", ["CCC", "DDD"]), {
        snapshotId: "snap-1",
      });
      expect(retry.ok).toBe(true);
      expect(retry.ok && retry.alreadyPublished).toBe(true);
      expect(retry.ok && retry.count).toBe(2);
      expect(calls).toBe(1); // 快路径只查一次且被装作未命中
      expect(h.txQueries).toBe(2); // 首次发布事务 1 次 + 重试事务内二次检查 1 次
      expect(rows()).toEqual(before);
      expect(ledger()).toHaveLength(1);
    } finally {
      spy.mockRestore();
    }
  });

  it("不同 snapshotId 是新代次：整表替换 Product 并追加账本", async () => {
    const first = await publishProducts("us", payload("snap-1", ["AAA", "BBB"]), {
      snapshotId: "snap-1",
    });
    const second = await publishProducts("us", payload("snap-2", ["CCC", "DDD", "EEE"]), {
      snapshotId: "snap-2",
    });
    expect(first.ok && first.alreadyPublished).toBeFalsy();
    expect(second.ok && second.alreadyPublished).toBeFalsy();
    expect(second.ok && second.count).toBe(3);
    expect(rows().map((r: any) => r.code)).toEqual(["CCC", "DDD", "EEE"]);
    expect(ledger()).toEqual([
      { snapshotId: "snap-1", type: "us", count: 2 },
      { snapshotId: "snap-2", type: "us", count: 3 },
    ]);
  });

  it("snapshotId 也可由载荷自带（普通 /api/sync?type=us 路径）", async () => {
    const result = await publishProducts("us", payload("snap-data", ["AAA"]));
    expect(result).toMatchObject({ ok: true, count: 1, snapshotId: "snap-data" });
    expect(ledger()).toEqual([{ snapshotId: "snap-data", type: "us", count: 1 }]);
  });

  it("可观测副本只做镜像：发布成功后 JSON 有记录，写失败也不影响发布", async () => {
    await publishProducts("us", payload("snap-1", ["AAA", "BBB"]), { snapshotId: "snap-1" });
    const mirrorFile = process.env.US_SNAPSHOT_PUBLICATIONS_FILE as string;
    const mirror = JSON.parse(fs.readFileSync(mirrorFile, "utf8"));
    expect(mirror.snapshots["snap-1"]).toMatchObject({ type: "us", count: 2 });

    const blocker = path.join(dir, "blocker");
    fs.writeFileSync(blocker, "x");
    process.env.US_SNAPSHOT_PUBLICATIONS_FILE = path.join(blocker, "nested", "x.json");
    const result = await publishProducts("us", payload("snap-2", ["CCC", "DDD"]), {
      snapshotId: "snap-2",
    });
    expect(result.ok).toBe(true);
    expect(rows().map((r: any) => r.code)).toEqual(["CCC", "DDD"]);
  });
});

describe("CR10-49：发布前的既有保护一条不放宽", () => {
  it("acquisitionComplete=false ⇒ 可预期拒绝，零写库、零账本", async () => {
    const result = await publishProducts(
      "us",
      { ...payload("snap-bad", ["AAA"]), acquisitionComplete: false, note: "缺页" },
      { snapshotId: "snap-bad" },
    );
    expect(result.ok).toBe(false);
    expect(result.ok === false && result.rejected).toBe(true);
    expect(result.ok === false && result.error).toContain("incomplete acquisition");
    expect(rows()).toEqual([]);
    expect(ledger()).toEqual([]);
  });

  it("intentionalSubset 不能在没有 productPolicySubset 时越过缩水闸", async () => {
    const result = await publishProducts(
      "us",
      { ...payload("snap-bad", ["AAA"]), intentionalSubset: true, productPolicySubset: false },
      { snapshotId: "snap-bad" },
    );
    expect(result.ok).toBe(false);
    expect(result.ok === false && result.rejected).toBe(true);
    expect(result.ok === false && result.error).toContain("non-product subset");
    expect(rows()).toEqual([]);
  });

  it("空载荷 ⇒ 保留旧数据，连账本也不写", async () => {
    await publishProducts("us", payload("snap-1", ["AAA", "BBB"]), { snapshotId: "snap-1" });
    const result = await publishProducts("us", payload("snap-empty", []), {
      snapshotId: "snap-empty",
    });
    expect(result.ok).toBe(false);
    expect(result.ok === false && result.error).toContain("empty payload");
    expect(rows().map((r: any) => r.code)).toEqual(["AAA", "BBB"]);
    expect(ledger()).toHaveLength(1);
  });

  it("缩水未声明 ⇒ 拒绝；声明为产品口径子集 ⇒ 放行并留痕", async () => {
    await publishProducts("us", payload("snap-10", Array.from({ length: 10 }, (_, i) => `S${i}`)), {
      snapshotId: "snap-10",
    });
    const rejected = await publishProducts("us", payload("snap-5", ["A", "B", "C", "D", "E"]), {
      snapshotId: "snap-5",
    });
    expect(rejected.ok).toBe(false);
    expect(rejected.ok === false && rejected.rejected).toBe(true);
    expect(rejected.ok === false && rejected.error).toContain("payload shrunk");
    expect(rows()).toHaveLength(10);
    expect(ledger()).toHaveLength(1);

    const allowed = await publishProducts(
      "us",
      {
        ...payload("snap-5b", ["A", "B", "C", "D", "E"]),
        intentionalSubset: true,
        productPolicySubset: true,
        degraded: true,
        source: "sina-us-category-list",
        note: "完整采集后按行业口径剔除",
      },
      { snapshotId: "snap-5b" },
    );
    expect(allowed.ok).toBe(true);
    expect(allowed.ok && allowed.note).toContain("按上游声明放行有意子集");
    expect(rows()).toHaveLength(5);
    expect(ledger().map((r: any) => r.snapshotId)).toEqual(["snap-10", "snap-5b"]);
  });

  it("重复 (type,code) 仍按首次出现去重，并点名 dupCodes", async () => {
    const data = payload("snap-dup", ["DUP", "DUP", "AAA"]);
    const result = await publishProducts("us", data, { snapshotId: "snap-dup" });
    expect(result.ok).toBe(true);
    expect(result.ok && result.count).toBe(2);
    expect(result.ok && result.dupCodes).toEqual(["us:DUP"]);
    expect(rows().map((r: any) => r.code)).toEqual(["AAA", "DUP"]);
  });
});

describe("CR10-49：collecting 与普通同步共用发布路径", () => {
  it("us 还在采集 ⇒ syncType 返回 collecting，不是失败", async () => {
    h.dsGet.mockResolvedValueOnce({
      collecting: true,
      state: "collecting",
      snapshotId: "snap-c",
      progress: { resolvedPages: 441, requiredPages: 923 },
      note: "正在采集",
    });
    const result = await syncType("us");
    expect(result.error).toBeUndefined();
    expect(result.collecting).toBe(true);
    expect(result.jobState).toBe("collecting");
    expect(result.snapshotId).toBe("snap-c");
    expect(result.progress).toEqual({ resolvedPages: 441, requiredPages: 923 });
  });

  it("us 候选就绪 ⇒ 走同一个 publishProducts，不另立一套保护", async () => {
    h.dsGet.mockResolvedValueOnce(payload("snap-sync", ["AAA", "BBB"]));
    const result = await syncType("us");
    expect(result.error).toBeUndefined();
    expect(result.count).toBe(2);
    expect(result.snapshotId).toBe("snap-sync");
    expect(rows().map((r: any) => r.code)).toEqual(["AAA", "BBB"]);
    expect(ledger()).toEqual([{ snapshotId: "snap-sync", type: "us", count: 2 }]);
  });

  it("同一 snapshotId 经 syncType 重放 ⇒ alreadyPublished，不重复写库", async () => {
    h.dsGet.mockResolvedValue(payload("snap-sync", ["AAA"]));
    await syncType("us");
    const before = rows();
    const replay = await syncType("us");
    expect(replay.error).toBeUndefined();
    expect(replay.alreadyPublished).toBe(true);
    expect(rows()).toEqual(before);
    expect(ledger()).toHaveLength(1);
  });
});
