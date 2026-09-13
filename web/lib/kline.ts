// 日 K 增量缓存（PLAN M3/KlineDaily）：BFF 维护，历史日 K 不变只拉增量
// - 首次请求：整段回源 data-service 并落库
// - 后续请求：命中区间读库，仅增量区间（缓存末日+1 → 请求末日）回源
// - 分钟级数据（interval=1m）：实时数据不落库，直连透传（R: PLAN 约定）
// - 回源失败时已有缓存照常返回（R10 优雅降级，note 标注）

import { prisma } from "@/lib/prisma";
import { Lru } from "./lru";
import { beijingToday } from "./time";
import { dsGet } from "@/lib/data-service";
import { detectPhases } from "@/lib/phases";

export type Candle = {
  date: string; // YYYY-MM-DD（分钟级为 YYYY-MM-DD HH:MM）
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
};

export type KlineResult = {
  type: string;
  code: string;
  interval: string;
  valueOnly: boolean;
  source: string;
  candles: Candle[];
  phases: ReturnType<typeof detectPhases>;
  cachedDays: number;
  fetchedDays: number;
  note: string | null;
};

type DsKline = {
  type: string;
  code: string;
  interval: string;
  valueOnly?: boolean;
  source: string;
  candles: { date: string; open: number; high: number; low: number; close: number; volume: number | null }[];
};

const MAX_RANGE_DAYS = 366 * 5; // 防御上限：5 年

// 增量复查窗口（R15：避免非交易日/频繁访问导致的无效回源）
const RECHECK_MS = 30 * 60 * 1000;
// M3/O2：缓存加容量上限（防长期运行内存无界增长）
const lastChecked = new Lru<string, number>(500);
const lastFailed = new Lru<string, number>(500); // 失败负缓存（整段回源失败的窗口抑制）

function dayStart(iso: string): Date {
  return new Date(`${iso}T00:00:00.000Z`);
}

