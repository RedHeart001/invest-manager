import { describe, expect, it } from "vitest";

import { detectPhases, phaseAttributionText, type BarLike } from "./phases";

function seq(from: number, to: number, step: number, startDay = 1): BarLike[] {
  const out: BarLike[] = [];
  for (let v = from; v !== to + step; v += step) {
    out.push({
      date: `2026-01-${String(startDay++).padStart(2, "0")}`,
      close: v,
    });
  }
  return out;
}

describe("detectPhases（ZigZag 阶段划分）", () => {
  it("单边上涨 → 单个上涨阶段，幅度与天数正确", () => {
    const bars = seq(100, 140, 2); // 21 根，+40%
    const phases = detectPhases(bars);
    expect(phases).toHaveLength(1);
    expect(phases[0].direction).toBe("up");
    expect(phases[0].label).toBe("上涨");
    expect(phases[0].changePct).toBeCloseTo(40, 1);
    expect(phases[0].tradingDays).toBe(20);
    expect(phases[0].startDate).toBe(bars[0].date);
    expect(phases[0].endDate).toBe(bars[20].date);
  });

  it("涨-跌-涨完整摆动 → 三阶段，各段幅度正确", () => {
    const a = seq(100, 120, 2, 1); // idx 0-10
    const b = seq(118, 100, -2, 12); // idx 11-20
    const c = seq(102, 120, 2, 22); // idx 21-30
    const phases = detectPhases([...a, ...b, ...c]);
    expect(phases.map((p) => p.direction)).toEqual(["up", "down", "up"]);
    expect(phases[0].changePct).toBeCloseTo(20, 1);
    expect(phases[1].changePct).toBeCloseTo(-16.67, 1);
    expect(phases[2].changePct).toBeCloseTo(20, 1);
  });

  it("阈值内噪声 → 单个震荡阶段", () => {
    const bars: BarLike[] = [100, 101, 99, 100, 99.5, 100.5, 99.8, 100.2].map(
      (close, i) => ({
        date: `2026-02-${String(i + 1).padStart(2, "0")}`,
        close,
      }),
    );
    const phases = detectPhases(bars);
    expect(phases).toHaveLength(1);
    expect(phases[0].direction).toBe("flat");
    expect(phases[0].label).toBe("震荡");
    expect(Math.abs(phases[0].changePct)).toBeLessThan(1);
  });

  it("上涨后小幅回落（未达反转阈值）→ 上涨段 + 收尾小段", () => {
    const bars = [...seq(100, 120, 2, 1), ...seq(119, 117, -1, 12)];
    const phases = detectPhases(bars);
    expect(phases[0].direction).toBe("up");
    expect(phases[0].changePct).toBeCloseTo(20, 1);
    expect(phases.length).toBeGreaterThanOrEqual(1);
  });

  it("数据不足（<2 根）→ 空数组", () => {
    expect(detectPhases([])).toEqual([]);
    expect(detectPhases([{ date: "2026-01-01", close: 100 }])).toEqual([]);
  });

  it("自定义反转阈值生效", () => {
    const bars = seq(100, 110, 1, 1); // +10%
    expect(detectPhases(bars, { reversalPct: 20 })).toHaveLength(1);
  });

  it("归因文案统一含'可能相关'且最多两条", () => {
    expect(phaseAttributionText([])).toBeNull();
    const text = phaseAttributionText(["年报超预期", "行业政策", "第三条"]);
    expect(text).toContain("可能相关");
    expect(text).toContain("年报超预期");
    expect(text).not.toContain("第三条");
  });
});
