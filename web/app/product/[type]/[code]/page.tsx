import { notFound } from "next/navigation";
import type { EChartsOption } from "echarts";

import Breadcrumbs from "@/app/components/Breadcrumbs";
import EChart from "@/app/components/EChart";
import WatchButton from "@/app/components/WatchButton";
import ProductCharts from "./ProductCharts";
import ResearchPanel from "./ResearchPanel";
import { dsGet, type Quote } from "@/lib/data-service";
import { fetchEvents, narrowByDates, pickEventDates } from "@/lib/events";
import { getKlineRange, normalizeRange, type KlineResult } from "@/lib/kline";
import { detectPhases } from "@/lib/phases";
import { buildProfile, isExchangeTradedFund, type QuoteEnriched } from "@/lib/profile";
import { prisma } from "@/lib/prisma";
import { parseTags } from "@/lib/score";

const TYPE_LABEL: Record<string, string> = {
  stock: "股票",
  fund: "基金",
  bond: "债券",
  crypto: "虚拟币",
  hk: "港股",
  us: "美股",
};

function fmtVolume(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "--";
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)} 亿`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(2)} 万`;
  return v.toFixed(0);
}

function fmtPrice(v: number | null | undefined, decimals: number): string {
  if (v == null || !Number.isFinite(v)) return "--";
  return v.toFixed(decimals);
}

type HoldingsResp = {
  code: string;
  degraded: boolean;
  note: string | null;
  quarter: string | null;
  holdings: { code: string; name: string; weight: number | null }[];
  source?: string;
};

type YieldResp = {
  degraded: boolean;
  note: string | null;
  curve: { date: string; values: Record<string, number> }[];
  source?: string;
};

