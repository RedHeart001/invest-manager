"use client";

// 主图区 + 变化解读区（PLAN M3 六区结构 ③④，客户端交互）
// - 时间档位 1D/1W/1M/3M/6M/1Y + 自定义起止（1D 走分钟线透传，不落库）
// - 阶段背景带（ZigZag 客户端重算，与解读区联动）
// - 事件标记（转折点/大波动日 → "可能相关"新闻）
// - 多标的归一化收益率对比
// - 涨红跌绿（中国行情惯例）；R5：切换区间必须有可见加载态

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { EventsResult } from "@/lib/events";
import type { KlineResult } from "@/lib/kline";
import { detectPhases, phaseAttributionText, phaseColor, type Phase } from "@/lib/phases";

type Props = {
  type: string;
  code: string;
  initialKline: KlineResult;
  initialPhases: Phase[];
  events: EventsResult;
  valueDecimals: number;
  valueLabel: string; // 价格 / 单位净值
};

const PRESETS: { key: string; label: string; days: number; interval: "1m" | "1d" }[] = [
  { key: "1D", label: "1D", days: 1, interval: "1m" },
  { key: "1W", label: "1W", days: 7, interval: "1d" },
  { key: "1M", label: "1M", days: 30, interval: "1d" },
  { key: "3M", label: "3M", days: 90, interval: "1d" },
  { key: "6M", label: "6M", days: 182, interval: "1d" },
  { key: "1Y", label: "1Y", days: 365, interval: "1d" },
];

// B4：beijingToday 已抽公共 util（lib/time.ts）
import { beijingToday } from "@/lib/time";

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00.000Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const UP = "#dc2626"; // 涨红
const DOWN = "#16a34a"; // 跌绿

type Candle = KlineResult["candles"][number];

