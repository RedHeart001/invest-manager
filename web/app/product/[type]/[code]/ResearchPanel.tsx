"use client";

// 深度研报面板（P5 / M5）：触发深度研究 → 轮询状态 → 渲染研报视图
// （评级徽章 / 分析师观点卡 / 多空辩论 / 风控结论 / 降级标注，R11+R12 话语一致）

import { useCallback, useEffect, useRef, useState } from "react";

type FullReport = {
  ok?: boolean;
  rating?: string;
  summary?: string;
  analysts?: { role: string; view: string; points: string[] }[];
  debate?: { bull: string[]; bear: string[]; note?: string };
  risk?: string[];
  meta?: {
    llmCalls?: number;
    engine?: string;
    sources?: string[];
    degraded?: boolean;
    note?: string | null;
  };
};

type ReportRow = {
  status: "none" | "running" | "done" | "failed";
  rating?: string | null;
  summary?: string | null;
  fullReport?: FullReport | null;
  error?: string | null;
};

const RATING_STYLE: Record<string, string> = {
  乐观: "bg-emerald-50 text-emerald-700 border-emerald-200",
  中性: "bg-zinc-100 text-zinc-600 border-zinc-200",
  谨慎: "bg-amber-50 text-amber-700 border-amber-200",
  悲观: "bg-red-50 text-red-700 border-red-200",
};

