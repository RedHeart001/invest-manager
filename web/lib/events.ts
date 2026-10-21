// 事件标注（R11 轻量归因第一阶段）：
// - 挑选需要解释的日期：阶段转折点 + 大波动日（单日 |涨跌| > 3%）
// - 按日期挂接当日新闻标题（股票走东财；转债先问映射腿拿正股、再走同一条腿；其余类型明确标注缺口）
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
  /** #75 的 web 那一半（CR9-111）：转债事件区的来路＝正股。只有转债且真拿到正股时才有值。 */
  fromStock?: { code: string; name: string | null } | null;
  /** 机器可读位（不上屏的那一维）：转债这一条为什么接不上。
   *  `route-failed`＝路由不可用（未装载／404／连不上），`no-underlying`＝映射答不出（不在册或那一行没有正股代码）。
   *  这两态在屏上都只说"缺口"，但成因不同，验收时要分得开（R16 同口径）。 */
  mapStatus?: "ok" | "no-underlying" | "route-failed";
};

// E-3 刀 A（10-12 主人「按推荐方案做」的字）：三句里两处事实不准（crypto／fund），bond 那句只统一了
// 尾巴；改准后由 `events.test.ts` 的字面断言钉住（改回旧字面 ⇒ 断言恰红）。
//  · crypto 原写「暂无免费新闻源」与自家事实不符：Tavily 已是 OPT-2 新闻融合的第三家
//    （`data-service/app/hotspot/pipeline.py:195`），缺的是「按标的检索」这条通道，不是「源」。
//  · fund 原写「季报/分红节点」：`/fund/report` 只回定期报告清单
//    （`akshare_provider.py` 的 `PERIODIC_KEYWORDS` 四串），兑现不了「分红节点」，
//    文案不许承诺库里没有的那一档。
export const DEGRADE_NOTES: Record<string, string> = {
  fund: "基金事件源（定期报告公告）暂未接入事件区，仅展示阶段划分",
  bond: "可转债公告源（强赎/下修）暂未接入事件区，仅展示阶段划分",
  crypto: "加密货币事件源暂未接入事件区，仅展示阶段划分",
};

type NewsResp = {
  code: string;
  degraded: boolean;
  note: string | null;
  items: { date: string; time?: string; title: string; source?: string; url?: string }[];
};

/** `GET /bond/underlying`（CR9-108 落的只读映射腿）：转债 → 正股 */
type UnderlyingResp = {
  code: string;
  degraded: boolean;
  note: string | null;
  stockCode: string | null;
  stockName: string | null;
};

/** 转债那一屏的来路句——文案只有这一处出口，组件不自己组词（改这里必须让 `events.test.ts` 的字面断言翻红） */
export function bondEventsFrom(from: { code: string; name: string | null }): string {
  return `事件区取的是正股「${from.name ?? from.code}」的新闻，转债公告源仍未接入`;
}

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

/**
 * 纯函数（CR-10）：把"全量按日期分组"的事件收窄到指定日期集合。
 * R11 的设计是**只**给"阶段转折点 + 大波动日"挂接事件；此前 `fetchEvents`
 * 返回全部有新闻的日期（`pickEventDates` 成了只被单测引用的死代码）。
 */
export function narrowByDates(
  byDate: Record<string, EventItem[]>,
  dates: string[],
): Record<string, EventItem[]> {
  const want = new Set(dates);
  const out: Record<string, EventItem[]> = {};
  for (const [d, items] of Object.entries(byDate)) {
    if (want.has(d)) out[d] = items;
  }
  return out;
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

/** 个股新闻那一腿（stock 直接用，bond 拿正股代码用）——两条臂共用一份降级语义 */
async function newsEvents(code: string): Promise<EventsResult> {
  try {
    const resp = await dsGet<NewsResp>("/news", { code }, 30_000);
    if (resp.degraded) {
      return { degraded: true, note: resp.note ?? "新闻源暂不可用", byDate: {} };
    }
    return { degraded: false, note: null, byDate: groupByDate(resp.items as EventItem[]) };
  } catch (e) {
    return {
      degraded: true,
      note: `新闻源不可达：${e instanceof Error ? e.message : "unknown"}`,
      byDate: {},
    };
  }
}

export async function fetchEvents(type: string, code: string): Promise<EventsResult> {
  const key = `${type}:${code}`;
  const hit = cache.get(key);
  if (hit) {
    const ttl = hit.degraded ? DEGRADED_TTL_MS : CACHE_TTL_MS;
    if (Date.now() - hit.ts < ttl) return hit.result;
  }

  let result: EventsResult;
  if (type === "stock") {
    result = await newsEvents(code);
  } else if (type === "bond") {
    // #75 的 web 那一半（CR9-111，主人的字＝「按你自己定的方案执行落实」）：转债自己没有新闻通道，
    // 先问映射腿拿正股，再拿正股代码去问个股新闻——所以那一屏从此**会发上游请求**（旧写法一次都不发）。
    // 成本口径：映射＝一枚东财令牌 ⇔ 件内 ≈4 个 HTTP（ds 侧 TTL 24h），个股新闻＝1 发（600s 缓存）。
    let map: UnderlyingResp | null;
    try {
      map = await dsGet<UnderlyingResp>("/bond/underlying", { code }, 30_000);
    } catch {
      // 路由不可用（未装载／404／连不上）＝维持接之前那句缺口说明，不把"连接被拒绝"当新故障上屏
      map = null;
    }
    const underlying =
      map && !map.degraded && map.stockCode ? { code: map.stockCode, name: map.stockName } : null;
    if (underlying) {
      const ev = await newsEvents(underlying.code);
      result = ev.degraded ? ev : { ...ev, fromStock: underlying, mapStatus: "ok" as const };
    } else {
      result = {
        degraded: true,
        note: DEGRADE_NOTES.bond,
        byDate: {},
        mapStatus: map ? "no-underlying" : "route-failed",
      };
    }
  } else {
    result = { degraded: true, note: DEGRADE_NOTES[type] ?? "该类型暂无事件源", byDate: {} };
  }
  cache.set(key, { ts: Date.now(), result, degraded: result.degraded });
  return result;
}
