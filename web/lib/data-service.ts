// data-service 调用封装（BFF 内部使用）
//
// ⚠️ **本文件是"同构"的**：`lib/events.ts` 被 `"use client"` 的 `ProductCharts.tsx`
// import，而 events.ts 又 import 本文件 ⇒ 本模块会进**浏览器 bundle**。
// 因此这里只许有 fetch/AbortSignal 这类两端都有的东西；
// 任何 `node:` 内置或仅服务端的包（如 `undici`）都必须在**函数体内**延迟 require，
// 或搬到只跑在服务端的入口（见 `web/instrumentation.ts`）。
// 2026-11-07 的教训：把 `import { Agent } from "undici"` 写在顶层，webpack 立刻顺着
// `undici → node:assert` 报 `UnhandledSchemeError`，整站编译失败。

const DATA_SERVICE_URL = process.env.DATA_SERVICE_URL ?? "http://localhost:8000";

/** 传输层上限（ms）——**不是**业务预算，是"这条连接最多能被拖多久"的兜底。
 *
 * 为什么需要这一层（2026-11-07 实测，此前一直是潜伏雷）：
 * Node 内置 `fetch`（undici）自带 `headersTimeout`，**默认 300s**，它在
 * `AbortSignal.timeout(N)` 之前触发 ⇒ 任何 N > 300_000 的预算都是**假的**。
 * 现场证据：`sync.ts` 给 `GET /products?type=stock` 的预算是 600_000，而实测该请求
 * 要 **435.8s**（5927 只 × 东财 `clist/get` 每页硬截 100 行 × `eastmoney` 桶 5s/页）；
 * 结果 303155ms 就被掐断，且抛的是 `TypeError` + `cause.code=UND_ERR_HEADERS_TIMEOUT`
 * ——`name` 不匹配 `TimeoutError`/`AbortError`，于是被下面 `unreachableMessage` 译成
 * 「连接被拒绝/网络不可达」（违 R16：失败原因不如实）。
 * 离线对照实验（`.tmp/undici-probe/`，Node v26.13.0 / undici 8.12.2）：
 *   服务端 4s 才回，`headersTimeout=2500` ⇒ 3061ms 断；`headersTimeout=6000` ⇒ 4022ms 成功
 *   ⇒ 这个旋钮**按设定值线性生效**，调大即可越过默认 300s。
 *
 * **不变量（改任何一侧前先读这条）**：`TRANSPORT_CEILING_MS` 必须 **大于** 全仓最大的
 * 单次 ds 预算。现值最大者＝`productsBudgetMs("us")` 的 1_800_000（美股乙全量，11-12）
 * ⇒ 2_700_000 留 1.5 倍。三层不变量：ds 看门狗（1500s）＜ web 业务预算（us 1800s）＜ 本上限。
 * 反过来，业务预算必须是**更小**的那一个：这样超时时先到期的是 `AbortSignal`，
 * 抛 `TimeoutError`（语义准确、文案说得出"预算多少"），传输层只是永不先开的保险。
 *
 * 常量住在这里（谁 import 都安全，纯数字），**安装动作**住在 `web/instrumentation.ts`。
 */
export const TRANSPORT_CEILING_MS = 2_700_000;

/** 供 `instrumentation.ts` 与测试共用的**纯值**，安装逻辑不在这里（避免把 undici 拖进浏览器）。
 *  返回 undefined 表示当前运行时没有 undici（浏览器）；调用方应当跳过。 */
export function shouldInstallTransportCeiling(): boolean {
  return typeof window === "undefined" && typeof process !== "undefined";
}

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

/** `/products` 的按类型预算（ms，11-12 美股乙）：us 全量＝新浪名单（上限 950 页、早停按实盘）、名义 ≈950s，
 *  600s 共用预算装不下 ⇒ us 单独 1_800_000（＞ds 看门狗 1500s，超时先由 ds 侧到期、
 *  回执带原文）；其余类型沿用 600_000（港股 48 页 × 东财桶 5s 的最坏形态）。
 *  常量住这里＝ds 预算单一来源，`data-service.test.ts` 的不变量断言从这几个数算。 */
export const PRODUCTS_BUDGET_MS = 600_000;
export const US_PRODUCTS_BUDGET_MS = 1_800_000;
export function productsBudgetMs(type: string): number {
  return type === "us" ? US_PRODUCTS_BUDGET_MS : PRODUCTS_BUDGET_MS;
}

/** CR6-P3-3：区分"超时"与"连不上"——此前 catch 一律报 unreachable，
 *  `AbortSignal.timeout` 触发的 TimeoutError 语义被吞掉，排查时无法定位。
 *
 *  #63（2026-10-12）：导出供 `/api/quote` 的裸 fetch catch 复用——那条是唯一
 *  没分「超时 vs 连不上」的 ds 调用臂，R16 要求失败原因如实。
 *
 *  **2026-11-07 补第三档（`UND_ERR_*`）**：此前只认 `name`，而 undici 自己的传输层
 *  超时抛的是 `TypeError('fetch failed')` + `cause.code='UND_ERR_HEADERS_TIMEOUT'`
 *  ——`name` 是 `TypeError`，落进了 else ⇒ **超时被报成「连接被拒绝/网络不可达」**。
 *  现场代价：stock 列表那轮的真实成因（435.8s 的请求被 300s 传输层上限掐断）在回执里
 *  完全看不出来。三档都归"超时"是对的：它们的共同语义是**对端可能还在算，只是我们不等了**；
 *  而 `ECONNREFUSED`/`ENOTFOUND` 仍是"连不上"，不该混。
 *  文案要带出 code（排查时它是唯一能区分"我们的上限"与"预算到期"的线索）。
 */
const UNDICI_TIMEOUT_CODES = new Set([
  "UND_ERR_HEADERS_TIMEOUT",
  "UND_ERR_BODY_TIMEOUT",
  "UND_ERR_CONNECT_TIMEOUT",
]);

export function unreachableMessage(e: unknown, timeoutMs: number): string {
  const err = e as { name?: string; cause?: { code?: string } } | null;
  const name = err?.name;
  if (name === "TimeoutError" || name === "AbortError") {
    return `data-service timeout after ${timeoutMs}ms（服务在跑但未及时响应）`;
  }
  const code = err?.cause?.code;
  if (code && UNDICI_TIMEOUT_CODES.has(code)) {
    // 这一档刻意**不**说 timeoutMs：掐断它的是传输层上限（`TRANSPORT_CEILING_MS`），
    // 不是调用方给的预算。把预算数写在这里等于谎报"我们等了 timeoutMs 才放弃"。
    return `data-service transport timeout（${code}，请求已发出但未在上限内得到响应；不是连接被拒）`;
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
