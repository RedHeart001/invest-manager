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
// CR4（C17 漏网）：跨请求共享缓存必须挂 globalThis——dev HMR 重建模块作用域
// 会重置模块级变量，lastFailed 的失败窗口（R15 限流保护）随之失效。
type LruRef = { current: Lru<string, number> };
const LAST_CHECKED_KEY = Symbol.for("invest-manager.kline.lastChecked");
// CR-05（本轮 code review）：头部缺口补全与尾部增量此前共用 `lastChecked`，
// 头补成功会立即压制同请求的尾部增量（同一 30 分钟窗口）→ 本次拿不到最新一日。
// 拆出独立的尾部复查键，两者互不影响。
const LAST_CHECKED_TAIL_KEY = Symbol.for("invest-manager.kline.lastCheckedTail");
const LAST_FAILED_KEY = Symbol.for("invest-manager.kline.lastFailed");
const lastCheckedBox: LruRef = ((globalThis as unknown as Record<symbol, LruRef | undefined>)[
  LAST_CHECKED_KEY
] ??= { current: new Lru<string, number>(500) });
const lastCheckedTailBox: LruRef = ((globalThis as unknown as Record<symbol, LruRef | undefined>)[
  LAST_CHECKED_TAIL_KEY
] ??= { current: new Lru<string, number>(500) });
const lastFailedBox: LruRef = ((globalThis as unknown as Record<symbol, LruRef | undefined>)[
  LAST_FAILED_KEY
] ??= { current: new Lru<string, number>(500) });
const lastChecked = lastCheckedBox.current; // 头部缺口补全的复查窗口
const lastCheckedTail = lastCheckedTailBox.current; // 尾部增量的复查窗口（CR-05 拆分）
const lastFailed = lastFailedBox.current; // 失败负缓存（整段回源失败的窗口抑制）

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
  if ((dayStart(e).getTime() - dayStart(s).getTime()) / 86_400_000 > MAX_RANGE_DAYS) {
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

/** CR6-P1-3 护栏：日期合法且 OHLC 均为有限数值，才允许写入 KlineDaily（列为 NOT NULL）。 */
export function isUsableCandle(c: {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
}): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(c.date) &&
    [c.open, c.high, c.low, c.close].every(Number.isFinite)
  );
}

async function upsertCandles(
  type: string,
  code: string,
  candles: { date: string; open: number; high: number; low: number; close: number; volume: number | null }[],
  source: string,
): Promise<number> {
  // CR6-P1-3：护栏——provider 侧已剔除 null OHLC，这里再兜一层，防未来
  // 新 provider 漏过滤时单行脏数据让整批 upsert 中断。
  const valid = candles.filter(isUsableCandle);
  if (valid.length === 0) return 0;
  // 只写入新日期（已存在的日期跳过，避免重复 UPDATE 与虚增 fetchedDays）
  const dates = valid.map((c) => dayStart(c.date).toISOString());
  const existing = await prisma.klineDaily.findMany({
    where: { type, code, date: { in: dates.map((d) => new Date(d)) } },
    select: { date: true },
  });
  const have = new Set(existing.map((r) => r.date.toISOString().slice(0, 10)));
  const fresh = valid.filter((c) => !have.has(c.date));
  if (fresh.length === 0) return 0;

  // CR-15（本轮 code review）：首段回源（5 年 ≈ 1200 行）此前逐行 await create，
  // 1200 次往返；改为分块多行 INSERT OR IGNORE——一次往返写多行，
  // 且 OR IGNORE 天然吸收并发请求对同一 (type,code,date) 的重复写入（无需 catch P2002）。
  // 分块 50：50 行 × 10 列 = 500 个绑定参数，低于 SQLite 默认 999 上限。
  //
  // 回归修复（本轮集成验收发现）：Prisma 对 SQLite 的 DateTime 存的是 **Unix 毫秒整数**，
  // 而 `$executeRawUnsafe` 传 ISO 字符串会存成 **text** → 与 Prisma 生成的
  // `date >= ? / <= ?`（数字比较）不匹配，导致这些行在带日期范围的查询里**被漏掉**
  // （实测：KlineDaily 中 text 行查不出，R13 交叉验证因此失败）。
  // 故原生 INSERT 的日期参数必须与 Prisma 同为毫秒数字（`dayStart().getTime()`）。
  const CHUNK = 50;
  let n = 0;
  for (let i = 0; i < fresh.length; i += CHUNK) {
    const batch = fresh.slice(i, i + CHUNK);
    const rowPlaceholder = "(?,?,?,?,?,?,?,?,?,?)";
    const params = batch.flatMap((c) => [
      randomId(), // 走原生 INSERT，id 需显式生成（Prisma 默认 cuid 不参与）
      type,
      code,
      dayStart(c.date).getTime(), // 毫秒整数：与 Prisma DateTime 存储一致
      c.open,
      c.high,
      c.low,
      c.close,
      c.volume,
      source,
    ]);
    await prisma.$executeRawUnsafe(
      `INSERT OR IGNORE INTO "KlineDaily"
         ("id","type","code","date","open","high","low","close","volume","source")
       VALUES ${batch.map(() => rowPlaceholder).join(",")}`,
      ...params,
    );
    n += batch.length;
  }
  return n;
}

