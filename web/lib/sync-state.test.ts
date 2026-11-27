import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// W4（2026-11-27）：四态展示的**今日同步结果**这一半（`lib/sync-state.ts` ＋ `staleNotes` 的前两档）。
//
// 要钉住的那一形：昨天成功、今天 02:00 那一轮失败 ⇒ 旧判据（`listAt` 早于昨日才说话、给一天
// 宽限）那一整天一个字都不出，页面把昨天的名单当今天的用。方案 §9 的分界是
// 「数据库保留旧数据」≠「页面把旧数据当最新」。
//
// 三条不许在这里被写成谎：
//  ① 今日这一轮**还没跑**（盘上还是昨天那轮）⇒ 一个字都不出（夜里 00:30 打开页面时）；
//  ② 今日失败 ⇒ 必须同时说得出 历史状态／数据时间／失败原因（缺一件就是"看不见的降级"）；
//  ③ `skipped`（当日幂等闸门挡下）与 `degraded`（取到了但来源降级）都不是 `failed`。

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** 北京某个"月-日 时:分"对应的 UTC 瞬间（与 `freshness.test.ts` 同一把手） */
function bj(day: string, hhmm: string): Date {
  return new Date(`${day}T${hhmm}:00+08:00`);
}

import { DEGRADED_NOTE_MARKER, parseSyncAttempt, readSyncAttempt, retryNote, todayDegradedNote, todayFailure } from "./sync-state";
import { staleNotes } from "./freshness";
import { beijingToday } from "./time";

const TODAY = "2026-10-02";

/** 盘上那份 `sync-state.json` 的最小形状（键名与 `sync_scheduler._mark_outcome` 同源） */
function stateFile(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    lastAttemptDate: TODAY,
    lastAttemptTrigger: "daily",
    lastAttemptOutcome: "partial_failed",
    at: `${TODAY}T02:31:00+08:00`,
    lastResult: {
      ok: false,
      outcome: "partial_failed",
      failedTypes: ["stock"],
      results: [
        { type: "stock", error: "eastmoney request failed on all hosts: ProxyError" },
        { type: "fund", count: 28013 },
        { type: "bond", skipped: true, note: "今日已同步" },
        { type: "hk", count: 4596 },
      ],
    },
    ...over,
  };
}

const at = (day: string) => ({ listAt: bj(day, "12:00"), snapAt: bj(day, "13:00"), maxPrice: 12.5 });

describe("读 DS 的同步状态（W4）：形状不对一律当「没有」，不许让展示层 500", () => {
  it("正常形状：逐类失败／降级／跳过各归各位", () => {
    const a = parseSyncAttempt(
      stateFile({
        lastResult: {
          results: [
            { type: "stock", error: "boom" },
            { type: "fund", note: `${DEGRADED_NOTE_MARKER}sina：只取前排 N 页` },
            { type: "bond", skipped: true },
          ],
        },
      }),
    );
    expect(a.date).toBe(TODAY);
    expect(a.trigger).toBe("daily");
    expect(a.outcome).toBe("partial_failed");
    expect(a.failed).toEqual({ stock: { error: "boom" } });
    expect(Object.keys(a.degraded)).toEqual(["fund"]);
    expect(a.skipped).toEqual(["bond"]);
    expect(a.source).toBe("disk");
  });

  it("🔁 不是对象 ⇒ 空视图（不抛、不编）", () => {
    for (const bad of [null, 42, "x", [], undefined]) {
      const a = parseSyncAttempt(bad);
      expect(a.date).toBeNull();
      expect(a.failed).toEqual({});
      // `source` 说的是「读没读到文件」，与形状无关：这里压根没有文件内容可取
      expect(a.source).toBe("none");
    }
  });

  it("🔁 是对象但形状不对（lastResult 为 null／results 不是数组）⇒ 各字段全空，只剩下「读到过文件」这一事实", () => {
    for (const bad of [{ lastResult: null }, { lastResult: { results: {} } }, { lastResult: { results: [1, "x", null] } }]) {
      const a = parseSyncAttempt(bad);
      expect(a.date).toBeNull();
      expect(a.outcome).toBeNull();
      expect(a.failed).toEqual({});
      expect(a.degraded).toEqual({});
      expect(a.skipped).toEqual([]);
      expect(a.retry).toBeNull();
    }
  });

  it("🔁 `degraded` 的判据是**同一个字面量**（`sync.ts` 拼、这里判），改词不会静默退化成 fresh", () => {
    const src = readFileSync(path.join(HERE, "sync.ts"), "utf8");
    // 反向：sync.ts 里那串字必须来自常量，不许再手写一份字面量
    expect(src).toContain("DEGRADED_NOTE_MARKER");
    expect(src).not.toContain('`list degraded source=');
  });

  it("今天这一轮 vs 昨天那一轮：只有今天的失败算「今日失败」", () => {
    const today = parseSyncAttempt(stateFile());
    const yesterday = parseSyncAttempt(stateFile({ lastAttemptDate: "2026-10-01" }));
    // `today` 显式给：判据日只有一个来源，免得跨零点的那次渲染出现两个"今天"
    expect(todayFailure(today, "stock", TODAY)).toEqual({
      error: "eastmoney request failed on all hosts: ProxyError",
    });
    // 夜里 00:30 打开页面时盘上还是昨天那轮 ⇒ 不许把昨天说成今日
    expect(todayFailure(yesterday, "stock", TODAY)).toBeNull();
    expect(todayDegradedNote(yesterday, "stock", TODAY)).toBeNull();
  });
});

