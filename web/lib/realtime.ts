/**
 * CR9-92（OPT-3 第一批 1a）：详情页「当日实时行情条」的读侧判据。
 *
 * 这个文件里只放**不含网络判断**的四件纯事：两个节奏怎么落到请求上、这一块到底显不显示、
 * 拉不到时交什么、什么时候不该发（规则④）。取数在 `app/api/realtime/route.ts`，
 * 渲染在 `app/product/[type]/[code]/RealtimeStrip.tsx`。
 *
 * 三条已定参数的出处＝`docs/PLAN.md:172`（现价 10s、分时 60s、"分时序列归属日期==北京今日"是
 * 唯一的当日判据）。⚠️ 那两个秒数是**预设值**：TTL／并发 N／共识阈值都归 1b（欠 10-13 A 窗的
 * ②③④），所以这里不许把它们写成"测出来的"，屏上也不为此多一句话——`consensus.provisional`
 * 住在响应里，机器读得出来就够了（主人 10-05 的字：面向开发者的数落机器可读位）。
 */
import { marketClockOf } from "./market-clock";
import type { Quote } from "./data-service";

export type RealtimeVerdict = "agree" | "diverged" | "no_second_source";

export type RealtimePoint = { t: string; price: number | null; volume: number | null };

export type RealtimeLeg = {
  kind: "price" | "intraday";
  source: string;
  ok: boolean;
  latencyMs: number;
  detail: string | null;
};

export type RealtimeIntraday = {
  interval: string;
  date: string | null;
  bars: number;
  lastAt: string;
  source: string | null;
  points: RealtimePoint[];
};

/** 与 `data-service/app/realtime.py` 的 `aggregate()` 一字对应（键面登记在 `lib/ds-contract.ts`）。 */
export type RealtimeResponse = {
  type: string;
  code: string;
  observedAt: string;
  parts: string[];
  price: Quote | null;
  intraday: RealtimeIntraday | null;
  crossChecked: boolean;
  verifyVerdict: RealtimeVerdict;
  consensus: {
    verdict: RealtimeVerdict;
    diffPct: number | null;
    thresholdPct: number;
    provisional: boolean;
    basis: string;
  };
  /** `null`＝这一轮**没取**分时（只问了现价），不能读成"没有当日数据"（CR9-67 丙 那三态纪律） */
  hasTodayData: boolean | null;
  intradayDateIsToday: boolean | null;
  wired: boolean;
  sources: RealtimeLeg[];
  degraded: boolean;
  note: string | null;
};

/** 现价一跳＝10s（已定参数）。 */
export const PRICE_POLL_MS = 10_000;
/** 分时原生粒度 1 分钟 ⇒ 每 6 跳取一次全量（10s × 6 = 60s，PLAN.md:172 的第二个节奏）。 */
export const INTRADAY_EVERY_TICKS = 6;
/**
 * BFF→ds 的预算。**必须 ≥ ds 这一条路的最坏耗时**（CR9-88 的 §B 契约）：
 * `realtime.py` 串行跑腿，最多 2 条现价腿＋1 条分时腿 × `LEG_TIMEOUT_S=3s`＝9s，
 * 留 3s 余量。实时区不许出现 20s 排队，所以这里的数也是"实时区没有排队"这件事的第二道锁。
 */
export const REALTIME_BUDGET_MS = 12_000;

/** 屏上字面的唯一来源（屏幕上的字归主人定：要改只改这一张表，改完用例会点名是哪一句）。 */
export const REALTIME_TEXT = {
  heading: "当日实时",
  lastUpdate: (hhmmss: string) => `最后更新 ${hhmmss}（北京）`,
  stale: (hhmmss: string) => `刷新没成功，仍显示 ${hhmmss} 那一次的价`,
  agree: "两家报价一致",
  noSecondSource: "只有一家报价，未做比对",
  /** 这句此前住在组件里（`RealtimeStrip.tsx:109` 的 `??` 右半）＝这张表的第二处硬编码文案。
   *  搬进来不是新字面——它是 note 缺失时的兜底（10-13 下午复核）。
   *  10-17 主人的字＝「句 B 六串要改字面」⇒ 这句与上面三串一起换成说人话的字面，
   *  `heading`／`lastUpdate` 两串**没动**＝PLAN `:170`／`:181` 的需求原文逐字引用着它们。 */
  diverged: "两家报价有出入",
};

/** 第 N 跳该问哪几条腿（tick 从 0 起，0 是进页面的那一次）。 */
export function partsForTick(tick: number): "price" | "price,intraday" {
  if (!Number.isInteger(tick) || tick < 0) return "price,intraday";
  return tick % INTRADAY_EVERY_TICKS === 0 ? "price,intraday" : "price";
}

/**
 * 把"这一跳"并进已有那一屏：现价每跳都换，分时只在**真取过分时的那一跳**才换。
 *
 * 为什么需要这一步：只问现价的响应里 `hasTodayData` 是 `null`（"这一轮没看"），
 * 直接整份替换会让这一块每 6 跳闪灭一次——那是自家节奏造成的闪，不是上游没数据。
 */
export function mergeTick(prev: RealtimeResponse | null, next: RealtimeResponse): RealtimeResponse {
  if (!prev) return next;
  if (next.parts.includes("intraday")) return next;
  return {
    ...next,
    intraday: prev.intraday,
    hasTodayData: prev.hasTodayData,
    intradayDateIsToday: prev.intradayDateIsToday,
  };
}

