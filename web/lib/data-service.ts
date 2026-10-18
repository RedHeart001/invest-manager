// data-service 调用封装（BFF 内部使用）

const DATA_SERVICE_URL = process.env.DATA_SERVICE_URL ?? "http://localhost:8000";

/**
 * #63（2026-10-12）：BFF 侧 `/quote` 的预算（ms）＝30s，全站既有口径
 * （本文件 `dsGet` 默认；另一处 `app/api/quote/verify/route.ts` 已随 10-17 CR9-115 删）。此前 `/api/quote`
 * 与详情页 SSR 各写死 15s，与 ds 侧一条 stock `get_quote` 的最坏路径差一个量级：
 * `_em_request` 的 `acquire()` 默认 **20s**（`data-service/app/utils/limiter.py` 的 `acquire(timeout=20.0)`）
 * ＋ 多 host 两轮 × 每发 15s（`data-service/app/providers/akshare_provider.py:303-309`）。
 * 15s 会在多 host 降级（上游抖动）时把慢响应掐断，再被回成「服务没启动」（违 R16；
 * 10-11 夜 R13 实测字面 `code=600519 503 in 15792ms`，而同发 ds 侧 12 次全 200）。
 * ⇒ 预算不许低于 30s；独立成常量是为了让三处调用点（route、详情页 SSR）不再各写一个数。
 */
export const QUOTE_TIMEOUT_MS = 30_000;

/** CR6-P3-3：区分"超时"与"连不上"——此前 catch 一律报 unreachable，
 *  `AbortSignal.timeout` 触发的 TimeoutError 语义被吞掉，排查时无法定位。
 *
 *  #63（2026-10-12）：导出供 `/api/quote` 的裸 fetch catch 复用——那条是唯一
 *  没分「超时 vs 连不上」的 ds 调用臂，R16 要求失败原因如实。 */
export function unreachableMessage(e: unknown, timeoutMs: number): string {
  const name = (e as { name?: string } | null)?.name;
  if (name === "TimeoutError" || name === "AbortError") {
    return `data-service timeout after ${timeoutMs}ms（服务在跑但未及时响应）`;
  }
  return "data-service unreachable（连接被拒绝/网络不可达）";
}

export class DataServiceError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    // CR6-P1-1：保留已解析的响应体，供上层按业务语义分流
    // （如 /research/start 用 409 + {rejected,todayDone} 表达"被拒"，
    // 若不透出 body，调用方只能看到"提交失败"）。
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "DataServiceError";
  }
}

export async function dsGet<T>(
  path: string,
  params: Record<string, string | undefined> = {},
  timeoutMs = 30_000,
): Promise<T> {
  const url = new URL(`${DATA_SERVICE_URL}${path}`);
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) url.searchParams.set(k, v);
  }
  let res: Response;
  try {
    res = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    throw new DataServiceError(unreachableMessage(e, timeoutMs));
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}) as Record<string, unknown>);
    throw new DataServiceError(
      String((body as { detail?: string }).detail ?? `data-service returned ${res.status}`),
      res.status,
    );
  }
  return (await res.json()) as T;
}

export async function dsPost<T>(
  path: string,
  body: Record<string, unknown>,
  timeoutMs = 30_000,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${DATA_SERVICE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    throw new DataServiceError(unreachableMessage(e, timeoutMs));
  }
  const parsed = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new DataServiceError(
      String(parsed.detail ?? `data-service returned ${res.status}`),
      res.status,
      parsed,
    );
  }
  return parsed as T;
}

export type Quote = {
  type: string;
  code: string;
  name?: string;
  price: number | null;
  change?: number | null;
  changePct?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  prevClose?: number | null;
  volume?: number | null;
  amount?: number | null;
  /** P2 扩展：身份区/指标卡（部分品种为 null） */
  marketCap?: number | null;
  floatCap?: number | null;
  peTtm?: number | null;
  peDyn?: number | null;
  pb?: number | null;
  turnover?: number | null;
  marketCapRank?: number | null;
  /** CR7-4/B2c：provider 侧早已返回（hk=HKD / us=USD / 转债=CNY），此前 TS 契约漏了 */
  currency?: string | null;
  source?: string;
  timestamp?: string | null;
};

/** 批量行情（一次外部请求），失败返回空对象由调用方降级。
 *
 * `usesEastmoney`（丙／CR9-67）＝ds 对它说"这一批按**主源**路由会不会打东财 `ulist.np`"，
 * 刷新腿用它决定**这一批之后**要不要睡 5 秒。三态要说清：
 *  - `true`／`false`＝ds 侧的新契约给了答案；
 *  - `null`＝**不知道**（对着还没升级的 ds 跑、或这次请求超时／连不上被我们吞掉了）⇒
 *    调用方必须按"不知道"处理，不许当成 `false`（回落见 `market-snapshot.shouldPaceBatch`）。
 *    理由就在那条 CR9-9 的对照实验里：把限速关掉换来的是东财家族自己进 180s 熔断，
 *    同族所有消费者（热点 pipeline、搜索富集、其它类型快照）一起连坐。 */
export async function fetchQuotes(
  type: string,
  codes: string[],
): Promise<{ quotes: Record<string, Quote>; usesEastmoney: boolean | null }> {
  if (codes.length === 0) return { quotes: {}, usesEastmoney: null };
  try {
    const data = await dsGet<{
      quotes?: Record<string, Quote>;
      usesEastmoney?: boolean | null;
    }>("/quotes", { type, codes: codes.join(",") }, 20_000);
    const flag = typeof data.usesEastmoney === "boolean" ? data.usesEastmoney : null;
    return { quotes: data.quotes ?? {}, usesEastmoney: flag };
  } catch {
    return { quotes: {}, usesEastmoney: null };
  }
}
