/**
 * R20（2026-11-12）：`computePePercentile` 纯函数离线单测＋详情页接线字面断言。
 *
 * 口径（主人 11-12 拍板接受近似并如实标注）：histPE_i = peTtm × close_i/priceNow ⇒
 * peTtm>0 时 PE 分位恒等于价格分位——「peTtm 无关性」那枚牙齿钉的就是这个数学事实。
 * 分位定义钉死：round(100 × count(close_i < priceNow) / N)，严格小于、含末根。
 * 一律 null（C4）：peTtm≤0/非有限（亏损股）、现价无效、有效 bar < MIN_BARS(120)。
 *
 * 🔁 反向钻不落盘：MIN_BARS 改 0 走「内存 transpile + new Function」（沿 C34 合成件纪律，
 * 不动生产文件一个字）；接线那半沿 jsx-key-guard 的源码字面先例（防「函数对但没人挂它」）。
 *
 * 运行（零出网）：`npx vitest run lib/metrics.test.ts`
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { MIN_BARS, computePePercentile } from "./metrics";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const METRICS_SRC = readFileSync(path.join(HERE, "metrics.ts"), "utf-8");
const PAGE_SRC = readFileSync(
  path.join(HERE, "..", "app", "product", "[type]", "[code]", "page.tsx"),
  "utf-8",
);

/** n 根连续日历日 bar（纯函数测试不需要真交易日历），默认 close = i+1 */
function hist(n: number, from = "2023-01-01", closeOf: (i: number) => number = (i) => i + 1) {
  const out: { date: string; close: number }[] = [];
  const d = new Date(`${from}T00:00:00.000Z`);
  for (let i = 0; i < n; i++) {
    out.push({ date: d.toISOString().slice(0, 10), close: closeOf(i) });
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
}

describe("computePePercentile：分位定义", () => {
  it("手工序列＝150 根 close 1..150、现价 100 ⇒ 99 根严格更小 ⇒ 66%", () => {
    const v = computePePercentile(20, 100, hist(150));
    expect(v).not.toBeNull();
    expect(v!.percentile).toBe(66);
    expect(v!.bars).toBe(150);
    expect(v!.from).toBe("2023-01-01");
    expect(v!.to).toBe("2023-05-30");
    expect(v!.approx).toBe(true);
  });

  it("严格小于＝现价恰等于一批 close 时那些根不计入（全 10 元、现价 10 ⇒ 0%）", () => {
    const flat = hist(150, "2023-01-01", () => 10);
    expect(computePePercentile(20, 10, flat)!.percentile).toBe(0);
    expect(computePePercentile(20, 10.01, flat)!.percentile).toBe(100);
  });

  it("含末根＝最后一根 close 也参与比较（现价 151 ⇒ 150/150 ⇒ 100%）", () => {
    expect(computePePercentile(20, 151, hist(150))!.percentile).toBe(100);
    expect(computePePercentile(20, 150, hist(150))!.percentile).toBe(99);
  });

  it("🔁 peTtm 无关性牙齿＝同价格序列 peTtm=10/30/0.5 ⇒ 结果逐字相等（PE 分位≡价格分位）", () => {
    const h = hist(200);
    const a = computePePercentile(10, 120, h);
    const b = computePePercentile(30, 120, h);
    const c = computePePercentile(0.5, 120, h);
    expect(a).not.toBeNull();
    expect(b).toEqual(a);
    expect(c).toEqual(a);
  });
});

describe("computePePercentile：一律 null 的边界（C4）", () => {
  it.each([0, -5, null, undefined, NaN, Infinity])("peTtm=%s ⇒ null（亏损股/无效值不硬算）", (pe) => {
    expect(computePePercentile(pe as number | null | undefined, 100, hist(150))).toBeNull();
  });

  it.each([0, -1, null, undefined, NaN, Infinity])("priceNow=%s ⇒ null", (p) => {
    expect(computePePercentile(20, p as number | null | undefined, hist(150))).toBeNull();
  });

  it("空历史 ⇒ null；119 根 ⇒ null；120 根 ⇒ 非 null（MIN_BARS 边界逐根钉）", () => {
    expect(MIN_BARS).toBe(120);
    expect(computePePercentile(20, 100, [])).toBeNull();
    expect(computePePercentile(20, 100, hist(119))).toBeNull();
    expect(computePePercentile(20, 100, hist(120))).not.toBeNull();
  });

  it("无效 close（NaN/0/负/Infinity）先剔除再数数＝150 根里 31 根无效 ⇒ 119 有效 ⇒ null", () => {
    const h = hist(150);
    const bad = [NaN, 0, -1, Infinity];
    for (let i = 0; i < 31; i++) h[i].close = bad[i % bad.length];
    expect(computePePercentile(20, 100, h)).toBeNull();
    h[30].close = 5; // 把无效区最后一根补成有效 ⇒ 120 ⇒ 出数
    expect(computePePercentile(20, 100, h)).not.toBeNull();
  });
});

describe("computePePercentile：窗口标签按实得跨度说（不谎称）", () => {
  it("真拿到 3 年（1096 根、跨 1095 天）⇒ 近3年", () => {
    const v = computePePercentile(20, 600, hist(1096, "2023-01-01"));
    expect(v!.windowLabel).toBe("近3年");
  });

  it("🔁 请求 3 年只拿到 8 个月（240 根、跨 239 天）⇒ 近8个月，不许出现「近3年」", () => {
    const v = computePePercentile(20, 120, hist(240, "2026-01-01"));
    expect(v!.windowLabel).toBe("近8个月");
    expect(v!.windowLabel).not.toContain("3年");
  });

  it("刚够门槛的短窗口（120 根、跨 119 天）⇒ 近4个月（月数四舍五入、至少 1）", () => {
    const v = computePePercentile(20, 60, hist(120));
    expect(v!.windowLabel).toBe("近4个月");
  });
});

describe("🔁 反向钻与接线（不落盘、零出网）", () => {
  it("🔁 内存把 MIN_BARS 改成 0 ⇒ 119 根不再被挡、空历史直接崩（证明阈值真在管事）", () => {
    expect(METRICS_SRC).toContain("MIN_BARS = 120");
    const mutated = METRICS_SRC.replace("MIN_BARS = 120", "MIN_BARS = 0");
    expect(mutated).toContain("MIN_BARS = 0");
    // metrics.ts 零 import ⇒ transpile 成 CJS 后 new Function 即可执行（纯内存，不写盘）
    const js = ts.transpileModule(mutated, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const mod: { exports: Record<string, unknown> } = { exports: {} };
    new Function("exports", "module", js)(mod.exports, mod);
    const fn = mod.exports.computePePercentile as typeof computePePercentile;

    expect(fn(20, 100, hist(119))).not.toBeNull(); // 阈值没了 ⇒ 119 根也出数（尺会红）
    expect(() => fn(20, 100, [])).toThrow(); // 空历史失去保护 ⇒ undefined.date 崩
    expect(computePePercentile(20, 100, hist(119))).toBeNull(); // 真件仍挡
    expect(computePePercentile(20, 100, [])).toBeNull();
  });

  it("接线＝第 7 腿仅 stock、3 年区间、复用既有 getKlineRange（源码字面，防「函数对但没人挂它」）", () => {
    expect(PAGE_SRC).toContain('import { computePePercentile } from "@/lib/metrics"');
    expect(PAGE_SRC).toContain("isoAddDays(todayIso(), -1095)");
    expect(PAGE_SRC).toContain('type === "stock" ? { start:');
    expect(PAGE_SRC).toContain("peRange ? getKlineRange(type, code, peRange.start, peRange.end) : Promise.resolve(null)");
    expect(PAGE_SRC).toContain("computePePercentile(quote?.peTtm, quote?.price, peHistory)");
    // 既有六腿与 ProductCharts 不受影响的最低读数：初始 K 线仍走 effectiveKline
    expect(PAGE_SRC).toContain("initialKline={effectiveKline}");
  });

  it("接线＝stats 槽位受非空保护、标签带「近似」、网格下口径说明含盈利假设与财报季失真", () => {
    expect(PAGE_SRC).toContain("if (peView) stats.push(");
    expect(PAGE_SRC).toContain("PE分位(${peView.windowLabel}·近似)");
    expect(PAGE_SRC).toContain("{peView && (");
    expect(PAGE_SRC).toContain("近似口径");
    expect(PAGE_SRC).toContain("盈利（TTM）不变");
    expect(PAGE_SRC).toContain("财报季盈利变动时会失真");
    expect(PAGE_SRC).toContain("实得 {peView.bars} 根日线");
  });
});