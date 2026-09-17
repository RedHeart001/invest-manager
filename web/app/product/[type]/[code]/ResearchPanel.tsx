"use client";

// 深度研报面板（P5 / M5）：触发深度研究 → 轮询状态 → 渲染研报视图
// （评级徽章 / 分析师观点卡 / 多空辩论 / 风控结论 / 降级标注，R11+R12 话语一致）

import { useCallback, useEffect, useRef, useState } from "react";

// 注意：必须从零依赖模块导入——ResearchPanel 是客户端组件（"use client"），
// 而 @/lib/research 会牵连 prisma（服务端专属），打进客户端包会构建失败。
import { isStaleRunning } from "@/lib/research-stale";

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
  /** CR5-3：/api/research 已返回该字段，用于判"running 是否已陈旧" */
  updatedAt?: string;
};

const RATING_STYLE: Record<string, string> = {
  乐观: "bg-emerald-50 text-emerald-700 border-emerald-200",
  中性: "bg-zinc-100 text-zinc-600 border-zinc-200",
  谨慎: "bg-amber-50 text-amber-700 border-amber-200",
  悲观: "bg-red-50 text-red-700 border-red-200",
};

// CR4（P2-6）：轮询上限（10s × 60 ≈ 10 分钟），防 data-service 内存任务表因重启
// 丢失后 running 行永不结束导致前端无限轮询。
const POLL_LIMIT = 60;

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
  const pollCountRef = useRef(0);
  const cancelledRef = useRef(false);

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

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // CR4（P2-6）：轮询加次数上限（10s × 60 ≈ 10 分钟），防止 data-service 任务表
  // 因重启丢失后 running 行永不结束导致前端无限轮询。
  const beginPolling = useCallback(() => {
    if (pollRef.current) return;
    pollCountRef.current = 0;
    pollRef.current = setInterval(async () => {
      if (cancelledRef.current) return;
      pollCountRef.current += 1;
      if (pollCountRef.current >= POLL_LIMIT) {
        stopPolling();
        setError("研究状态查询超时（约 10 分钟），请刷新页面查看最新状态");
        return;
      }
      const latest = await fetchOnce();
      if (cancelledRef.current) return;
      if (latest && latest.status !== "running") stopPolling();
      // CR5-3：陈旧 running（执行方疑似重启）无再轮询的价值——已给出重发入口，
      // 停轮询避免继续每 10s 空转到 POLL_LIMIT。
      else if (latest?.status === "running" && isStaleRunning(latest)) stopPolling();
    }, 10_000);
  }, [fetchOnce, stopPolling]);

  useEffect(() => {
    // CR4（P2-8）：组件可能在首次 fetch 期间卸载——此前 cleanup 先跑（pollRef 尚为
    // null），随后 async 继续 setInterval 再无人清理，每 10s 轮询直到标签页关闭。
    // 加 cancelled 标志，await 后设置 interval 前检查。
    cancelledRef.current = false;
    void (async () => {
      const r = await fetchOnce();
      if (cancelledRef.current) return;
      setLoaded(true);
      if (r?.status === "running") beginPolling();
    })();
    return () => {
      cancelledRef.current = true;
      stopPolling();
    };
  }, [fetchOnce, beginPolling, stopPolling]);

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
      if (cancelledRef.current) return; // CR4：POST await 期间卸载则不继续设轮询/状态
      if (body.report) setReport(body.report);
      if (body.status === "running") {
        setReport((prev) => prev ?? { status: "running" });
        beginPolling();
      } else if (body.status === "rejected" || body.error) {
        setError(body.reason ?? body.error ?? "未能启动");
      }
    } catch (e) {
      if (!cancelledRef.current) setError(e instanceof Error ? e.message : "触发失败");
    } finally {
      if (!cancelledRef.current) setTriggering(false);
    }
  }, [type, code, name, beginPolling]);

  const full = report?.fullReport ?? null;
  const meta = full?.meta ?? null;

  // CR5-3（2026-09-17 review）：data-service 任务表是内存态，执行中重启会丢任务与
  // 完成回调 → 库中行永久 running，而 UI 的 running 分支没有出口（无重试按钮），
  // 用户被卡死。复用后端已导出的 STALE_RUNNING_MS 判定：陈旧的 running 落入
  // 下方「起始态」分支（复用既有触发按钮），阈值一过轮询 re-render 即自动切换。
  const staleRunning = report ? isStaleRunning(report) : false;

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
      ) : report?.status === "running" && !staleRunning ? (
        <div className="mt-4">
          <p className="flex items-center gap-2 text-sm text-zinc-500">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
            深度研究执行中（多角色分析 + 辩论，约 2~5 分钟）…完成后本页自动更新
          </p>
        </div>
      ) : report?.status === "done" ? (
        // CR4（P3）：done 但 fullReport 缺失（超 200KB 被丢弃，仅存 summary/rating）时，
        // 此前会落到下方起始态显示"启动深度分析"，与顶部评级徽章矛盾。改为渲染摘要。
        <div className="mt-4 space-y-3">
          {report.summary && (
            <p className="rounded-lg bg-zinc-50 p-3 text-sm leading-relaxed text-zinc-700">
              {report.summary}
            </p>
          )}
          <p className="text-xs text-zinc-400">
            完整研报内容过大（超过存储上限）已省略，此处仅保留评级与结论摘要。
          </p>
        </div>
      ) : (
        <div className="mt-4 text-center">
          {/* CR5-3：陈旧 running 落入本分支——显式说明并给出重新发起入口 */}
          {staleRunning && (
            <p className="mb-3 text-xs text-amber-600">
              研究任务疑似中断（执行方可能已重启），可重新发起。
            </p>
          )}
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
