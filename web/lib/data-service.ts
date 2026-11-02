// data-service 调用封装（BFF 内部使用）

const DATA_SERVICE_URL = process.env.DATA_SERVICE_URL ?? "http://localhost:8000";

/**
 * #63（2026-10-12）：BFF 侧 `/quote` 的预算（ms）＝30s，全站既有口径
 * （本文件 `dsGet` 默认；另一处 `app/api/quote/verify/route.ts` 已随 10-17 CR9-115 删）。此前 `/api/quote`
 * 与详情页 SSR 各写死 15s，与 ds 侧一条 stock `get_quote` 的最坏路径差一个量级：
 * `_em_request` 的 `acquire()` 默认 **20s**（`data-service/app/utils/limiter.py` 的 `acquire(timeout=20.0)`）
 * ＋ 多 host 两轮 × 每发 15s（`akshare_provider.py` 里遍历 `EM_HOSTS` 的那个 for，单发超时＝`REQUEST_TIMEOUT`）。
 * 15s 会在多 host 降级（上游抖动）时把慢响应掐断，再被回成「服务没启动」（违 R16；
 * 10-11 夜 R13 实测字面 `code=600519 503 in 15792ms`，而同发 ds 侧 12 次全 200）。
 * ⇒ 预算不许低于 30s；独立成常量是为了让两个消费点（`/api/quote` 的裸 fetch、详情页 SSR 的 `dsGet`）不再各写一个数。
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

/** 批次信封里的成因位（CR10-8，11-02）：这一批**为什么**一个价都没拿到。
 *  三形各自独立、不许合成一个数——今夜 02:00 那轮的实况就是反例：crypto 的
 *  `failedBatches=3` 里，1 批是 ds 回了 502（CoinGecko 那族不可达，detail 被旧 catch 扔掉），
 *  另 2 批在 ds 的访问日志里**根本没有**（web 侧超时/连不上）。两种成因在状态位里长成了一个数字。 */
export type QuotesFailKind =
  /** ds 明确回了非 2xx（成因原文＝ds 的 `detail`，已在 `DataServiceError.message` 里） */
  | "http"
  /** 超时／连不上＝这一发没被 ds 回答 */
  | "noAnswer"
  /** 200 但一个可用报价都没有（`quotes` 空，或 ds 自己声明的降级） */
  | "empty";

export type QuotesEnvelope = {
  quotes: Record<string, Quote>;
  usesEastmoney: boolean | null;
  failKind?: QuotesFailKind;
  /** 成因原文：ds 的 502 detail／超时文案／ds 自己的 `note`。只进接口字段，不上屏。 */
  failNote?: string;
};

/** 批量行情（一次外部请求）。失败时 `quotes` 仍回空对象由调用方降级，但从本行起**带得出成因**
 *  （`failKind`＋`failNote`，CR10-8）——此前它把所有成因在这一层抹平，下游只数得出批次。
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
): Promise<QuotesEnvelope> {
  if (codes.length === 0) return { quotes: {}, usesEastmoney: null };
  let data: {
    quotes?: Record<string, Quote>;
    usesEastmoney?: boolean | null;
    note?: string | null;
  };
  try {
    data = await dsGet<typeof data>("/quotes", { type, codes: codes.join(",") }, 20_000);
  } catch (e) {
    // 此前这里是裸 `catch { return {quotes:{}, ...} }`——ds 的 502 detail 明明已经被 `dsGet`
    // 变成异常消息带回来了（本文件 `:62-66`），却在这一层被整条丢掉，下游只能数批次。
    const answered = e instanceof DataServiceError && typeof e.status === "number";
    return {
      quotes: {},
      usesEastmoney: null,
      failKind: answered ? "http" : "noAnswer",
      failNote: e instanceof Error ? e.message : String(e),
    };
  }
  const quotes = data.quotes ?? {};
  const flag = typeof data.usesEastmoney === "boolean" ? data.usesEastmoney : null;
  if (Object.keys(quotes).length === 0) {
    return {
      quotes,
      usesEastmoney: flag,
      failKind: "empty",
      failNote: data.note ?? "data-service 回 200，但 quotes 为空（这一批没有匹配到任何报价）",
    };
  }
  return { quotes, usesEastmoney: flag };
}
