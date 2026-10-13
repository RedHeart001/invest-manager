"use client";

// CR9-92（OPT-3 第一批 1a）：详情页第七区「当日实时行情条」＝现价＋涨跌幅＋当日分时＋最后更新时间。
// 位置在 ② 现状区与 ③④ 主图区之间（`docs/PLAN.md:170`；六区→七区见 `:178`）。
//
// 四条行为规则落在这里（`PLAN.md:171`），每条都只出现一次、且都能被单元测点名：
// ① 有当日数据才显示，否则**整块不渲染**（`stripVisible`＝ds 那一位 `hasTodayData`）；
// ② 时间档位里没有「当日」这一档（本组件不提供档位，`ProductCharts` 的 1D 档由第二批撤）；
// ③ 拉不到就显示**最后已知值＋更新时间**，不空白、不假装（`mergeTick`＋`isStale`）；
// ④ 页面不可见／非交易时段不请求（`shouldPoll`，粗判据的边界写在那个函数上）。

import { useCallback, useEffect, useRef, useState } from "react";

import { priceWithCurrency } from "@/lib/currency";
import { quoteClockText } from "@/lib/market-clock";
import {
  PRICE_POLL_MS,
  REALTIME_TEXT,
  displayPrice,
  isStale,
  lastUpdateStamp,
  mergeTick,
  partsForTick,
  shouldPoll,
  sparkPath,
  stripVisible,
  type RealtimeResponse,
} from "@/lib/realtime";

const SPARK_W = 240;
const SPARK_H = 40;

export default function RealtimeStrip({
  type,
  code,
  valueDecimals = 2,
}: {
  type: string;
  code: string;
  valueDecimals?: number;
}) {
  const [shown, setShown] = useState<RealtimeResponse | null>(null);
  const [failCount, setFailCount] = useState(0);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const tickRef = useRef(0);
  const lastOkRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);
  // 迟到的响应不许覆盖新的那一发（与 `ProductCharts.tsx:99-103` 同一条 `seqRef` 守卫）
  const seqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const poll = useCallback(async () => {
    if (inFlightRef.current) return; // 12s 预算 > 10s 一跳 ⇒ 会重叠，宁可跳过这一跳也不叠加请求
    if (!shouldPoll(type, Date.now())) return; // 规则④：时段与可见性都不对就不发
    inFlightRef.current = true;
    const seq = ++seqRef.current;
    const parts = partsForTick(tickRef.current);
    try {
      const res = await fetch(
        `/api/realtime?type=${encodeURIComponent(type)}&code=${encodeURIComponent(code)}&parts=${parts}`,
        { signal: abortRef.current?.signal, cache: "no-store" },
      );
      const body = (await res.json()) as RealtimeResponse & { error?: string };
      if (!res.ok) throw new Error(body.error ?? `实时条取数失败（HTTP ${res.status}）`);
      if (seq !== seqRef.current) return;
      setShown((prev) => mergeTick(prev, body));
      lastOkRef.current = Date.now();
      setFailCount(0);
      setNowMs(Date.now());
    } catch {
      if (seq === seqRef.current) setFailCount((n) => n + 1);
    } finally {
      inFlightRef.current = false;
      tickRef.current += 1;
    }
  }, [type, code]);

  useEffect(() => {
    abortRef.current = new AbortController();
    tickRef.current = 0;
    void poll();
    const timer = setInterval(() => void poll(), PRICE_POLL_MS);
    // 从"隐藏"回到"可见"的那一刻补一发：这一跳本来就是新数据，不把它拖到下一个 10s
    const onVisible = () => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      abortRef.current?.abort();
    };
  }, [poll]);

  // 规则①：没有当日数据就整块不出现——不留一个空盒子，也不留"点了看到别的数据"的入口。
  // 这里多写一次 `=== null` 是必要的：TS 不会因为辅助函数返回 false 就收窄可空性。
  const data = shown;
  if (data === null || !stripVisible(data)) return null;
  const price = displayPrice(data);
  if (price === null) return null;

  const stamp = lastUpdateStamp(data);
  const stale = isStale(lastOkRef.current, nowMs, failCount);
  const verdict = data.verifyVerdict;
  const changePct = data.price?.changePct ?? null;
  const path = sparkPath(data.intraday?.points ?? [], SPARK_W, SPARK_H);
  const clock = quoteClockText(type, data.price?.timestamp);
  const verdictText =
    verdict === "diverged" ? (data.note ?? REALTIME_TEXT.diverged) : verdict === "agree" ? REALTIME_TEXT.agree : REALTIME_TEXT.noSecondSource;

  return (
    <section
      className="mt-5 rounded-xl border border-zinc-200 bg-white p-4"
      data-testid="realtime-strip"
      data-verdict={verdict}
      data-degraded={String(data.degraded)}
      data-stale={String(stale)}
      data-parts={data.parts.join(",")}
      data-intraday-date={data.intraday?.date ?? ""}
      data-sources={data.sources
        .filter((s) => s.ok)
        .map((s) => `${s.kind}:${s.source}`)
        .join(",")}
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="text-xs font-medium text-zinc-500">{REALTIME_TEXT.heading}</span>
        <span className="text-2xl font-bold tabular-nums">
          {priceWithCurrency(price.toFixed(valueDecimals), data.price?.currency)}
        </span>
        {changePct != null && (
          <span className={`text-sm font-medium tabular-nums ${changePct >= 0 ? "text-red-600" : "text-green-600"}`}>
            {changePct >= 0 ? "+" : ""}
            {changePct.toFixed(2)}%
          </span>
        )}
        <span className="ml-auto text-xs text-zinc-400">
          来源：{data.price?.source ?? "--"}
          {clock ? ` · ${clock}` : ""} ·{" "}
          {stamp ? (stale ? REALTIME_TEXT.stale(stamp) : REALTIME_TEXT.lastUpdate(stamp)) : "时间未知"}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {path && (
          <svg
            viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
            className="h-10 w-60"
            role="img"
            aria-label={`${REALTIME_TEXT.heading}曲线`}
            data-testid="realtime-spark"
          >
            <path d={path} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-blue-600" />
          </svg>
        )}
        <span
          data-testid="realtime-verdict"
          className={`text-xs ${
            verdict === "diverged"
              ? "text-amber-600"
              : verdict === "no_second_source"
                ? "italic text-zinc-400"
                : "text-zinc-500"
          }`}
        >
          {verdictText}
        </span>
      </div>
    </section>
  );
}