export default function ResearchPanel({
  type,
  code,
  name,
}: {
  type: string;
  code: string;
  name: string;
}) {
  const [report, setReport] = useState<ReportRow | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchOnce = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/research?type=${encodeURIComponent(type)}&code=${encodeURIComponent(code)}`,
      );
      const body = (await res.json()) as ReportRow;
      setReport(body);
      return body;
    } catch {
      return null;
    }
  }, [type, code]);

  useEffect(() => {
    void (async () => {
      const r = await fetchOnce();
      setLoaded(true);
      // 若已在 running，自动开始轮询
      if (r?.status === "running") {
        pollRef.current = setInterval(async () => {
          const latest = await fetchOnce();
          if (latest && latest.status !== "running" && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }, 10_000);
      }
    })();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchOnce]);

  const trigger = useCallback(async () => {
    setTriggering(true);
    setError(null);
    try {
      const res = await fetch("/api/research/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, code, name }),
      });
      const body = (await res.json()) as {
        status?: string;
        reason?: string;
        error?: string;
        report?: ReportRow;
      };
      if (body.report) setReport(body.report);
      if (body.status === "running") {
        setReport((prev) => prev ?? { status: "running" });
        if (!pollRef.current) {
          pollRef.current = setInterval(async () => {
            const latest = await fetchOnce();
            if (latest && latest.status !== "running" && pollRef.current) {
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
          }, 10_000);
        }
      } else if (body.status === "rejected" || body.error) {
        setError(body.reason ?? body.error ?? "未能启动");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "触发失败");
    } finally {
      setTriggering(false);
    }
  }, [type, code, name, fetchOnce]);

  const full = report?.fullReport ?? null;
  const meta = full?.meta ?? null;

  return (
    <section id="research" className="mt-6 rounded-xl border border-zinc-200 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold tracking-tight">深度分析</h2>
        {report?.status === "done" && report.rating && (
          <span
            className={`rounded-full border px-3 py-1 text-xs font-medium ${
              RATING_STYLE[report.rating] ?? "bg-zinc-100 text-zinc-600 border-zinc-200"
            }`}
          >
            评级：{report.rating}
          </span>
        )}
      </div>

      {!loaded ? (
        <p className="mt-4 text-sm text-zinc-400">加载中…</p>
      ) : report?.status === "done" && full ? (
        <div className="mt-4 space-y-4">
          {report.summary && (
            <p className="rounded-lg bg-zinc-50 p-3 text-sm leading-relaxed text-zinc-700">
              {report.summary}
            </p>
          )}

          {(full.analysts ?? []).length > 0 && (
            <div>
              <p className="text-xs font-medium text-zinc-400">分析师观点</p>
              <div className="mt-2 grid gap-3 md:grid-cols-3">
                {(full.analysts ?? []).map((a) => (
                  <div key={a.role} className="rounded-lg border border-zinc-200 p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-zinc-700">{a.role}</span>
                      <span
                        className={`text-[11px] ${
                          a.view === "看多"
                            ? "text-emerald-600"
                            : a.view === "看空"
                              ? "text-red-500"
                              : "text-zinc-400"
                        }`}
                      >
                        {a.view}
                      </span>
                    </div>
                    <ul className="mt-1.5 list-disc space-y-1 pl-4 text-xs leading-relaxed text-zinc-600">
                      {(a.points ?? []).map((pt, i) => (
                        <li key={i}>{pt}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}

          {full.debate && ((full.debate.bull?.length ?? 0) > 0 || (full.debate.bear?.length ?? 0) > 0) && (
            <div>
              <p className="text-xs font-medium text-zinc-400">多空辩论</p>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3">
                  <p className="text-xs font-medium text-emerald-700">多方</p>
                  <ul className="mt-1.5 list-disc space-y-1 pl-4 text-xs leading-relaxed text-zinc-600">
                    {(full.debate.bull ?? []).map((x, i) => (
                      <li key={i}>{x}</li>
                    ))}
                  </ul>
                </div>
                <div className="rounded-lg border border-red-200 bg-red-50/50 p-3">
                  <p className="text-xs font-medium text-red-500">空方</p>
                  <ul className="mt-1.5 list-disc space-y-1 pl-4 text-xs leading-relaxed text-zinc-600">
                    {(full.debate.bear ?? []).map((x, i) => (
                      <li key={i}>{x}</li>
                    ))}
                  </ul>
                </div>
              </div>
              {full.debate.note && (
                <p className="mt-1.5 text-[11px] text-zinc-400">{full.debate.note}</p>
              )}
            </div>
          )}

          {(full.risk ?? []).length > 0 && (
            <div>
              <p className="text-xs font-medium text-zinc-400">风险提示</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-4 text-xs leading-relaxed text-zinc-600">
                {(full.risk ?? []).map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 pt-3 text-[11px] text-zinc-400">
            <span>引擎：{meta?.engine ?? "-"}</span>
            <span>·</span>
            <span>LLM 调用：{meta?.llmCalls ?? "-"} 次</span>
            <span>·</span>
            <span>数据源：{(meta?.sources ?? []).join(" / ") || "-"}</span>
            {meta?.degraded && (
              <span className="rounded bg-amber-50 px-2 py-0.5 text-amber-700">
                降级产出{meta.note ? `：${meta.note.slice(0, 60)}` : ""}
              </span>
            )}
          </div>
        </div>
      ) : report?.status === "running" ? (
        <div className="mt-4">
          <p className="flex items-center gap-2 text-sm text-zinc-500">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
            深度研究执行中（多角色分析 + 辩论，约 2~5 分钟）…完成后本页自动更新
          </p>
        </div>
      ) : (
        <div className="mt-4 text-center">
          {report?.status === "failed" && (
            <p className="mb-3 text-xs text-red-500">
              最近一次研究失败：{report.error ?? "unknown"}
            </p>
          )}
          <button
            onClick={() => void trigger()}
            disabled={triggering}
            className="rounded-lg bg-zinc-900 px-5 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
          >
            {triggering ? "提交中…" : "启动深度分析"}
          </button>
          <p className="mt-2 text-xs text-zinc-400">
            触发多角色深度研报：技术 / 基本面 / 新闻情绪分析师 + 多空辩论 + 评级（约 2~5 分钟，每日每标的限 1 次）
          </p>
        </div>
      )}

      {error && <p className="mt-3 text-xs text-red-500">{error}</p>}
    </section>
  );
}
