import fs from "node:fs";
import path from "node:path";

import type { SnapshotResult } from "./market-snapshot";

/**
 * #33 甲／CR9-60：刷新腿的**逐类进度状态位**（主人 2026-10-04 的字＝"甲＋丙①"）。
 *
 * 防的是这一件事（10-04 02:11 实测）：刷新腿的逐类结果住在 `/api/market/refresh` 的
 * **响应体**里，连接被重置（`ConnectionResetError 10054`）时 ds 那侧永远拿不到，`lastRefresh`
 * 只剩一句 `outcome=failed`——当晚只能靠 `MAX(snapshotAt)` 与 `SUM(lastPrice IS NOT NULL)`
 * 反推"刷完 stock、fund 跑到第 35 批就断了"。按 #21/CR9-28 的纪律，这该做成状态位。
 *
 * 形态＝**覆写式的小 JSON 文件**（同 `#29/CR9-53` 的 `backups/state.json`）：先 `.tmp` 再
 * rename ⇒ 读的一侧永远看不到半截 JSON。为什么不放内存：进程一死（dev 重编译/config 变更
 * 重启，正是本条要归因的那一档）内存就没了，而 C17 也说过 Next 的 HMR 会重建模块作用域。
 *
 * **这份状态位同时把 #33 丙 的归因变成事后可读**：本腿拿到连接重置时，
 * 文件里是 `outcome=completed` ⇒ web 自己跑完了、是连接在半途被掐（丙①，socket 层）；
 * 停在 `running` 且 `current` 正是当时那一类 ⇒ web 进程根本没走到头（丙②，重启/重编译）。
 *
 * 观测不拖垮主功能（CR9-45／#29 同族）：写不进只打一条 warn，刷新照旧跑完。
 * 并发轮次共享这一份文件（读-改-写），日常只有一条链在跑；真要并发时它给的是
 * "有没有跑到第几类"这种粗粒度证据，不承诺严格的交错顺序——别拿它当事务日志用。
 */

export type RefreshProgress = {
  /** 本轮起跑时刻（ISO）——跨天读数时靠它判这份进度是不是今天这轮的 */
  startedAt: string;
  /** 本轮被要求刷的类型（顺序即执行顺序） */
  types: string[];
  /** 正在刷的那一类；全部跑完为 null */
  current: string | null;
  /** 已完成的逐类结果（与响应体里那份同源，只是提前落盘） */
  done: SnapshotResult[];
  outcome: "running" | "completed" | "failed";
  finishedAt: string | null;
};

const nowIso = () => new Date().toISOString();

/**
 * 落点默认 `web/runtime/refresh-progress.json`（`.gitignore` 里挡住了）。
 * 10-04 03:3x 实测过一件事：往 `web/runtime/` 与 `web/prisma/` 连写 6 个文件，45s 长请求
 * 在飞期间 dev 日志 `Compiled` **0 次**（正向对照＝bump 一个模块图里的源文件 ⇒ 1 次）⇒
 * 它不是 #31 那个"写一下就全量重编译"的触发源，**不需要再动 `next.config.ts` 的监听排除**。
 * env 覆盖是给单测用的（不许把仓库目录当测试产物落点）。
 */
function progressFile(): string {
  return process.env.REFRESH_PROGRESS_FILE || path.join(process.cwd(), "runtime", "refresh-progress.json");
}

function writeProgress(p: RefreshProgress): void {
  try {
    const file = progressFile();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(p), "utf8");
    fs.renameSync(tmp, file);
  } catch (e) {
    console.warn("[refresh-progress] write failed:", e instanceof Error ? e.message : String(e));
  }
}

/** 读不到就 null（没有文件／半截／被手改坏都算"没有进度可读"，不抛——健康检查不许因此 503）。 */
export function readRefreshProgress(): RefreshProgress | null {
  try {
    const obj = JSON.parse(fs.readFileSync(progressFile(), "utf8")) as unknown;
    if (!obj || typeof obj !== "object") return null;
    const p = obj as Partial<RefreshProgress>;
    if (!Array.isArray(p.done) || !Array.isArray(p.types)) return null;
    return p as RefreshProgress;
  } catch {
    return null;
  }
}

/** 刷新腿起跑时写一次 ⇒ "这一轮开始了、打算刷哪几类"从第一毫秒就可读。 */
export function startRefreshProgress(types: string[]): void {
  writeProgress({
    startedAt: nowIso(),
    types,
    current: types[0] ?? null,
    done: [],
    outcome: "running",
    finishedAt: null,
  });
}

/** 每完成一类覆写一次。`done` 从**盘上**接着写，不是从模块内存：HMR/重启后仍能续上。 */
export function recordRefreshResult(result: SnapshotResult): void {
  const prev = readRefreshProgress();
  const done = [...(prev?.done ?? []), result];
  const types = prev?.types?.length ? prev.types : [result.type];
  writeProgress({
    startedAt: prev?.startedAt ?? nowIso(),
    types,
    done,
    current: done.length < types.length ? types[done.length] : null,
    outcome: "running",
    finishedAt: null,
  });
}

/** 收尾（含异常收尾）。没有起跑记录也不抛——至少留下"有一个请求在这里结束"。 */
export function finishRefreshProgress(outcome: "completed" | "failed"): void {
  const prev = readRefreshProgress();
  writeProgress({
    startedAt: prev?.startedAt ?? nowIso(),
    types: prev?.types ?? [],
    done: prev?.done ?? [],
    current: null,
    outcome,
    finishedAt: nowIso(),
  });
}