/**
 * 规则①：**有当日数据才显示**，否则整块不渲染（不给"点了看到别的数据"留空间）。
 * 判据就是 ds 那一位 `hasTodayData`（= 分时序列归属日 == 北京今日），这里不另算一份。
 * `null`（这一轮没取分时）也返回 false——但组件不会因此清掉已有的曲线：见 `RealtimeStrip` 里
 * "只在取过分时的那一轮重新决定显不显示"这一条。
 */
export function stripVisible(r: RealtimeResponse | null | undefined): boolean {
  return r?.hasTodayData === true;
}

/** 现价那一格的数：取到就用，取不到交最后已知值（规则③），两者都不空白、都不假装。 */
export function displayPrice(r: RealtimeResponse | null): number | null {
  return r?.price?.price ?? null;
}

/** "最后更新"到底是谁的时刻：优先上游自己的时间戳，缺失才回落 `observedAt`。 */
export function lastUpdateStamp(r: RealtimeResponse | null): string | null {
  if (!r) return null;
  const raw = r.price?.timestamp ?? r.observedAt;
  const m = /T(\d{2}:\d{2}:\d{2})/.exec(raw ?? "");
  return m ? m[1] : (raw ?? null);
}

/** 规则③的机器可读位：这一屏是"刚取到的"还是"停住的最后值"。 */
export function isStale(lastOkAtMs: number | null, nowMs: number, failCount: number): boolean {
  // 一次都没成过 ⇒ 组件根本不渲染这一格，这里不许替它编一个"停住的最后值"
  if (lastOkAtMs === null) return false;
  return failCount > 0 || nowMs - lastOkAtMs > PRICE_POLL_MS * INTRADAY_EVERY_TICKS;
}

/**
 * 规则④的"非交易时段不请求"：**粗判据**，只认星期与该市场的墙上钟点（钟名沿用
 * `market-clock.ts` 那张表，不另立第二份）。它**故意不判节假日与半日市**——那要交易日历，
 * 而"这里不猜开没开盘"是 `market-clock.ts:11` 写下来的既有边界（#58 丙）。
 *
 * 判得粗是安全的：这个闸只管"要不要发这一发"（省钱），真正决定屏上有没有这一块的是 ds 那一侧
 * 的"分时序列归属日 == 北京今日"（判据①）。节假日上会发生的是"少发几发"，不是"显示错数据"。
 */
const SESSIONS: Record<string, number[][]> = {
  // 分钟数区间（该市场墙上钟）：A股／场内基金 09:30–11:30、13:00–15:00
  stock: [[570, 690], [780, 900]],
  fund: [[570, 690], [780, 900]],
  // 港股 09:30–12:00、13:00–16:00
  hk: [[570, 720], [780, 960]],
  // 美股 09:30–16:00（美东）
  us: [[570, 960]],
};

function wallMinutes(instantMs: number, timeZone: string): { minuteOfDay: number; weekday: number } {
  const got = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(new Date(instantMs));
  const at = (t: string) => got.find((p) => p.type === t)?.value ?? "0";
  const hour = Number(at("hour")) % 24; // hour12:false 在部分引擎里把 0 点写成 "24"
  const weekdayIndex: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  return { minuteOfDay: hour * 60 + Number(at("minute")), weekday: weekdayIndex[at("weekday")] ?? 0 };
}

export function sessionMayBeOpen(type: string, nowMs: number): boolean {
  const windows = SESSIONS[type];
  const clock = marketClockOf(type);
  if (!windows || !clock) return false; // 认不得的市场（crypto/bond）＝不发这一发
  const { minuteOfDay, weekday } = wallMinutes(nowMs, clock.timeZone);
  if (weekday === 0 || weekday === 6) return false;
  return windows.some(([start, end]) => minuteOfDay >= start && minuteOfDay <= end);
}

/** 规则④的另一半：页面不可见就不发（`document.hidden`）。SSR 里没有 document ⇒ 当作可见，
 *  由组件在挂载后再决定（浏览器那一侧才是这条规则的适用面）。 */
export function pageVisible(): boolean {
  if (typeof document === "undefined") return true;
  return !document.hidden;
}

export function shouldPoll(type: string, nowMs: number): boolean {
  return sessionMayBeOpen(type, nowMs) && pageVisible();
}

/** 迷你折线：把分时点画成一条 SVG path（这里不引 ECharts——一条 10s 一跳的窄条不值得再养一个实例）。 */
export function sparkPath(points: RealtimePoint[], width: number, height: number): string | null {
  const ys = points.map((p) => p.price).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (ys.length < 2 || width <= 0 || height <= 0) return null;
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1; // 一条平线也要画得出来（span=0 会把所有点甩到 y=0）
  const stepX = width / (points.length - 1);
  let d = "";
  let i = -1;
  for (const p of points) {
    i += 1;
    if (typeof p.price !== "number" || !Number.isFinite(p.price)) continue;
    const x = (i * stepX).toFixed(1);
    const y = (height - ((p.price - min) / span) * height).toFixed(1);
    d += `${d ? "L" : "M"}${x} ${y}`;
  }
  return d || null;
}
