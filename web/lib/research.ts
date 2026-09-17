// 深度研报数据层（P5 / M5）：提交任务 + 回调落库 + 查询
// 产出落库统一模式：data-service 完成后回调 /api/research/ingest，由 BFF 落库

import { appendMessage } from "./chat";
import { beijingToday } from "./time";
import { prisma } from "./prisma";
import { dsPost } from "./data-service";
import { broadcast } from "./sse";

function dayStart(iso: string): Date {
  return new Date(`${iso}T00:00:00.000Z`);
}

function todayIso(): string {
  return beijingToday(); // B4：统一走公共 util
}

// CR4（2026-09-15 review）：running 行陈旧判定阈值——data-service 任务表为内存态，
// 超过该时长仍 running 视为执行方已丢失任务，允许重新提交（对齐任务 480s 超时 + 回调节拍）。
// CR5-3：常量与前端判定函数收敛到零依赖模块 research-stale.ts（单一来源，防阈值漂移）。
export { STALE_RUNNING_MS } from "./research-stale";
import { STALE_RUNNING_MS } from "./research-stale";

export type FullReport = {
  ok: boolean;
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
  error?: string;
};

export type ReportRow = {
  id: string;
  type: string;
  code: string;
  date: string;
  rating: string | null;
  summary: string | null;
  status: string;
  fullReport: FullReport | null;
  error: string | null;
  updatedAt: string;
};

function toRow(r: {
  id: string;
  type: string;
  code: string;
  date: Date;
  rating: string | null;
  summary: string | null;
  status: string;
  fullReport: string | null;
  error?: string | null;
  updatedAt: Date;
}): ReportRow {
  let full: FullReport | null = null;
  try {
    full = r.fullReport ? (JSON.parse(r.fullReport) as FullReport) : null;
  } catch {
    full = null;
  }
  return {
    id: r.id,
    type: r.type,
    code: r.code,
    date: r.date.toISOString().slice(0, 10),
    rating: r.rating,
    summary: r.summary,
    status: r.status,
    fullReport: full,
    error: r.error ?? null,
    updatedAt: r.updatedAt.toISOString(),
  };
}

export type StartResult =
  | { status: "running"; taskId?: string; reason?: string; report?: ReportRow }
  | { status: "done"; report: ReportRow }
  | { status: "rejected"; reason: string };

/** 提交深度研究（当日 done 直接复用；running 原样返回；否则调 data-service 建任务） */
// 代码审查修复：研报完成推送此前无会话归属——ChatUI 全局订阅并把卡片塞进
// **当前打开的会话**（跨会话串消息）。改为：启动时登记发起会话，完成时
// ① 把提示落库到该会话（切走再回来也能看到，兑现"同一会话推送"承诺）
// ② 广播携带 sessionIds，前端按当前会话过滤。
//
// C17（2026-09-13 第二轮 code review）：注册表必须挂 globalThis——
// dev HMR 重建模块作用域会重置模块级 Map，导致 start 时登记的 watcher 丢失、
// ingest 时取不到会话（定向推送静默失效）。
const WATCHERS_KEY = Symbol.for("invest-manager.research.watchers");
const researchWatchers: Map<string, Set<string>> = ((
  globalThis as unknown as Record<symbol, Map<string, Set<string>> | undefined>
)[WATCHERS_KEY] ??= new Map());

function watchResearch(type: string, code: string, sessionId?: string): void {
  if (!sessionId) return;
  const key = `${type}:${code}`;
  const set = researchWatchers.get(key) ?? new Set<string>();
  set.add(sessionId);
  researchWatchers.set(key, set);
}

function takeWatchers(type: string, code: string): string[] {
  const key = `${type}:${code}`;
  const out = [...(researchWatchers.get(key) ?? [])];
  researchWatchers.delete(key);
  return out;
}

