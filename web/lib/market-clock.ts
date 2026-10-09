/**
 * #58：报价时间戳用的是哪一个钟。
 *
 * 上游给的是**那个市场的本地墙上时间**，原样透传、不换钟——`_ts_iso` 只归一形态
 * （`data-service/app/providers/tencent_provider.py` 的 CR9-7 注释自己写着这件事），
 * akshare 那条腿是 `datetime.fromtimestamp(ts)`＝跑 ds 的这台机器的钟（北京）。
 * 于是 `/product/us/CEG` 上「2026-10-08T16:00:01」是**美东**的 16:00，换算成北京＝当天凌晨 04:00；
 * 主人 10-09 就是把这条正确的数读成了「过期一天」（原话与诊断见 FIX-LEDGER 第 56 项末、第 58 项）。
 *
 * 所以这里只做一件不含判断的事：**说出那个时间戳属于哪个钟**，并在两个钟不同时补一份北京时间。
 * 不猜"开没开盘"、不说"这只还活着没有"——那两样要交易日历／存续状态，是另一项（#58 丙）。
 *
 * 只覆盖**真的带时间戳的那几条腿**：yfinance 与 coingecko 的现价响应里根本没有 `timestamp`
 * （`openbb_provider.py:119-131`／`crypto_provider.py:123-137`）；那种情形屏上原样不动——
 * 没有钟可点名就不许编一个。
 */

const BEIJING = "Asia/Shanghai";

/** type → 哪一个钟。市场集合与 `tencent_provider.CURRENCY_BY_TYPE` 对齐。 */
const CLOCK_BY_TYPE: Record<string, { label: string; timeZone: string }> = {
  us: { label: "美东", timeZone: "America/New_York" },
  hk: { label: "香港", timeZone: "Asia/Hong_Kong" },
  stock: { label: "北京", timeZone: BEIJING },
  fund: { label: "北京", timeZone: BEIJING },
  bond: { label: "北京", timeZone: BEIJING },
};

export type MarketClock = { label: string; timeZone: string };

export function marketClockOf(type: string): MarketClock | null {
  return CLOCK_BY_TYPE[type] ?? null;
}

/** `_ts_iso` 的产物形状；它凑不满 14 位数字时原样透传，那种形态这里不认领、也不改。 */
const ISO_14 = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$/;

type Wall = [string, string, string, string, string, string];

function parts(ms: number, timeZone: string): Wall {
  const got = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(ms));
  const at = (type: string) => got.find((p) => p.type === type)?.value ?? "00";
  // hour12:false 在部分引擎里把 0 点写成 "24"
  return [at("year"), at("month"), at("day"), String(Number(at("hour")) % 24).padStart(2, "0"), at("minute"), at("second")];
}

function stamp([y, mo, d, h, mi, s]: Wall): string {
  return `${y}-${mo}-${d} ${h}:${mi}:${s}`;
}

/** 某个瞬间在指定时区上的偏移（毫秒）：把该时区的墙上读数为当 UTC 算，再减掉真 UTC。 */
function zoneOffsetMs(instantMs: number, timeZone: string): number {
  const [y, mo, d, h, mi, s] = parts(instantMs, timeZone);
  return Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s)) - Math.floor(instantMs / 1000) * 1000;
}

/** 把「某时区的墙上时间」还原成瞬间；两遍修正确保夏令时切换点取到落地那一侧的偏移。 */
function instantFromWallClock(wall: Wall, timeZone: string): number {
  const [y, mo, d, h, mi, s] = wall;
  const naive = Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s));
  const first = naive - zoneOffsetMs(naive, timeZone);
  return naive - zoneOffsetMs(first, timeZone);
}

/** 那一屏的时间戳格：`美东 2026-10-08 16:00:01（北京 2026-10-09 04:00:01）`；没钟可点名就返回 null。 */
export function quoteClockText(type: string, timestamp?: string | null): string | null {
  const raw = timestamp?.trim();
  if (!raw) return null;
  const clock = marketClockOf(type);
  if (!clock) return raw; // 认不得的市场：原样给，不贴钟名
  const hit = ISO_14.exec(raw);
  if (!hit) return raw; // 形态不是 `_ts_iso` 归一出来的那一种：不认领
  const wall: Wall = [hit[1], hit[2], hit[3], hit[4], hit[5], hit[6]];
  const local = stamp(wall);
  if (clock.timeZone === BEIJING) return `北京 ${local}`;
  const asBeijing = stamp(parts(instantFromWallClock(wall, clock.timeZone), BEIJING));
  // 同一个墙上钟（港股＝UTC+8 不换夏令时）不必再写一遍
  return asBeijing === local ? `${clock.label} ${local}` : `${clock.label} ${local}（北京 ${asBeijing}）`;
}