function isoAddDays(iso: string, days: number): string {
  const d = dayStart(iso);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function todayIso(): string {
  // 东财交易日历以北京时间为准（B4：统一走公共 util）
  return beijingToday();
}

export function normalizeRange(
  start?: string | null,
  end?: string | null,
): { start: string; end: string } | { error: string } {
  const iso = (s: string | null | undefined) =>
    s && /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : null;
  const s = iso(start) ?? isoAddDays(todayIso(), -90);
  const e = iso(end) ?? todayIso();
  if (dayStart(s) > dayStart(e)) return { error: "start must be <= end" };
  if (dayStart(e) < dayStart(s) || (dayStart(e).getTime() - dayStart(s).getTime()) / 86_400_000 > MAX_RANGE_DAYS) {
    return { error: `range too large (max ${MAX_RANGE_DAYS} days)` };
  }
  return { start: s, end: e };
}

async function fetchDs(
  type: string,
  code: string,
  startIso: string,
  endIso: string,
  interval: string,
): Promise<DsKline> {
  const ymd = (iso: string) => iso.replaceAll("-", "");
  return dsGet<DsKline>(
    "/kline",
    {
      type,
      code,
      start: interval === "1d" ? ymd(startIso) : undefined,
      end: interval === "1d" ? ymd(endIso) : undefined,
      interval,
    },
    45_000,
  );
}

async function upsertCandles(
  type: string,
  code: string,
  candles: { date: string; open: number; high: number; low: number; close: number; volume: number | null }[],
  source: string,
): Promise<number> {
  const valid = candles.filter((c) => /^\d{4}-\d{2}-\d{2}$/.test(c.date));
  if (valid.length === 0) return 0;
  // 只写入新日期（已存在的日期跳过，避免重复 UPDATE 与虚增 fetchedDays）
  const dates = valid.map((c) => dayStart(c.date).toISOString());
  const existing = await prisma.klineDaily.findMany({
    where: { type, code, date: { in: dates.map((d) => new Date(d)) } },
    select: { date: true },
  });
  const have = new Set(existing.map((r) => r.date.toISOString().slice(0, 10)));
  let n = 0;
  for (const c of valid) {
    if (have.has(c.date)) continue;
    try {
      await prisma.klineDaily.create({
        data: {
          type,
          code,
          date: dayStart(c.date),
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
          volume: c.volume,
          source,
        },
      });
      n += 1;
    } catch (e) {
      // 并发请求可能同时对同一 (type,code,date) 判定"不存在"后各写一次
      // （代码审查修复）：唯一约束冲突按"已写入"处理，其余错误上抛。
      if (!isUniqueViolation(e)) throw e;
    }
  }
  return n;
}

function isUniqueViolation(e: unknown): boolean {
  return typeof e === "object" && e !== null && (e as { code?: string }).code === "P2002";
}

export async function getKlineRange(
  type: string,
  code: string,
  start: string,
  end: string,
  interval = "1d",
): Promise<KlineResult> {
  // 分钟级：不落库，直连透传
  if (interval !== "1d") {
    const ds = await fetchDs(type, code, start, end, interval);
    return {
      type,
      code,
      interval,
      valueOnly: Boolean(ds.valueOnly),
      source: ds.source,
      candles: ds.candles,
      phases: [],
      cachedDays: 0,
      fetchedDays: ds.candles.length,
      note: null,
    };
  }

  const cached = await prisma.klineDaily.findMany({
    where: {
      type,
      code,
      date: { gte: dayStart(start), lte: dayStart(end) },
    },
    orderBy: { date: "asc" },
  });

  let fetched = 0;
  let fetchedSource = "";
  const notes: string[] = [];
  const cacheKey = `${type}:${code}`;

  if (cached.length === 0) {
    // 失败负缓存（R15：限流/故障期间，窗口内不再整段回源，避免每页加载重复砸站）
    if (Date.now() - (lastFailed.get(cacheKey) ?? 0) < RECHECK_MS) {
      return {
        type,
        code,
        interval: "1d",
        valueOnly: false,
        source: "--",
        candles: [],
        phases: [],
        cachedDays: 0,
        fetchedDays: 0,
        note: "近期回源失败（限流/故障），窗口期内暂不再尝试",
      };
    }
    // 整段回源
    try {
      const ds = await fetchDs(type, code, start, end, interval);
      if ((ds.candles?.length ?? 0) === 0) {
        // 2026-09-13 code review：上游"成功但空响应"也必须进失败窗口，
        // 否则每次请求都整段回源（限流期被持续捶打）；并给出明确降级说明。
        lastFailed.set(cacheKey, Date.now());
        notes.push(`上游返回空数据${ds.source ? `（源：${ds.source}）` : ""}，窗口期内暂不重试`);
      } else {
        fetched = await upsertCandles(type, code, ds.candles, ds.source);
        fetchedSource = ds.source;
        lastChecked.set(cacheKey, Date.now());
      }
    } catch (e) {
      notes.push(`回源失败：${e instanceof Error ? e.message : "unknown"}`);
      lastFailed.set(cacheKey, Date.now());
    }
  } else {
    // 失败负缓存同样适用于缺口回源分支（代码审查修复）：否则头部缺口每次
    // 页面加载都会重试，抵消 R15 的限流保护。
    const withinFailWindow = Date.now() - (lastFailed.get(cacheKey) ?? 0) < RECHECK_MS;
    const minCached = cached[0].date.toISOString().slice(0, 10);
    const maxCached = cached[cached.length - 1].date.toISOString().slice(0, 10);
    // 头部缺口（首次只缓存过 3M，后来请求 1Y）
    if (minCached > start) {
      if (withinFailWindow) {
        notes.push("历史区间回源近期失败（限流/故障），窗口期内跳过补齐");
      } else {
        try {
          const ds = await fetchDs(type, code, start, isoAddDays(minCached, -1), interval);
          fetched += await upsertCandles(type, code, ds.candles, ds.source);
          fetchedSource = ds.source;
          lastChecked.set(cacheKey, Date.now());
        } catch (e) {
          notes.push(`历史区间回源失败：${e instanceof Error ? e.message : "unknown"}`);
          lastFailed.set(cacheKey, Date.now());
        }
      }
    }
    // 尾部增量（缓存末日 < 请求末日）：30 分钟内已复查过则跳过（R15：避免非交易日空转）
    if (maxCached < end) {
      const recentlyChecked =
        Date.now() - (lastChecked.get(cacheKey) ?? 0) < RECHECK_MS;
      if (recentlyChecked) {
        notes.push("增量复查窗口内（30 分钟），本次使用缓存");
      } else {
        try {
          const ds = await fetchDs(type, code, isoAddDays(maxCached, 1), end, interval);
          fetched += await upsertCandles(type, code, ds.candles, ds.source);
          fetchedSource = fetchedSource || ds.source;
          lastChecked.set(cacheKey, Date.now());
        } catch (e) {
          notes.push(`增量回源失败：${e instanceof Error ? e.message : "unknown"}`);
          lastChecked.set(cacheKey, Date.now()); // 失败也进入窗口，避免连续重试
        }
      }
    }
  }

  const rows = await prisma.klineDaily.findMany({
    where: {
      type,
      code,
      date: { gte: dayStart(start), lte: dayStart(end) },
    },
    orderBy: { date: "asc" },
  });

  const candleList = rows.map((r) => ({
    date: r.date.toISOString().slice(0, 10),
    open: r.open,
    high: r.high,
    low: r.low,
    close: r.close,
    volume: r.volume,
  }));

  return {
    type,
    code,
    interval: "1d",
    valueOnly: rows.length > 0 && rows.every((r) => r.open === r.close && r.high === r.close && r.low === r.close),
    source: rows.length > 0 ? (fetchedSource || rows[rows.length - 1].source) : "cache",
    candles: candleList,
    // P5：阶段划分随响应返回（vendor_adapter 研报与详情页归因同源）
    phases:
      interval === "1d" && candleList.length >= 2
        ? detectPhases(
            candleList.map((c) => ({ ...c, volume: c.volume ?? 0 })),
          )
        : [],
    cachedDays: Math.max(0, rows.length - fetched),
    fetchedDays: fetched,
    note: notes.length > 0 ? notes.join("；") : null,
  };
}
