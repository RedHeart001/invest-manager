// 研报 running 状态陈旧判定（CR5-3，2026-09-17 review）
//
// 背景：data-service 的任务注册表是**内存态**（PLAN M5）；其执行中重启会丢失任务
// 与完成回调，web 侧 ResearchReport 行永久停在 running。后端已具备"超阈值可重提"
// 能力，前端据此把陈旧的 running 落入"可重新发起"态（复用既有触发按钮）。
//
// 本模块保持**零依赖**以便单测（不引入 prisma / next 相关模块）。

/** running 陈旧阈值：对齐后端 research.ts 的 STALE_RUNNING_MS（10 分钟） */
export const STALE_RUNNING_MS = 10 * 60 * 1000;

export type RunningLike = { status: string; updatedAt?: string | null };

/**
 * 该行是否为"陈旧的 running"（执行方疑似已重启）。
 * 仅在 status=running 且有可解析的 updatedAt 且已超阈值时为 true。
 */
export function isStaleRunning(row: RunningLike, nowMs: number = Date.now()): boolean {
  if (row.status !== "running" || !row.updatedAt) return false;
  const ts = new Date(row.updatedAt).getTime();
  if (!Number.isFinite(ts)) return false;
  return nowMs - ts > STALE_RUNNING_MS;
}
