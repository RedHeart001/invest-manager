// R20（2026-11-12）：股票 PE 历史分位——近似口径，屏上如实标注。
// 数学事实：histPE_i = peTtm × close_i / priceNow ⇒ peTtm>0 时 PE 分位恒等于价格分位
// （同比例缩放不改排序），故实现只比价格。近似误差来自「盈利（TTM）不变」假设，
// 财报季盈利变动时会失真——口径声明住本注释＋详情页网格下一行说明。

export const MIN_BARS = 120;

export type PePercentileView = {
  percentile: number;
  bars: number;
  from: string;
  to: string;
  windowLabel: string;
  approx: true;
};

/** history 须按日期升序（getKlineRange 的返回即此形）。分位＝严格小于现价的 bar 占比（含末根）。 */
export function computePePercentile(
  peTtm: number | null | undefined,
  priceNow: number | null | undefined,
  history: { date: string; close: number }[],
): PePercentileView | null {
  // C4：算不出就给 null（亏损股 peTtm≤0、缺现价、历史不足），不许拿 0 或假数充
  if (peTtm == null || !Number.isFinite(peTtm) || peTtm <= 0) return null;
  if (priceNow == null || !Number.isFinite(priceNow) || priceNow <= 0) return null;
  const valid = history.filter((c) => Number.isFinite(c.close) && c.close > 0);
  if (valid.length < MIN_BARS) return null;

  const below = valid.filter((c) => c.close < priceNow).length;
  const percentile = Math.round((100 * below) / valid.length);

  // 窗口标签按实得跨度说：请求 3 年只拿到 8 个月就写「近8个月」，不谎称近3年
  const from = valid[0].date;
  const to = valid[valid.length - 1].date;
  const spanDays = (Date.parse(to) - Date.parse(from)) / 86_400_000;
  const years = spanDays / 365.25;
  const windowLabel =
    years >= 1.5
      ? `近${Math.round(years)}年`
      : `近${Math.max(1, Math.round(spanDays / 30.44))}个月`;

  return { percentile, bars: valid.length, from, to, windowLabel, approx: true };
}