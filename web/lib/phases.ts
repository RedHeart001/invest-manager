// 阶段划分（R11 轻量归因第一阶段）：ZigZag 摆动点检测，纯本地算法
// 把选定区间切成上涨/下跌/震荡阶段，标注幅度与天数——零外部依赖。
// 归因克制原则由展示层执行：一律标"可能相关"，不做因果断言。

export type PhaseDirection = "up" | "down" | "flat";

export type Phase = {
  startDate: string;
  endDate: string;
  direction: PhaseDirection;
  changePct: number;
  tradingDays: number; // 阶段内交易日数（不含起始日）
  label: string; // 上涨 / 下跌 / 震荡
};

export type PhaseOptions = {
  /** 反转阈值（%）：收盘价自阶段极值回撤/反弹超过该幅度即确认转折 */
  reversalPct?: number;
  /** |changePct| 低于该值（%）判为震荡 */
  flatPct?: number;
};

const DEFAULTS = { reversalPct: 4, flatPct: 1.0 };

export type BarLike = { date: string; close: number };

/**
 * ZigZag 摆动点检测：
 * 1. 收盘价序列中确认转折点（自极值反向变动 ≥ reversalPct）
 * 2. 相邻转折点（含区间首尾）构成阶段
 * 3. 按段内涨跌幅标注 上涨/下跌/震荡
 */
export function detectPhases(barsInput: BarLike[], opts: PhaseOptions = {}): Phase[] {
  // 数据清洗（代码审查修复）：close ≤ 0 或非有限值（脏数据/占位行）会让涨幅
  // 计算出现 Infinity/NaN，并让"自极值反向变动"的判定恒真 → 输出错误阶段与幅度。
  const bars = barsInput.filter((b) => Number.isFinite(b.close) && b.close > 0);
  const { reversalPct: T, flatPct: FLAT } = { ...DEFAULTS, ...opts };
  const n = bars.length;
  if (n < 2) return [];

  const pivots: number[] = [0];
  let dir = 0; // 0 未定，1 上行中，-1 下行中
  let hiIdx = 0; // 区间内最高收盘（未定阶段时）
  let loIdx = 0; // 区间内最低收盘（未定阶段时）
  let extIdx = 0; // 当前阶段极值

  for (let i = 1; i < n; i++) {
    const p = bars[i].close;
    if (dir === 0) {
      if (p > bars[hiIdx].close) hiIdx = i;
      if (p < bars[loIdx].close) loIdx = i;
      const upTrigger = p >= bars[loIdx].close * (1 + T / 100);
      const downTrigger = p <= bars[hiIdx].close * (1 - T / 100);
      // 两个触发同时成立时，取更近（更大下标）极值的方向
      if (upTrigger && (!downTrigger || loIdx >= hiIdx)) {
        pivots.push(loIdx);
        dir = 1;
        extIdx = i;
      } else if (downTrigger) {
        pivots.push(hiIdx);
        dir = -1;
        extIdx = i;
      }
    } else if (dir === 1) {
      if (p > bars[extIdx].close) {
        extIdx = i;
      } else if (p <= bars[extIdx].close * (1 - T / 100)) {
        pivots.push(extIdx);
        dir = -1;
        extIdx = i;
      }
    } else {
      if (p < bars[extIdx].close) {
        extIdx = i;
      } else if (p >= bars[extIdx].close * (1 + T / 100)) {
        pivots.push(extIdx);
        dir = 1;
        extIdx = i;
      }
    }
  }

  // 段列表：确认的转折点 + 收尾（最后一个极值 → 最后一根）
  const points = [...pivots];
  if (points[points.length - 1] !== n - 1) {
    // 收尾点：若当前存在进行中的极值段，用 extIdx 收尾更贴近形态
    if (dir !== 0 && extIdx > points[points.length - 1] && extIdx < n - 1) {
      points.push(extIdx);
    }
    points.push(n - 1);
  }

  const out: Phase[] = [];
  for (let k = 0; k < points.length - 1; k++) {
    const a = points[k];
    const b = points[k + 1];
    if (b <= a) continue;
    const pct = (bars[b].close / bars[a].close - 1) * 100;
    const direction: PhaseDirection = pct > FLAT ? "up" : pct < -FLAT ? "down" : "flat";
    out.push({
      startDate: bars[a].date,
      endDate: bars[b].date,
      direction,
      changePct: Math.round(pct * 100) / 100,
      tradingDays: b - a,
      label: direction === "up" ? "上涨" : direction === "down" ? "下跌" : "震荡",
    });
  }
  return out;
}

/** 阶段标注色（涨红跌绿，中国行情惯例） */
export function phaseColor(direction: PhaseDirection): string {
  if (direction === "up") return "#FCEBEB"; // red-50
  if (direction === "down") return "#EAF3DE"; // green-50
  return "#F1EFE8"; // gray-50
}

/** 归因文案（克制）：只列"可能相关"事件，不做因果断言 */
export function phaseAttributionText(eventTitles: string[]): string | null {
  if (!eventTitles.length) return null;
  return `可能相关：${eventTitles.slice(0, 2).join("；")}`;
}
