import fs from "node:fs";
import path from "node:path";

import { beijingToday } from "./time";

/**
 * W4（2026-11-27）：把「今天这一轮同步到底谁失败了」读成 Web 侧可用的机器可读位。
 *
 * 治的形态：`freshness.ts` 的陈旧说明只看**库里有多旧**（`listAt` 早于昨日才说话，给了一天
 * 宽限挡休市日误报）。于是"昨天成功、今天 02:00 那一轮失败"这一整天，页面都在把昨天的名单
 * 当成今天的展示，一句提示都没有——这正是方案里"保留旧数据 ≠ 把旧数据当最新"那条分界。
 *
 * 为什么读**共享卷上的文件**而不是问 DS 的 `/sync/status`：
 *  · 浏览一次只多一次本地 `readFileSync`（几千字节），零出网、不占任何源族桶；
 *  · DS 挂了/重启中时它仍然读得到——而那恰恰是最需要说出"数据是旧的"的时刻，
 *    反过来做成 HTTP 依赖就会在最该说话的时候沉默（CR9-45 同族纪律）；
 *  · 权威判据本来就是 DS 侧写在盘上的那一份（`sync_scheduler._mark_outcome`）。
 *
 * 落点与 DS 同源：容器里两个服务挂的是**同一个** `prisma-data` 卷
 * （web 见 `/app/data`、data-service 见 `/data`），所以 `/app/data/runtime/sync-state.json`
 * 就是 DS 的 `SYNC_STATE_FILE`。开发态没有该卷 ⇒ 回落到仓库里的 `data-service/runtime/`。
 * 刻意**不新增 compose env**：那要动 `compose-token.test.ts` 逐枚列出的键面清单，
 * 而"候选路径逐个尝"已经覆盖两种部署形态。
 */

/** 一份"今天这一轮同步"的读侧视图（只挑展示要用的那几枚，不复制整份文件形状）。 */
export type SyncAttempt = {
  /** `lastAttemptDate`（北京时间 YYYY-MM-DD）；读不到为 null */
  date: string | null;
  /** `daily` / `startup-catchup` / `manual` */
  trigger: string | null;
  /** `running` / `completed` / `partial_failed` / `skipped` / `inconclusive` / `rejected` / `failed` */
  outcome: string | null;
  at: string | null;
  /** 逐类失败原因（只收**有 error** 的那几类；键＝type） */
  failed: Record<string, { error: string; note?: string }>;
  /** 逐类「今日成功但降级」的说明（note 带 `DEGRADED_NOTE_MARKER`；键＝type） */
  degraded: Record<string, string>;
  /** 当日幂等闸门挡下的那几类（`skipped`，不是失败） */
  skipped: string[];
  /** W3 的补试计划（盘上那份原样带回，展示层用它说"已安排自动补试"） */
  retry: RetryPlan | null;
  /** `disk`＝真读到了文件；`none`＝没有文件（从未跑过 / 路径不对） */
  source: "disk" | "none";
  /** 读取失败的原因字面（缺文件不算错，返回 null） */
  readError: string | null;
};

export type RetryPlan = {
  date?: string;
  state?: string;
  types?: string[];
  notBefore?: string;
  attempt?: number;
  maxAttempts?: number;
  outcome?: string;
  cancelReason?: string;
  /** `exhausted` 时 DS 记的那句话（仍失败 / 结果未知） */
  error?: string | null;
};

/**
 * `web/lib/sync.ts` 写进逐类 `note` 的降级标记（`list degraded source=<源>`）。
 *
 * 两侧共用**这一个**字面量：`sync.ts` 用模板拼它、这里用它判，改词就会同时改到判据
 * （否则某天把 note 措辞改柔和，降级态会静默退回 fresh——那正是"看不见的降级"R16 那一族）。
 */
export const DEGRADED_NOTE_MARKER = "list degraded source=";

const EMPTY: SyncAttempt = {
  date: null,
  trigger: null,
  outcome: null,
  at: null,
  failed: {},
  degraded: {},
  skipped: [],
  retry: null,
  source: "none",
  readError: null,
};

/** 候选落点：env 显式覆盖 → 容器共享卷 → 仓库开发态。 */
function candidatePaths(): string[] {
  const out: string[] = [];
  const env = process.env.SYNC_STATE_FILE;
  if (env) out.push(env);
  out.push("/app/data/runtime/sync-state.json");
  out.push(path.join(process.cwd(), "..", "data-service", "runtime", "sync-state.json"));
  return [...new Set(out)];
}