/** 原生 INSERT 需要显式主键（Prisma 的 cuid 默认值不参与 $executeRaw） */
function randomId(): string {
  return crypto.randomUUID();
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
      // CR4（2026-09-15 review）：头部分支此前只查 lastFailed、不读 lastChecked，
      // 且"成功但空响应"既不写 lastChecked 也不写 lastFailed → 上市不足 1 年的
      // 标的选 1Y 区间时 minCached（上市日）恒 > start，每次页面加载都整段回源
      // 头部缺口，反复捶打东财（R15/C11 防线漏洞）。与尾部增量对称处理。
      const recentlyChecked =
        Date.now() - (lastChecked.get(cacheKey) ?? 0) < RECHECK_MS;
      if (withinFailWindow || recentlyChecked) {
        notes.push("历史区间回源近期失败/已复查（限流/故障），窗口期内跳过补齐");
      } else {
        try {
          const ds = await fetchDs(type, code, start, isoAddDays(minCached, -1), interval);
          if ((ds.candles?.length ?? 0) === 0) {
            // 与整段回源分支同口径：空响应进失败窗口（C11）
            lastFailed.set(cacheKey, Date.now());
            notes.push("历史区间上游返回空数据，窗口期内暂不重试");
          } else {
            fetched += await upsertCandles(type, code, ds.candles, ds.source);
            fetchedSource = ds.source;
            lastChecked.set(cacheKey, Date.now());
          }
        } catch (e) {
          notes.push(`历史区间回源失败：${e instanceof Error ? e.message : "unknown"}`);
          lastFailed.set(cacheKey, Date.now());
        }
      }
    }
    // 尾部增量（缓存末日 < 请求末日）：30 分钟内已复查过则跳过（R15：避免非交易日空转）
    // CR-05：读/写独立的 `lastCheckedTail`，不再被头部缺口补全压制。
    if (maxCached < end) {
      const recentlyChecked =
        Date.now() - (lastCheckedTail.get(cacheKey) ?? 0) < RECHECK_MS;
      if (recentlyChecked) {
        notes.push("增量复查窗口内（30 分钟），本次使用缓存");
      } else {
        try {
          const ds = await fetchDs(type, code, isoAddDays(maxCached, 1), end, interval);
          fetched += await upsertCandles(type, code, ds.candles, ds.source);
          fetchedSource = fetchedSource || ds.source;
          lastCheckedTail.set(cacheKey, Date.now());
        } catch (e) {
          notes.push(`增量回源失败：${e instanceof Error ? e.message : "unknown"}`);
          lastCheckedTail.set(cacheKey, Date.now()); // 失败也进入窗口，避免连续重试
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