export async function startResearch(
  type: string,
  code: string,
  name?: string,
  watcherSessionId?: string,
): Promise<StartResult> {
  const dateIso = todayIso();
  const existing = await prisma.researchReport.findUnique({
    where: { type_code_date: { type, code, date: dayStart(dateIso) } },
  });
  if (existing?.status === "done") {
    return { status: "done", report: toRow(existing) };
  }
  // CR4（2026-09-15 review）：data-service 任务表是内存态，任务执行中重启会
  // 丢失任务与完成回调 → 该行永久停在 running（整天无法重触发 + 前端无限轮询）。
  // running 且超阈值（对齐 RESEARCH_TASK_TIMEOUT_S 480s + 回调节拍）视为陈旧，
  // 标记 failed 并允许重新提交。
  if (existing?.status === "running") {
    const ageMs = Date.now() - new Date(existing.updatedAt).getTime();
    if (ageMs > STALE_RUNNING_MS) {
      await prisma.researchReport.update({
        where: { id: existing.id },
        data: { status: "failed", error: "研究任务超时（执行方可能已重启），可重新提交" },
      });
    } else {
      return { status: "running", reason: "研究任务执行中" };
    }
  }

  let ds: { taskId?: string; rejected?: string; todayDone?: boolean };
  try {
    ds = await dsPost<{ taskId?: string; rejected?: string; todayDone?: boolean }>(
      "/research/start",
      { type, code, name: name ?? code },
      30_000,
    );
  } catch (e) {
    // data-service 不可达：记录 failed，避免用户无限等待
    const row = await prisma.researchReport.upsert({
      where: { type_code_date: { type, code, date: dayStart(dateIso) } },
      create: {
        type,
        code,
        date: dayStart(dateIso),
        status: "failed",
        error: e instanceof Error ? e.message.slice(0, 300) : "data-service unreachable",
      },
      update: { status: "failed", error: e instanceof Error ? e.message.slice(0, 300) : "data-service unreachable" },
    });
    return { status: "rejected", reason: `研究任务提交失败：${row.error}` };
  }

  if (ds.rejected && ds.todayDone) {
    // 每日限 1 次：库中尚无 done 行（可能由另一实例完成），直接返回原因
    return { status: "rejected", reason: ds.rejected };
  }
  if (ds.rejected) {
    // CR4（P3）：被拒但非"当日已完成"（如并发去重：另一实例正在执行）也登记
    // 发起会话——否则 chat 仍提示"完成后在会话推送"却推送不到（C8 承诺落空）。
    watchResearch(type, code, watcherSessionId);
    return { status: "running", reason: ds.rejected };
  }

  const row = await prisma.researchReport.upsert({
    where: { type_code_date: { type, code, date: dayStart(dateIso) } },
    create: { type, code, date: dayStart(dateIso), status: "running" },
    update: { status: "running", error: null },
  });
  // 任务真正进入 running 才登记发起会话（完成后定向推送）
  watchResearch(type, code, watcherSessionId);
  return { status: "running", taskId: ds.taskId, report: toRow(row) };
}

export type IngestPayload = {
  type: string;
  code: string;
  date?: string;
  report?: FullReport;
  error?: string;
};

/** data-service 完成回调：落库 + SSE 广播 */
export async function ingestResearch(payload: IngestPayload): Promise<ReportRow> {
  const dateIso = payload.date && /^\d{4}-\d{2}-\d{2}$/.test(payload.date) ? payload.date : todayIso();
  const report = payload.report;
  // JSON 截断保护（2026-09-13 code review）：盲目 slice 会把 JSON 切成非法文本，
  // parse 失败后 UI 只能回落到"无研报"。改为超限时丢弃 fullReport（保留 summary/rating）。
  let fullReportJson: string | null = null;
  if (report) {
    const json = JSON.stringify(report);
    fullReportJson = json.length <= 200_000 ? json : null;
  }
  const data = {
    status: report?.ok ? "done" : "failed",
    rating: report?.ok ? (report.rating ?? "中性") : null,
    summary: report?.ok ? (report.summary ?? "").slice(0, 500) : null,
    fullReport: fullReportJson,
    error: report?.ok ? null : (payload.error ?? report?.error ?? "研究失败").slice(0, 300),
  };
  const row = await prisma.researchReport.upsert({
    where: { type_code_date: { type: payload.type, code: payload.code, date: dayStart(dateIso) } },
    create: {
      type: payload.type,
      code: payload.code,
      date: dayStart(dateIso),
      status: data.status,
      rating: data.rating,
      summary: data.summary,
      fullReport: data.fullReport,
      error: data.error,
    },
    update: data,
  });

  if (data.status === "done") {
    // 代码审查修复：定向推送（含会话归属）
    const sessionIds = takeWatchers(payload.type, payload.code);
    const text = `📄 深度研究报告已完成：**${payload.code}** 评级「${data.rating ?? "中性"}」\n\n${data.summary ?? ""}\n\n[查看完整研报 →](/product/${payload.type}/${payload.code}#research)`;
    // ① 提示落库到发起会话：切走再回来也能看到（PLAN"任务完成后在同一会话推送"）
    for (const sid of sessionIds) {
      try {
        await appendMessage(sid, "assistant", text);
      } catch (e) {
        console.error("[research] 会话推送落库失败:", e instanceof Error ? e.message : e);
      }
    }
    // ② 广播带会话归属，前端按当前会话过滤
    broadcast("research", {
      type: payload.type,
      code: payload.code,
      rating: data.rating,
      summary: data.summary,
      sessionIds,
    });
  } else {
    // 失败路径同样消费 watcher（2026-09-13 code review）：此前只在 done 时清理，
    // 失败/长期未完成的任务会让 Map 无界增长，且发起会话收不到任何反馈。
    const sessionIds = takeWatchers(payload.type, payload.code);
    const failText = `⚠️ 深度研究未能完成（${payload.code}）：${data.error ?? "未知原因"}\n\n可稍后在详情页「深度分析」区重试。`;
    for (const sid of sessionIds) {
      try {
        await appendMessage(sid, "assistant", failText);
      } catch (e) {
        console.error("[research] 失败推送落库失败:", e instanceof Error ? e.message : e);
      }
    }
    broadcast("research", {
      type: payload.type,
      code: payload.code,
      failed: true,
      error: data.error,
      sessionIds,
    });
  }
  return toRow(row);
}

/** 查询最近研报（详情页轮询） */
export async function getLatestReport(
  type: string,
  code: string,
): Promise<ReportRow | null> {
  const row = await prisma.researchReport.findFirst({
    where: { type, code },
    orderBy: { date: "desc" },
  });
  return row ? toRow(row) : null;
}