function readStateFile(): { data: unknown; error: string | null } {
  let lastError: string | null = null;
  let sawAny = false;
  for (const p of candidatePaths()) {
    try {
      sawAny = true;
      return { data: JSON.parse(fs.readFileSync(p, "utf8")) as unknown, error: null };
    } catch (e) {
      const code = (e as NodeJS.ErrnoException).code;
      if (code !== "ENOENT") lastError = `${path.basename(p)}: ${code ?? (e as Error).name}`;
    }
  }
  // 一个候选路径都不存在 ≠ 读坏了：那是"这台机上从来没有过同步状态"（首次部署/开发态）
  return { data: null, error: sawAny ? lastError : null };
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

/** 读今天这一轮的同步结局（纯函数化到 `parseSyncAttempt`，便于零文件单测）。 */
export function readSyncAttempt(): SyncAttempt {
  const { data, error } = readStateFile();
  if (data === null) return { ...EMPTY, readError: error };
  return parseSyncAttempt(data);
}

/** 盘上那份 `sync-state.json` → 读侧视图（形状不对一律当"没有"，展示层不许因此 500）。 */
export function parseSyncAttempt(raw: unknown): SyncAttempt {
  const data = asRecord(raw);
  if (!data) return { ...EMPTY };
  const lastResult = asRecord(data.lastResult);
  const results = Array.isArray(lastResult?.results) ? (lastResult!.results as unknown[]) : [];
  const failed: SyncAttempt["failed"] = {};
  const degraded: SyncAttempt["degraded"] = {};
  const skipped: string[] = [];
  for (const item of results) {
    const r = asRecord(item);
    const type = str(r?.type);
    if (!r || !type) continue;
    const err = str(r.error);
    if (err) {
      const note = str(r.note);
      failed[type] = note ? { error: err, note } : { error: err };
      continue;
    }
    if (r.skipped) {
      skipped.push(type);
      continue;
    }
    const note = str(r.note);
    if (note && note.includes(DEGRADED_NOTE_MARKER)) degraded[type] = note;
  }
  const retry = asRecord(data.retry) as RetryPlan | null;
  return {
    date: str(data.lastAttemptDate),
    trigger: str(data.lastAttemptTrigger),
    outcome: str(data.lastAttemptOutcome),
    at: str(data.at),
    failed,
    degraded,
    skipped,
    retry: retry && typeof retry.state === "string" ? retry : null,
    source: "disk",
    readError: null,
  };
}

/** 今天（北京日界）这一轮里，`type` 的失败原因；不是今天 / 没失败 ⇒ null。
 *
 * 「是不是今天」这一道是"尚未到调度时间不报警"的落点：夜里 00:30 打开页面时，盘上还是
 * **昨天**那一轮（今天这轮 02:00 才跑），此时任何失败都不该被说成"今日失败"。
 *
 * `today` 可显式给：调用方（`staleNotes`）已经拿着一个判据日，若这里各自再取一次
 * `beijingToday()`，跨零点的一次渲染就会前后不一致（上面说"昨天那轮"，下面说"今日失败"）。
 */
export function todayFailure(
  attempt: SyncAttempt,
  type: string,
  today: string = beijingToday(),
): { error: string; note?: string } | null {
  if (attempt.date !== today) return null;
  return attempt.failed[type] ?? null;
}

/** 今天这一轮里 `type` 是否"取到了、但来源降级"；不是今天 ⇒ null（`today` 同 `todayFailure`） */
export function todayDegradedNote(
  attempt: SyncAttempt,
  type: string,
  today: string = beijingToday(),
): string | null {
  if (attempt.date !== today) return null;
  return attempt.degraded[type] ?? null;
}

/** 补试计划的一句话说明（展示层直接用；`null`＝今天没有安排）。
 *
 * 四种状态都要说得出人话，且**不许**把 `exhausted`／`cancelled` 说成"还会再试一次"：
 * 那两种恰恰是"今天已经不会再自动补了"，说错就变成第二种谎（R16 同族）。
 */
export function retryNote(plan: RetryPlan | null, today: string = beijingToday()): string | null {
  if (!plan || plan.date !== today) return null;
  const types = (plan.types ?? []).join("、");
  const at = (plan.notBefore ?? "").slice(11, 16);
  switch (plan.state) {
    case "pending":
      return at ? `已安排 ${at} 自动补试（${types}）` : `已安排一次自动补试（${types}）`;
    case "running":
      return `正在自动补试（${types}）`;
    case "completed":
      return `自动补试已完成（${types}）`;
    case "exhausted":
      return `自动补试仍未成功（${types}），今日不再自动重试`;
    case "cancelled":
      return `自动补试已取消（${types}），今日不再自动重试`;
    default:
      return `补试计划状态：${plan.state}`;
  }
}
