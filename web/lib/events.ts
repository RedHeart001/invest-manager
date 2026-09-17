// 事件标注（R11 轻量归因第一阶段）：
// - 挑选需要解释的日期：阶段转折点 + 大波动日（单日 |涨跌| > 3%）
// - 按日期挂接当日新闻/公告标题（股票走东财源；其余类型明确标注缺口）
// - 归因克制：展示层统一用"可能相关"，不做因果断言

import { dsGet } from "@/lib/data-service";
import { Lru } from "./lru";

export type EventItem = {
  date: string; // YYYY-MM-DD
  time?: string;
  title: string;
  source?: string;
  url?: string;
};

export type EventsResult = {
  degraded: boolean;
  note: string | null;
  byDate: Record<string, EventItem[]>;
};

const DEGRADE_NOTES: Record<string, string> = {
  fund: "基金事件源（季报/分红节点）暂未接入，仅展示阶段划分",
  bond: "可转债公告源（强赎/下修）暂未接入，仅展示阶段划分",
  crypto: "加密货币暂无免费新闻源，仅展示阶段划分并标注数据缺口",
};

type NewsResp = {
  code: string;
  degraded: boolean;
  note: string | null;
  items: { date: string; time?: string; title: string; source?: string; url?: string }[];
};

const CACHE_TTL_MS = 10 * 60 * 1000;
// CR4（C17 漏网 + P3）：跨请求共享缓存挂 globalThis（防 HMR 重置）；
// 降级结果用短 TTL，避免源恢复后事件区仍"粘" 10 分钟。
const DEGRADED_TTL_MS = 60 * 1000;
type CacheEntry = { ts: number; result: EventsResult; degraded: boolean };
const EVENTS_CACHE_KEY = Symbol.for("invest-manager.events.cache");
const cacheBox: { current: Lru<string, CacheEntry> } = ((globalThis as unknown as Record<
  symbol,
  { current: Lru<string, CacheEntry> } | undefined
>)[EVENTS_CACHE_KEY] ??= { current: new Lru<string, CacheEntry>(300) });
const cache = cacheBox.current;

/** 纯函数：新闻条目 → 按日期分组（可单测） */
export function groupByDate(items: EventItem[]): Record<string, EventItem[]> {
  const byDate: Record<string, EventItem[]> = {};
  for (const it of items) {
    if (!it.date || !it.title) continue;
    (byDate[it.date] ??= []).push(it);
  }
  return byDate;
}

/** 纯函数：挑选需要标注事件的日期（转折点 + 大波动日），最多 12 个 */
export function pickEventDates(
  candles: { date: string; close: number }[],
  phaseEndDates: string[],
  bigMovePct = 3,
): string[] {
  const dates = new Set<string>(phaseEndDates);
  for (let i = 1; i < candles.length; i++) {
    const prev = candles[i - 1].close;
    if (prev > 0) {
      const pct = (candles[i].close / prev - 1) * 100;
      if (Math.abs(pct) >= bigMovePct) dates.add(candles[i].date);
    }
  }
  return [...dates].slice(0, 12);
}

export async function fetchEvents(type: string, code: string): Promise<EventsResult> {
  const key = `${type}:${code}`;
  const hit = cache.get(key);
  if (hit) {
    const ttl = hit.degraded ? DEGRADED_TTL_MS : CACHE_TTL_MS;
    if (Date.now() - hit.ts < ttl) return hit.result;
  }

  let result: EventsResult;
  if (type !== "stock") {
    result = { degraded: true, note: DEGRADE_NOTES[type] ?? "该类型暂无事件源", byDate: {} };
  } else {
    try {
      const resp = await dsGet<NewsResp>("/news", { code }, 30_000);
      if (resp.degraded) {
        result = { degraded: true, note: resp.note ?? "新闻源暂不可用", byDate: {} };
      } else {
        result = {
          degraded: false,
          note: null,
          byDate: groupByDate(resp.items as EventItem[]),
        };
      }
    } catch (e) {
      result = {
        degraded: true,
        note: `新闻源不可达：${e instanceof Error ? e.message : "unknown"}`,
        byDate: {},
      };
    }
  }
  cache.set(key, { ts: Date.now(), result, degraded: result.degraded });
  return result;
}