describe("补试那句话：四种状态都要说得出人话，且不许把 exhausted/cancelled 说成「还会再试」", () => {
  const plan = (state: string, over: Record<string, unknown> = {}) => ({
    date: TODAY,
    state,
    types: ["stock"],
    notBefore: `${TODAY}T03:01:00+08:00`,
    ...over,
  });

  it("pending：说出起跑时刻与类型", () => {
    expect(retryNote(plan("pending"), TODAY)).toContain("03:01");
    expect(retryNote(plan("pending"), TODAY)).toContain("stock");
  });

  it("🔁 exhausted／cancelled：必须明说「今日不再自动重试」（说成已安排就是第二种谎）", () => {
    for (const s of ["exhausted", "cancelled"]) {
      const text = retryNote(plan(s), TODAY) ?? "";
      expect(text).toContain("今日不再自动重试");
      expect(text).not.toContain("已安排");
    }
  });

  it("🔁 不是今天的计划 ⇒ null（不把昨天的补试安排在今天的页面上）", () => {
    expect(retryNote(plan("pending"), "2026-10-03")).toBeNull();
    expect(retryNote(null, TODAY)).toBeNull();
  });
});

describe("staleNotes 的四态：今日失败立刻标历史，不等超过一天", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(bj(TODAY, "17:00"));
  });
  afterEach(() => vi.useRealTimers());

  const failedAttempt = () => parseSyncAttempt(stateFile());

  it("昨天成功、今天失败 ⇒ 立刻出 failed，并带名单日／快照日／失败原因（方案点名的三件）", () => {
    const n = staleNotes([{ type: "stock", ...at("2026-10-01") }], TODAY, failedAttempt());
    expect(n).toEqual([
      {
        type: "stock",
        kind: "failed",
        since: "2026-10-01",
        dataAt: "2026-10-01",
        reason: "eastmoney request failed on all hosts: ProxyError",
      },
    ]);
  });

  it("🔁 反向：同一份数据、**没有**今日失败 ⇒ 一个字都不出（宽限期那一档没被顺手放宽）", () => {
    expect(staleNotes([{ type: "stock", ...at("2026-10-01") }], TODAY, null)).toEqual([]);
  });

  it("🔁 反向：盘上还是昨天那轮（今日未跑）⇒ 也不出字（不许把昨天说成今日失败）", () => {
    const y = parseSyncAttempt(stateFile({ lastAttemptDate: "2026-10-01" }));
    expect(staleNotes([{ type: "stock", ...at("2026-10-01") }], TODAY, y)).toEqual([]);
  });

  it("今日失败且库里一行都没有 ⇒ unavailable（不是「旧」，是「没有」），不编日子", () => {
    const n = staleNotes([], TODAY, failedAttempt());
    expect(n).toEqual([
      { type: "stock", kind: "unavailable", since: "", reason: "eastmoney request failed on all hosts: ProxyError" },
    ]);
  });

  it("库里连快照都没有 ⇒ failed 只带名单日、不虚构 dataAt", () => {
    const n = staleNotes(
      [{ type: "stock", listAt: bj("2026-10-01", "02:00"), snapAt: null, maxPrice: null }],
      TODAY,
      failedAttempt(),
    );
    expect(n[0]).toMatchObject({ kind: "failed", since: "2026-10-01" });
    expect(n[0].dataAt).toBeUndefined();
  });

  it("今日失败且该类型在补试名单里 ⇒ 那句话挂到这一条上（不是另起一行）", () => {
    const a = parseSyncAttempt(stateFile({ retry: { date: TODAY, state: "pending", types: ["stock"], notBefore: `${TODAY}T03:01:00+08:00` } }));
    const n = staleNotes([{ type: "stock", ...at("2026-10-01") }], TODAY, a);
    expect(n[0].kind).toBe("failed");
    expect(n[0].retry).toContain("03:01");
  });

  it("🔁 补试只覆盖 failing 的那几类：不在名单里的类型不许挂这句话", () => {
    const a = parseSyncAttempt(
      stateFile({
        retry: { date: TODAY, state: "pending", types: ["bond"], notBefore: `${TODAY}T03:01:00+08:00` },
      }),
    );
    const n = staleNotes([{ type: "stock", ...at("2026-10-01") }], TODAY, a);
    expect(n[0].retry).toBeUndefined();
  });

  it("今日取到了但来源降级 ⇒ degraded，且与 failed 用不同 kind（新数据也可能降级）", () => {
    const a = parseSyncAttempt(
      stateFile({
        lastResult: { results: [{ type: "stock", note: `${DEGRADED_NOTE_MARKER}sina：只取前排 5 页` }] },
      }),
    );
    const n = staleNotes([{ type: "stock", ...at(TODAY) }], TODAY, a);
    expect(n).toEqual([
      { type: "stock", kind: "degraded", since: TODAY, reason: `${DEGRADED_NOTE_MARKER}sina：只取前排 5 页` },
    ]);
  });

  it("🔁 被当日闸门跳过（skipped）不是失败 ⇒ 不出字", () => {
    const a = parseSyncAttempt(stateFile({ lastResult: { results: [{ type: "stock", skipped: true }] } }));
    expect(staleNotes([{ type: "stock", ...at(TODAY) }], TODAY, a)).toEqual([]);
  });

  it("优先级：今日失败 盖过 库内陈旧（同一类只说一次，成因不重复报）", () => {
    const n = staleNotes([{ type: "stock", ...at("2026-09-01") }], TODAY, failedAttempt());
    expect(n.map((x) => x.kind)).toEqual(["failed"]);
  });

  it("多类混合仍按 tab 顺序，条数不截断（上限是渲染层的事）", () => {
    const a = parseSyncAttempt(
      stateFile({ lastResult: { results: [{ type: "hk", error: "hkex down" }, { type: "stock", error: "em down" }] } }),
    );
    const n = staleNotes([{ type: "stock", ...at("2026-10-01") }, { type: "hk", ...at("2026-10-01") }], TODAY, a);
    expect(n.map((x) => x.type)).toEqual(["stock", "hk"]);
  });
});

describe("readSyncAttempt：落点找不到时是「没有」而不是「读坏了」", () => {
  it("候选路径都不存在 ⇒ source=none、readError=null（首次部署/开发态不是故障）", () => {
    const saved = process.env.SYNC_STATE_FILE;
    process.env.SYNC_STATE_FILE = path.join(HERE, "definitely-missing-sync-state.json");
    try {
      const a = readSyncAttempt();
      // 仓库开发态那条候选（`../data-service/runtime/sync-state.json`）可能存在 ⇒ 只断言
      // "不会因为 env 那条不存在就报错"，且真读到文件时 source 必须是 disk。
      expect(a.readError).toBeNull();
      expect(["disk", "none"]).toContain(a.source);
    } finally {
      if (saved === undefined) delete process.env.SYNC_STATE_FILE;
      else process.env.SYNC_STATE_FILE = saved;
    }
  });
});
