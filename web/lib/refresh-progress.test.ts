/**
 * CR9-60（#33 甲）离线单测：刷新腿的**逐类进度状态位**（`lib/refresh-progress.ts`）。
 *
 * 背景（10-04 02:11 实测）：链式刷新腿被 `ConnectionResetError(10054)` 打断时，逐类结果
 * 住在响应体里 ⇒ 永远拿不到，`lastRefresh` 只剩一句 `outcome=failed`，只能靠库里的
 * `MAX(snapshotAt)` 反推中断点。主人的字＝"甲＋丙①"，本模块就是"甲"。
 *
 * 这套断言要钉住的四件事：
 * 1. **边跑边落盘**：起跑写一次、每完成一类写一次 ⇒ 任何时刻被掐断都留下"跑到第几类"；
 * 2. **续得上**：`done` 从盘上读回来接着写，不是模块内存——C17 记过 Next 的 HMR 会重建
 *    模块作用域，而进程重启正是本条要归因的那一档；
 * 3. **收尾态要说得出口**：`completed` ⇄ 停在 `running` 是 #33 丙①/丙② 的分档依据；
 * 4. **观测不拖垮主功能**（CR9-45／#29 同族）：写不进只 warn，读不到只 null，都不抛。
 *
 * 全程零网络、零 prisma（`SnapshotResult` 是 `import type`，编译后即消失），
 * 落点由 `REFRESH_PROGRESS_FILE` 指到系统临时目录 ⇒ 不许把仓库目录当测试产物落点。
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SnapshotResult } from "./market-snapshot";
import {
  completedToday,
  finishRefreshProgress,
  hasCompletionLedger,
  lastCompletedAt,
  readRefreshProgress,
  recordRefreshResult,
  startRefreshProgress,
} from "./refresh-progress";

const TYPES = ["stock", "fund", "bond", "crypto", "hk"];

function res(type: string, over: Partial<SnapshotResult> = {}): SnapshotResult {
  return {
    type,
    total: 10,
    updated: 10,
    failedBatches: 0,
    tookMs: 1234,
    snapshotAt: "2026-10-04T18:00:00.000Z",
    ...over,
  };
}

const file = () => process.env.REFRESH_PROGRESS_FILE as string;

describe("刷新腿进度状态位（CR9-60／#33 甲）", () => {
  let dir = "";
  let prevEnv: string | undefined;

  beforeEach(() => {
    prevEnv = process.env.REFRESH_PROGRESS_FILE;
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "rp-"));
    process.env.REFRESH_PROGRESS_FILE = path.join(dir, "refresh-progress.json");
  });

  afterEach(() => {
    if (prevEnv === undefined) delete process.env.REFRESH_PROGRESS_FILE;
    else process.env.REFRESH_PROGRESS_FILE = prevEnv;
    fs.rmSync(dir, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  it("起跑就落一次盘：running／types 全／current 是第一类／done 空", () => {
    startRefreshProgress(TYPES);
    const p = readRefreshProgress();
    expect(p?.outcome).toBe("running");
    expect(p?.types).toEqual(TYPES);
    expect(p?.current).toBe("stock");
    expect(p?.done).toEqual([]);
    expect(typeof p?.startedAt).toBe("string");
    expect(p?.finishedAt).toBe(null);
  });

  it("每完成一类推进一格：done 累计、current 跟着走、startedAt 不被改写", () => {
    startRefreshProgress(TYPES);
    const t0 = readRefreshProgress()?.startedAt;
    recordRefreshResult(res("stock"));
    let p = readRefreshProgress();
    expect(p?.done.map((x) => x.type)).toEqual(["stock"]);
    expect(p?.current).toBe("fund");
    recordRefreshResult(res("fund", { updated: 3500 }));
    p = readRefreshProgress();
    expect(p?.done.map((x) => x.type)).toEqual(["stock", "fund"]);
    expect(p?.current).toBe("bond");
    expect(p?.outcome).toBe("running"); // 中途永远还是 running——这正是"被打断"的形状
    expect(p?.startedAt).toBe(t0);
  });

  it("五类刷完 ⇒ current 归 null（『跑完了』与『停在第几类』必须不同形）", () => {
    startRefreshProgress(TYPES);
    for (const t of TYPES) recordRefreshResult(res(t));
    const p = readRefreshProgress();
    expect(p?.current).toBe(null);
    expect(p?.done).toHaveLength(5);
  });

  it("收尾 completed：落时刻、不改 startedAt、逐类结果还在", () => {
    startRefreshProgress(TYPES);
    const t0 = readRefreshProgress()?.startedAt;
    recordRefreshResult(res("stock"));
    finishRefreshProgress("completed");
    const p = readRefreshProgress();
    expect(p?.outcome).toBe("completed");
    expect(p?.startedAt).toBe(t0);
    expect(typeof p?.finishedAt).toBe("string");
    expect(p?.done).toHaveLength(1); // 收尾不许把已完成的那一类抹掉
  });

  it("🔁 异常收尾也标 failed：这条链的失败形态同样留得下来", () => {
    startRefreshProgress(TYPES);
    finishRefreshProgress("failed");
    const p = readRefreshProgress();
    expect(p?.outcome).toBe("failed");
    expect(p?.current).toBe(null);
  });

  it("没有起跑记录时收尾/回调都不抛（观测不许反过来打断刷新）", () => {
    expect(() => finishRefreshProgress("completed")).not.toThrow();
    expect(readRefreshProgress()?.outcome).toBe("completed");
    expect(() => recordRefreshResult(res("bond"))).not.toThrow();
    const p = readRefreshProgress();
    expect(p?.done.map((x) => x.type)).toEqual(["bond"]); // 单类型漏 start 时也要留下痕迹
  });

  it("写盘失败只 warn：本模块的异常绝不往上冒（CR9-45／#29 同族）", () => {
    startRefreshProgress(TYPES);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(fs, "writeFileSync").mockImplementation(() => {
      throw new Error("readonly volume");
    });
    expect(() => recordRefreshResult(res("stock"))).not.toThrow();
    expect(() => finishRefreshProgress("completed")).not.toThrow();
    expect(warn).toHaveBeenCalledTimes(2);
    vi.restoreAllMocks();
  });

  it("先写 .tmp 再改名 ⇒ 磁盘上不留半截文件", () => {
    startRefreshProgress(TYPES);
    recordRefreshResult(res("stock"));
    expect(fs.existsSync(`${file()}.tmp`)).toBe(false);
    expect(fs.existsSync(file())).toBe(true);
  });

  it("🔁 读不到就 null：没有文件／半截 JSON／形状不对，三种都当『没有进度可读』", () => {
    expect(readRefreshProgress()).toBe(null); // 还没有文件
    fs.writeFileSync(file(), '{"startedAt":"2026-10-0', "utf8"); // 半截
    expect(readRefreshProgress()).toBe(null);
    fs.writeFileSync(file(), JSON.stringify({ startedAt: "x" }), "utf8"); // 缺 done/types
    expect(readRefreshProgress()).toBe(null);
    fs.writeFileSync(file(), "[1,2]", "utf8"); // 顶层不是对象
    expect(readRefreshProgress()).toBe(null);
  });

  it("模块作用域被 HMR 重建后仍能续上（done 读的是盘，不是内存——C17）", async () => {
    startRefreshProgress(TYPES);
    recordRefreshResult(res("stock"));
    vi.resetModules();
    const fresh = await import("./refresh-progress");
    fresh.recordRefreshResult(res("fund"));
    const p = fresh.readRefreshProgress();
    expect(p?.done.map((x) => x.type)).toEqual(["stock", "fund"]);
    expect(p?.current).toBe("bond");
  });

  // ---------- CR9-61（乙＝可续跑）：完成账本这一半 ----------

  it("CR9-61：每跑完一类就往账本里记一条该类的完成时刻", () => {
    startRefreshProgress(["stock", "fund"]);
    recordRefreshResult(res("stock"));
    const p = readRefreshProgress();
    expect(typeof p?.lastCompleted.stock).toBe("string");
    expect(p?.lastCompleted.fund).toBeUndefined(); // 没跑完的那一类不许有记录
    expect(Number.isNaN(Date.parse(String(p?.lastCompleted.stock)))).toBe(false);
  });

  // #36／CR9-64（主人 10-05 取「甲」）：盖章条件从"这一轮跑完了"收紧成"这一轮真写入了行"。
  // 实测把这件事逼出来的两枚形态都在 10-05 白天那一轮里：crypto 三批全失败仍被盖章，
  // 而被挡的 stock 把首次时刻从 01:01 重盖章成 16:27——闸门本身没被这两枚骗到
  // （挡不挡还要"今日有 snapshotAt"那一半先成立），被骗的是读账本的人。
  it("#36：一行都没写的那一类不进账本（全失败与被挡都不算「跑完过」）", () => {
    startRefreshProgress(["crypto", "stock"]);
    recordRefreshResult(res("crypto", { updated: 0, failedBatches: 3, snapshotAt: null }));
    recordRefreshResult(res("stock", { updated: 0, skipped: true, snapshotAt: null }));
    const p = readRefreshProgress();
    expect(p?.done.length).toBe(2); // 逐类结果照旧留痕——收的是账本，不是观测
    expect(p?.lastCompleted.crypto).toBeUndefined();
    expect(p?.lastCompleted.stock).toBeUndefined();
    expect(hasCompletionLedger()).toBe(false); // 空账本 ⇒ 闸门退回旧判据，而不是"跑完过"
  });

  it("🔁 #36：同一类先有真写入的盖章、后来一轮 updated=0 ⇒ 首次时刻保住不被重盖章，而真写入照常盖", () => {
    startRefreshProgress(["stock", "fund"]);
    recordRefreshResult(res("stock")); // updated=10 ⇒ 盖章
    const first = readRefreshProgress()?.lastCompleted.stock;
    expect(typeof first).toBe("string");
    startRefreshProgress(["stock"]);
    recordRefreshResult(res("stock", { updated: 0, skipped: true })); // 被挡的一轮
    expect(readRefreshProgress()?.lastCompleted.stock).toBe(first); // 不许覆盖成"现在"
    recordRefreshResult(res("fund", { updated: 7 })); // 真写入了的照常记
    expect(typeof readRefreshProgress()?.lastCompleted.fund).toBe("string");
  });

  it("CR9-61🔁：新一轮 start 不许抹掉上一轮的完成记录（跨轮合并，否则那次刷新白烧）", () => {
    startRefreshProgress(["stock", "fund"]);
    recordRefreshResult(res("stock"));
    const first = readRefreshProgress()?.lastCompleted.stock;
    // #38／10-06 反向验证挖出来的：这条曾经"看不见回退"——把盖章整行删掉时 `first` 与后来的值
    // 同为 `undefined`，`toBe` 照样成立 ⇒ 它只验得出"没被抹掉"，验不出"从来没记过"。
    // 这条前置就是把"记过"先钉住，之后比较才有内容。（同文件上面那条 🔁 #36 已经有同款前置。）
    expect(typeof first).toBe("string");
    startRefreshProgress(["fund"]); // 例如早上手动补一次 fund
    const p = readRefreshProgress();
    expect(p?.types).toEqual(["fund"]);
    expect(p?.lastCompleted.stock).toBe(first); // stock 的证据还在
    expect(p?.done).toEqual([]); // 而"本轮跑到哪儿"确实跟着新一轮重置
  });

  it("CR9-61：completedToday 判的是北京日——今日记录为真、昨日记录为假（与 #23/#22(b) 同一把尺）", () => {
    const todayIso = new Date().toISOString();
    const yesterdayIso = new Date(Date.now() - 86_400_000).toISOString();
    startRefreshProgress(["stock"]);
    fs.writeFileSync(
      file(),
      JSON.stringify({
        startedAt: todayIso,
        types: ["stock"],
        current: null,
        done: [],
        outcome: "completed",
        finishedAt: todayIso,
        lastCompleted: { stock: todayIso, fund: yesterdayIso },
      }),
      "utf8",
    );
    expect(completedToday("stock")).toBe(true);
    expect(completedToday("fund")).toBe(false); // 昨日跑完 ⇒ 今天这一类还能补
    expect(completedToday("bond")).toBe(false); // 账本里根本没有这一类
    expect(lastCompletedAt("stock")).toBe(todayIso);
    expect(lastCompletedAt("bond")).toBe(null);
  });

  it("CR9-61：hasCompletionLedger 两态——没文件／空账本都是 false，老文件缺字段也当空账本（退回旧判据）", () => {
    expect(hasCompletionLedger()).toBe(false); // 还没有任何文件
    startRefreshProgress(["stock"]);
    expect(hasCompletionLedger()).toBe(false); // 起了轮但还没跑完任何一类
    recordRefreshResult(res("stock"));
    expect(hasCompletionLedger()).toBe(true);
    // CR9-60 那版写出来的文件里没有 `lastCompleted` 字段：读侧补空对象，不许当成"读到了记录"
    fs.writeFileSync(
      file(),
      JSON.stringify({
        startedAt: new Date().toISOString(),
        types: ["stock"],
        current: null,
        done: [],
        outcome: "completed",
        finishedAt: new Date().toISOString(),
      }),
      "utf8",
    );
    expect(readRefreshProgress()?.lastCompleted).toEqual({});
    expect(hasCompletionLedger()).toBe(false);
  });
});