export default function ProductCharts({
  type,
  code,
  initialKline,
  initialPhases,
  events,
  valueDecimals,
  valueLabel,
}: Props) {
  const [kline, setKline] = useState<KlineResult>(initialKline);
  const [phases, setPhases] = useState<Phase[]>(initialPhases);
  const [rangeKey, setRangeKey] = useState("3M");
  const [custom, setCustom] = useState({ start: "", end: "" });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [compareInput, setCompareInput] = useState("");
  const [compare, setCompare] = useState<{ code: string; candles: Candle[] } | null>(null);
  const [chartReady, setChartReady] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstRef = useRef<unknown>(null);
  const instOnResizeRef = useRef<(() => void) | null>(null);
  // CR4（P2-7）：区间/对比加载竞态防护——快速切档时旧响应不得覆盖新状态。
  const abortRef = useRef<AbortController | null>(null);
  const seqRef = useRef(0);

  // CR4：卸载时中止在途请求
  useEffect(() => () => abortRef.current?.abort(), []);

  const load = useCallback(
    async (params: {
      start: string;
      end: string;
      interval: "1m" | "1d";
      compareCode?: string;
      rangeKey?: string;
    }) => {
      // 新请求 aborts 旧请求；序号守卫丢弃过期响应
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const mySeq = ++seqRef.current;
      const isStale = () => mySeq !== seqRef.current;

      setPending(true);
      setError(null);
      try {
        const q = new URLSearchParams({ type, code, interval: params.interval });
        if (params.interval === "1d") {
          q.set("start", params.start);
          q.set("end", params.end);
        }
        const res = await fetch(`/api/kline?${q.toString()}`, { signal: controller.signal });
        const data = (await res.json()) as KlineResult & { error?: string };
        if (isStale()) return;
        if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
        setKline(data);
        // 代码审查修复：调用方显式传入预设 key（此前按 start 日期反推，
        // 只有 1D/3M 能命中，1W/1M/6M/1Y 点击后高亮丢失）
        setRangeKey(
          params.rangeKey ??
            (params.interval === "1m"
              ? "1D"
              : params.start === shiftDays(beijingToday(), -90)
                ? "3M"
                : "custom"),
        );
        setPhases(data.interval === "1d" ? detectPhases(data.candles) : []);
        if (params.compareCode) {
          const cq = new URLSearchParams({
            type,
            code: params.compareCode,
            interval: "1d",
            start: params.start,
            end: params.end,
          });
          const cres = await fetch(`/api/kline?${cq.toString()}`, { signal: controller.signal });
          const cdata = (await cres.json()) as KlineResult & { error?: string };
          if (isStale()) return;
          if (cres.ok && cdata.candles?.length) {
            setCompare({ code: params.compareCode, candles: cdata.candles });
          } else {
            setCompare(null);
            setError(`对比标的加载失败：${cdata.error ?? "无数据"}`);
          }
        } else {
          setCompare(null);
        }
      } catch (e) {
        if (controller.signal.aborted || isStale()) return; // abort 不算错误
        setError(e instanceof Error ? e.message : "加载失败");
      } finally {
        if (!isStale()) setPending(false);
      }
    },
    [type, code],
  );

  const applyPreset = useCallback(
    (p: (typeof PRESETS)[number]) => {
      const today = beijingToday();
      const start = p.interval === "1m" ? today : shiftDays(today, -p.days);
      setRangeKey(p.key);
      void load({ start, end: today, interval: p.interval, rangeKey: p.key });
    },
    [load],
  );

  const applyCustom = useCallback(() => {
    if (!custom.start || !custom.end) return;
    setRangeKey("custom");
    void load({ start: custom.start, end: custom.end, interval: "1d", rangeKey: "custom" });
  }, [custom, load]);

  const addCompare = useCallback(() => {
    const target = compareInput.trim().toUpperCase();
    if (!target || target === code) return;
    const today = beijingToday();
    const days = PRESETS.find((p) => p.key === rangeKey)?.days ?? 90;
    const start =
      rangeKey === "custom" && custom.start ? custom.start : shiftDays(today, -days);
    void load({ start, end: today, interval: "1d", compareCode: target, rangeKey });
  }, [compareInput, code, rangeKey, custom, load]);

  // ---------- ECharts option ----------
  const option = useMemo(() => {
    const candles = kline.candles;
    if (candles.length === 0) return null;
    const dates = candles.map((c) => c.date);
    const isMinute = kline.interval === "1m";
    const showCompare = Boolean(compare && compare.candles.length > 1);

    // 事件标记（仅日线）：日期落在区间内的"可能相关"新闻
    const eventPoints = isMinute
      ? []
      : Object.entries(events.byDate)
          .filter(([d]) => dates.includes(d))
          .map(([d, items]) => {
            const bar = candles.find((c) => c.date === d);
            return {
              coord: [d, bar?.close ?? 0] as [string, number],
              value: items.map((x) => x.title).slice(0, 2).join("\n"),
            };
          });

    const norm = (arr: Candle[]) => {
      const base = arr[0]?.close || 1;
      return arr.map((c) => Math.round((c.close / base - 1) * 100 * 100) / 100);
    };

    const series: Record<string, unknown>[] = [];
    let grid: Record<string, number>[];
    let xAxis: Record<string, unknown>[];
    let yAxis: Record<string, unknown>[];

    if (showCompare && compare) {
      // 对比模式：归一化收益率曲线（%）
      grid = [{ left: 60, right: 20, top: 36, bottom: 50 }];
      xAxis = [
        {
          type: "category",
          data: dates,
          boundaryGap: false,
          axisLabel: { fontSize: 10 },
        },
      ];
      yAxis = [
        {
          type: "value",
          axisLabel: { formatter: "{value}%" },
          splitLine: { lineStyle: { color: "#f4f4f5" } },
        },
      ];
      const cmpNorm = norm(compare.candles);
      const cmpMap = new Map(
        compare.candles.map((c, i) => [c.date, cmpNorm[i]] as const),
      );
      series.push({
        name: `${code}（本标的）`,
        type: "line",
        data: norm(candles),
        showSymbol: false,
        lineStyle: { color: "#185FA5", width: 1.5 },
      });
      series.push({
        name: compare.code,
        type: "line",
        data: dates.map((d) => cmpMap.get(d) ?? null),
        showSymbol: false,
        lineStyle: { color: "#BA7517", width: 1.5 },
      });
    } else {
      const hasVolume = !isMinute && !kline.valueOnly;
      grid = hasVolume
        ? [
            { left: 60, right: 20, top: 30, height: 250 },
            { left: 60, right: 20, top: 316, height: 56 },
          ]
        : [{ left: 60, right: 20, top: 30, bottom: 50 }];
      xAxis = hasVolume
        ? [
            { type: "category", data: dates, boundaryGap: true, axisLabel: { show: false } },
            { type: "category", gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { fontSize: 10 } },
          ]
        : [{ type: "category", data: dates, boundaryGap: false, axisLabel: { fontSize: 10 } }];
      yAxis = hasVolume
        ? [
            { type: "value", scale: true },
            { type: "value", gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
          ]
        : [{ type: "value", scale: true }];

      const markArea = !isMinute && phases.length > 0
        ? {
            silent: true,
            data: phases.map((p) => [
              { xAxis: p.startDate },
              { xAxis: p.endDate, itemStyle: { color: phaseColor(p.direction) } },
            ]),
          }
        : undefined;
      const markPoint = eventPoints.length > 0
        ? {
            symbol: "circle",
            symbolSize: 8,
            itemStyle: { color: "#ffffff", borderColor: "#A32D2D", borderWidth: 2 },
            label: { show: false },
            data: eventPoints,
          }
        : undefined;

      if (kline.valueOnly) {
        series.push({
          name: valueLabel,
          type: "line",
          data: candles.map((c) => c.close),
          showSymbol: false,
          lineStyle: { color: "#185FA5", width: 1.5 },
          areaStyle: { color: "rgba(24,95,165,0.06)" },
          markArea,
          markPoint,
        });
      } else {
        series.push({
          name: valueLabel,
          type: "candlestick",
          data: candles.map((c) => [c.open, c.close, c.low, c.high]),
          itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
          markArea,
          markPoint,
        });
        if (hasVolume) {
          series.push({
            name: "成交量",
            type: "bar",
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: candles.map((c) => c.volume ?? 0),
            itemStyle: {
              color: (p: { dataIndex: number }) =>
                candles[p.dataIndex].close >= candles[p.dataIndex].open ? UP : DOWN,
              opacity: 0.5,
            },
          });
        }
      }
    }

    return {
      animation: false,
      grid,
      xAxis,
      yAxis,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        confine: true,
      },
      legend: showCompare ? { top: 0, textStyle: { fontSize: 11 } } : undefined,
      series,
    };
  }, [kline, phases, events, compare, code, valueLabel]);

  // 渲染主图（数据或 option 变化后）
  useEffect(() => {
    let cancelled = false;
    const el = chartRef.current;
    if (!el) return;
    import("echarts").then((echarts) => {
      if (cancelled) return;
      type ChartLike = {
        setOption: (o: unknown, opts?: { notMerge?: boolean }) => void;
        clear: () => void;
        resize?: () => void;
      };
      const inst =
        (echarts.getInstanceByDom(el) as ChartLike | undefined) ??
        (echarts.init(el) as unknown as ChartLike);
      chartInstRef.current = inst;
      if (option) {
        inst.setOption(option, { notMerge: true });
        setChartReady(true);
      } else {
        inst.clear();
      }
      // CR4（P3）：窗口/侧栏尺寸变化后画布重排（此前无 resize 监听，会留白/溢出）
      const onResize = () => inst.resize?.();
      window.addEventListener("resize", onResize);
      instOnResizeRef.current = onResize;
    });
    return () => {
      cancelled = true;
      if (instOnResizeRef.current) {
        window.removeEventListener("resize", instOnResizeRef.current);
        instOnResizeRef.current = null;
      }
      // 代码审查修复：卸载时释放 ECharts 实例（此前只置 cancelled，
      // 离开详情页/重复渲染会泄漏实例与画布）
      const inst = chartInstRef.current as { dispose?: () => void } | null;
      try {
        inst?.dispose?.();
      } catch {
        // 已释放
      }
      chartInstRef.current = null;
    };
  }, [option]);

  const pctClass = (v: number) =>
    v > 0 ? "text-red-600" : v < 0 ? "text-green-600" : "text-zinc-500";
  const pctText = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

  const phaseEvents = (p: Phase): string[] => {
    const titles: string[] = [];
    for (const [d, items] of Object.entries(events.byDate)) {
      if (d >= p.startDate && d <= p.endDate) titles.push(...items.map((x) => x.title));
    }
    return titles;
  };

  return (
    <section className="mt-6">
      {/* ③ 主图区 */}
      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              onClick={() => applyPreset(p)}
              disabled={pending}
              className={`rounded px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                rangeKey === p.key
                  ? "bg-blue-600 text-white"
                  : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
              }`}
            >
              {p.label}
            </button>
          ))}
          <span className="ml-2 flex items-center gap-1 text-xs text-zinc-500">
            <input
              type="date"
              value={custom.start}
              onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value }))}
              className="rounded border border-zinc-200 px-1.5 py-1"
            />
            <span>~</span>
            <input
              type="date"
              value={custom.end}
              onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value }))}
              className="rounded border border-zinc-200 px-1.5 py-1"
            />
            <button
              onClick={applyCustom}
              disabled={pending || !custom.start || !custom.end}
              className="rounded bg-zinc-800 px-2 py-1 text-white disabled:opacity-50"
            >
              应用
            </button>
          </span>
          <span className="ml-auto flex items-center gap-1 text-xs text-zinc-500">
            <input
              value={compareInput}
              onChange={(e) => setCompareInput(e.target.value)}
              placeholder="对比代码"
              className="w-24 rounded border border-zinc-200 px-1.5 py-1"
            />
            <button
              onClick={addCompare}
              disabled={pending || !compareInput.trim()}
              className="rounded border border-zinc-300 px-2 py-1 hover:bg-zinc-50 disabled:opacity-50"
            >
              叠加对比
            </button>
            {compare && (
              <button
                onClick={() => setCompare(null)}
                className="rounded border border-zinc-300 px-2 py-1 hover:bg-zinc-50"
              >
                移除 {compare.code}
              </button>
            )}
          </span>
        </div>

        <div className="relative mt-3">
          <div ref={chartRef} className="h-[400px] w-full" />
          {(pending || (!chartReady && kline.candles.length > 0)) && (
            <div className="absolute inset-0 flex items-center justify-center bg-white/70 text-sm text-zinc-500">
              {pending ? "图表数据加载中…" : "图表渲染中…"}
            </div>
          )}
          {kline.candles.length === 0 && !pending && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-zinc-400">
              {error ?? "暂无行情数据"}
            </div>
          )}
        </div>

        <div className="mt-2 flex flex-wrap items-center justify-between gap-1 text-xs text-zinc-400">
          <span>
            数据来源：{kline.source}
            {kline.valueOnly ? "（该品种仅收盘值序列）" : ""}
            {kline.interval === "1d" && kline.cachedDays > 0 && kline.fetchedDays > 0
              ? ` · 命中缓存 ${kline.cachedDays} 天 / 增量拉取 ${kline.fetchedDays} 天`
              : ""}
          </span>
          {kline.note && <span>备注：{kline.note}</span>}
        </div>
        {error && kline.candles.length > 0 && (
          <p className="mt-1 text-xs text-red-600">{error}</p>
        )}
      </div>

      {/* ④ 变化解读区 */}
      <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-4">
        <h2 className="text-sm font-medium text-zinc-800">
          变化解读（所选区间 {phases.length} 个阶段）
        </h2>
        {events.degraded && (
          <p className="mt-1 text-xs text-amber-600">事件标注不可用：{events.note}</p>
        )}
        {kline.interval === "1m" ? (
          <p className="mt-2 text-xs text-zinc-400">1D 分钟线不参与阶段划分。</p>
        ) : phases.length === 0 ? (
          <p className="mt-2 text-xs text-zinc-400">暂无阶段数据。</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead>
                <tr className="whitespace-nowrap text-zinc-400">
                  <th className="py-1.5 pr-4 font-normal">时段</th>
                  <th className="py-1.5 pr-4 font-normal">阶段</th>
                  <th className="py-1.5 pr-4 text-right font-normal">幅度</th>
                  <th className="py-1.5 pr-4 text-right font-normal">时长（交易日）</th>
                  <th className="w-full py-1.5 font-normal">可能相关事件（非因果断言）</th>
                </tr>
              </thead>
              <tbody>
                {phases.map((p, i) => {
                  const attr = phaseAttributionText(phaseEvents(p));
                  const sameYear = p.startDate.slice(0, 4) === p.endDate.slice(0, 4);
                  const rangeText = sameYear
                    ? `${p.startDate.slice(5)} → ${p.endDate.slice(5)}`
                    : `${p.startDate} → ${p.endDate}`;
                  return (
                    <tr
                      key={`${p.startDate}-${i}`}
                      className="border-t border-zinc-100 align-top"
                    >
                      <td
                        className="whitespace-nowrap py-2 pr-4 tabular-nums text-zinc-700"
                        title={`${p.startDate} → ${p.endDate}`}
                      >
                        {rangeText}
                      </td>
                      <td className="py-2 pr-4">
                        <span
                          className="inline-block whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium leading-5"
                          style={{
                            color:
                              p.direction === "up"
                                ? UP
                                : p.direction === "down"
                                  ? DOWN
                                  : "#5F5E5A",
                            background: phaseColor(p.direction),
                          }}
                        >
                          {p.label}
                        </span>
                      </td>
                      <td
                        className={`whitespace-nowrap py-2 pr-4 text-right font-medium tabular-nums ${pctClass(p.changePct)}`}
                      >
                        {pctText(p.changePct)}
                      </td>
                      <td className="whitespace-nowrap py-2 pr-4 text-right tabular-nums text-zinc-700">
                        {p.tradingDays} 天
                      </td>
                      <td className="py-2 text-zinc-500">
                        {attr ? (
                          <p
                            className="max-w-[460px] leading-5 line-clamp-2"
                            title={attr}
                          >
                            {attr}
                          </p>
                        ) : (
                          <span className="text-zinc-300">——</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-[11px] text-zinc-400">
          阶段由摆动点算法自动划分（反转阈值 4%）；事件按日期挂接当日新闻，仅代表时间上的相关性，不构成因果判断。
        </p>
      </div>
    </section>
  );
}