export default async function ProductPage({
  params,
}: {
  params: Promise<{ type: string; code: string }>;
}) {
  const { type, code } = await params;

  const product = await prisma.product.findUnique({
    where: { type_code: { type, code } },
  });
  if (!product) notFound();
  const tags = parseTags(product.tags);

  // ② 现状区：实时行情（含 P2 扩展字段，失败优雅降级）
  // 代码审查修复（性能）：五路独立取数此前**串行 await**，各 15~45s 超时会在
  // TTFB 上叠加；改为并行发起、各自保留降级处理（R10 语义不变）。
  const otcFund = type === "fund" && !isExchangeTradedFund(code);
  const valueDecimals = type === "fund" ? 4 : 2;
  const valueLabel = otcFund ? "单位净值" : "价格";
  const range = normalizeRange(null, null);
  const rangeOk = "start" in range;

  const [quoteRes, klineRes, eventsRes, holdingsRes, yieldRes] = await Promise.allSettled([
    dsGet<Quote>("/quote", { type, code }, 15_000),
    rangeOk ? getKlineRange(type, code, range.start, range.end) : Promise.reject(new Error("非法区间")),
    fetchEvents(type, code),
    otcFund ? dsGet<HoldingsResp>("/fund/holdings", { code }, 30_000) : Promise.resolve(null),
    type === "bond"
      ? dsGet<YieldResp>("/bond/yieldcurve", { days: "90" }, 30_000)
      : Promise.resolve(null),
  ]);

  let quote: Quote | null = null;
  let quoteError: string | null = null;
  if (quoteRes.status === "fulfilled") {
    quote = quoteRes.value;
  } else {
    quoteError = quoteRes.reason instanceof Error ? quoteRes.reason.message : "行情获取失败";
  }

  let kline: KlineResult | null = null;
  let klineError: string | null = null;
  if (klineRes.status === "fulfilled") {
    kline = klineRes.value;
  } else if (rangeOk) {
    klineError = klineRes.reason instanceof Error ? klineRes.reason.message : "K线获取失败";
  }
  const emptyKline: KlineResult = {
    type,
    code,
    interval: "1d",
    valueOnly: false,
    source: "--",
    candles: [],
    phases: [],
    cachedDays: 0,
    fetchedDays: 0,
    note: klineError,
  };
  const effectiveKline = kline ?? emptyKline;
  const phases = kline && kline.candles.length > 1 ? detectPhases(kline.candles) : [];

  // 事件标注（R11 轻量归因）
  // CR-10：只保留"阶段转折点 + 大波动日"的事件（此前全量按日期返回，
  // pickEventDates 未接线）。无 K 线时保持全量（降级路径）。
  const rawEvents =
    eventsRes.status === "fulfilled"
      ? eventsRes.value
      : { byDate: {}, note: eventsRes.reason instanceof Error ? eventsRes.reason.message : "事件获取失败", degraded: true };
  const events: typeof rawEvents =
    effectiveKline.candles.length > 1
      ? {
          ...rawEvents,
          byDate: narrowByDates(
            rawEvents.byDate,
            pickEventDates(
              effectiveKline.candles.map((c) => ({ date: c.date, close: c.close })),
              phases.map((p) => p.endDate),
            ),
          ),
        }
      : rawEvents;

  // ⑤ 明细区按类型槽位
  let holdings: HoldingsResp | null = null;
  let holdingsError: string | null = null;
  if (otcFund) {
    if (holdingsRes.status === "fulfilled") {
      holdings = holdingsRes.value;
    } else {
      holdingsError = holdingsRes.reason instanceof Error ? holdingsRes.reason.message : "持仓获取失败";
    }
  }
  let yieldData: YieldResp | null = null;
  if (type === "bond") {
    if (yieldRes.status === "fulfilled" && yieldRes.value) {
      yieldData = yieldRes.value;
    } else {
      yieldData = { degraded: true, note: "收益率曲线获取失败", curve: [] };
    }
  }

  const profile = buildProfile(
    { type, name: product.name, code, exchange: product.exchange, tags },
    (quote as QuoteEnriched | null) ?? null,
  );

  // 指标卡：区间高低（来自初始 3M K线）+ 行情扩展字段
  const closes = effectiveKline.candles;
  const rangeHigh = closes.length ? Math.max(...closes.map((c) => c.high)) : null;
  const rangeLow = closes.length ? Math.min(...closes.map((c) => c.low)) : null;

  const stats: { label: string; value: string }[] = [];
  if (quote?.open != null) stats.push({ label: "今开", value: fmtPrice(quote.open, valueDecimals) });
  if (quote?.prevClose != null) stats.push({ label: "昨收", value: fmtPrice(quote.prevClose, valueDecimals) });
  if (quote?.high != null) stats.push({ label: "今日最高", value: fmtPrice(quote.high, valueDecimals) });
  if (quote?.low != null) stats.push({ label: "今日最低", value: fmtPrice(quote.low, valueDecimals) });
  if (rangeHigh != null) stats.push({ label: "区间最高(3M)", value: fmtPrice(rangeHigh, valueDecimals) });
  if (rangeLow != null) stats.push({ label: "区间最低(3M)", value: fmtPrice(rangeLow, valueDecimals) });
  if (quote?.volume != null) stats.push({ label: "成交量", value: fmtVolume(quote.volume) });
  if (quote?.turnover != null) stats.push({ label: "换手率", value: `${quote.turnover.toFixed(2)}%` });
  if (quote?.marketCap != null) {
    stats.push({
      label: "总市值",
      value: quote.marketCap >= 1e12 ? `${(quote.marketCap / 1e12).toFixed(2)} 万亿` : `${(quote.marketCap / 1e8).toFixed(0)} 亿`,
    });
  }
  if (quote?.peTtm != null) stats.push({ label: "PE(TTM)", value: quote.peTtm.toFixed(2) });
  if (quote?.pb != null) stats.push({ label: "市净率", value: quote.pb.toFixed(2) });
  if (quote?.marketCapRank != null) stats.push({ label: "市值排名", value: `#${quote.marketCapRank}` });

  // 明细区图表 option（SSR 构建，客户端渲染）
  const pieOption: EChartsOption | null = holdings?.holdings?.length
    ? {
        tooltip: { trigger: "item", formatter: "{b}: {d}%" },
        legend: {
          orient: "vertical" as const,
          right: 0,
          top: "middle" as const,
          textStyle: { fontSize: 10 },
        },
        series: [
          {
            type: "pie" as const,
            radius: ["32%", "62%"],
            center: ["36%", "50%"],
            data: holdings.holdings.map((h) => ({ name: h.name, value: h.weight ?? 0 })),
            label: { show: false },
          },
        ],
      }
    : null;

  const yieldOption: EChartsOption | null = yieldData?.curve?.length
    ? (() => {
        const dates = yieldData.curve.map((c) => c.date);
        const tenors = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"].filter(
          (t) => yieldData!.curve.some((c) => c.values[t] != null),
        );
        return {
          tooltip: { trigger: "axis" },
          legend: { top: 0, textStyle: { fontSize: 10 } },
          xAxis: { type: "category" as const, data: dates, axisLabel: { fontSize: 10 } },
          yAxis: { type: "value" as const, axisLabel: { formatter: "{value}%" } },
          series: tenors.map((t) => ({
            name: t,
            type: "line" as const,
            showSymbol: false,
            data: yieldData!.curve.map((c) => c.values[t] ?? null),
          })),
        };
      })()
    : null;

  const tableRows = [...closes].slice(-15).reverse();
  const changePct = quote?.changePct ?? null;

  return (
    <main className="mx-auto max-w-5xl px-6 py-8">
      <Breadcrumbs
        items={[
          { label: "首页", href: "/" },
          { label: "搜索", href: "/search" },
          { label: `${product.name}（${product.code}）` },
        ]}
      />

      {/* ① 身份区 */}
      <section className="mt-4">
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="text-2xl font-bold tracking-tight">{product.name}</h1>
          <span className="text-zinc-400">{product.code}</span>
          <span className="rounded bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500">
            {TYPE_LABEL[type] ?? type}
            {product.exchange ? ` · ${product.exchange}` : ""}
          </span>
          {/* G5：自选入口（Watchlist 加权来源） */}
          <span className="ml-auto">
            <WatchButton type={type} code={code} name={product.name} />
          </span>
        </div>
        {tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {tags.map((t) => (
              <span
                key={t}
                className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-600"
              >
                {t}
              </span>
            ))}
          </div>
        )}
        <p className="mt-2 text-sm text-zinc-600" data-testid="profile">
          {profile}
        </p>
      </section>

      {/* ② 现状区 */}
      <section className="mt-5 rounded-xl border border-zinc-200 bg-white p-5">
        {quote ? (
          <>
            <div className="flex flex-wrap items-baseline gap-4">
              <span className="text-4xl font-bold tabular-nums">
                {fmtPrice(quote.price, valueDecimals)}
              </span>
              {changePct != null && (
                <span
                  className={`text-base font-medium ${
                    changePct >= 0 ? "text-red-600" : "text-green-600"
                  }`}
                >
                  {changePct >= 0 ? "+" : ""}
                  {changePct.toFixed(2)}%
                </span>
              )}
              <span className="ml-auto text-xs text-zinc-400">
                来源：{quote.source}
                {quote.timestamp ? ` · ${quote.timestamp}` : ""}
              </span>
            </div>
            {stats.length > 0 && (
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
                {stats.map((s) => (
                  <div key={s.label} className="rounded-lg bg-zinc-50 px-3 py-2">
                    <p className="text-xs text-zinc-400">{s.label}</p>
                    <p className="mt-0.5 text-sm font-medium tabular-nums text-zinc-800">
                      {s.value}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-zinc-400">
            暂无实时行情{quoteError ? `（${quoteError}）` : ""}
          </p>
        )}
      </section>

      {/* ③④ 主图区 + 变化解读区 */}
      {kline ? (
        <ProductCharts
          key={`${type}:${code}`}
          type={type}
          code={code}
          initialKline={effectiveKline}
          initialPhases={phases}
          events={events}
          valueDecimals={valueDecimals}
          valueLabel={valueLabel}
        />
      ) : (
        <section className="mt-6 rounded-xl border border-dashed border-zinc-300 bg-white/50 p-8 text-center">
          <p className="text-sm text-zinc-500">
            图表数据不可用{klineError ? `（${klineError}）` : ""}
          </p>
          <p className="mt-1 text-xs text-zinc-400">
            该品种数据源暂不可达，已按 R12/R13 策略降级展示，不影响其余功能。
          </p>
        </section>
      )}

      {/* ⑤ 明细区（长页全展开，不折叠） */}
      <section className="mt-6 space-y-4">
        <h2 className="text-sm font-medium text-zinc-800">明细数据</h2>

        {tableRows.length > 0 && (
          <div className="rounded-xl border border-zinc-200 bg-white p-4">
            <h3 className="text-xs font-medium text-zinc-500">
              日线数据（最近 {tableRows.length} 条 / 来源：{effectiveKline.source}）
            </h3>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[520px] text-left text-xs">
                <thead>
                  <tr className="text-zinc-400">
                    <th className="py-1.5 pr-3 font-normal">日期</th>
                    <th className="py-1.5 pr-3 font-normal">开</th>
                    <th className="py-1.5 pr-3 font-normal">高</th>
                    <th className="py-1.5 pr-3 font-normal">低</th>
                    <th className="py-1.5 pr-3 font-normal">收</th>
                    <th className="py-1.5 font-normal">成交量</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((c) => (
                    <tr key={c.date} className="border-t border-zinc-100 tabular-nums">
                      <td className="py-1.5 pr-3 text-zinc-700">{c.date}</td>
                      <td className="py-1.5 pr-3 text-zinc-600">{fmtPrice(c.open, valueDecimals)}</td>
                      <td className="py-1.5 pr-3 text-zinc-600">{fmtPrice(c.high, valueDecimals)}</td>
                      <td className="py-1.5 pr-3 text-zinc-600">{fmtPrice(c.low, valueDecimals)}</td>
                      <td className="py-1.5 pr-3 font-medium text-zinc-800">{fmtPrice(c.close, valueDecimals)}</td>
                      <td className="py-1.5 text-zinc-500">{fmtVolume(c.volume)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {otcFund && (
          <div className="rounded-xl border border-zinc-200 bg-white p-4">
            <h3 className="text-xs font-medium text-zinc-500">
              资产配置 · 重仓持股
              {holdings?.quarter ? `（${holdings.quarter}）` : ""}
              {holdings?.source ? ` · 来源：${holdings.source}` : ""}
            </h3>
            {pieOption ? (
              <div className="mt-2 grid grid-cols-1 gap-4 lg:grid-cols-2">
                <EChart option={pieOption} height={260} />
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="text-zinc-400">
                      <th className="py-1.5 pr-3 font-normal">股票</th>
                      <th className="py-1.5 pr-3 font-normal">代码</th>
                      <th className="py-1.5 font-normal">占净值比例</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdings!.holdings.map((h) => (
                      <tr key={h.code} className="border-t border-zinc-100 tabular-nums">
                        <td className="py-1.5 pr-3 text-zinc-700">{h.name}</td>
                        <td className="py-1.5 pr-3 text-zinc-500">{h.code}</td>
                        <td className="py-1.5 text-zinc-700">
                          {h.weight != null ? `${h.weight.toFixed(2)}%` : "--"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-2 text-xs text-amber-600">
                持仓数据不可用（{holdings?.note ?? holdingsError ?? "该基金可能未披露股票持仓"}）
              </p>
            )}
          </div>
        )}

        {type === "bond" && (
          <div className="rounded-xl border border-zinc-200 bg-white p-4">
            <h3 className="text-xs font-medium text-zinc-500">
              国债收益率曲线（近 90 交易日）
              {yieldData?.source ? ` · 来源：${yieldData.source}` : ""}
            </h3>
            {yieldOption ? (
              <div className="mt-2">
                <EChart option={yieldOption} height={280} />
              </div>
            ) : (
              <p className="mt-2 text-xs text-amber-600">
                收益率曲线不可用（{yieldData?.note ?? "数据源缺失"}）
              </p>
            )}
          </div>
        )}
      </section>

      {/* ⑥ 深度分析入口（P5 / M5：多角色研报，与聊天 L2 工具同一链路） */}
      <ResearchPanel key={`${type}:${code}`} type={type} code={code} name={product.name} />

      <p className="mt-8 text-xs text-zinc-400">
        行情数据来自免费源，可能有延迟；阶段划分与事件标注仅代表时间上的相关性，可能相关而非因果；
        仅供参考，不构成投资建议。
      </p>
    </main>
  );
}
