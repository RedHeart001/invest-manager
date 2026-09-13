// data-service 调用封装（BFF 内部使用）

const DATA_SERVICE_URL = process.env.DATA_SERVICE_URL ?? "http://localhost:8000";

export class DataServiceError extends Error {
  constructor(
    message: string,
    readonly status?: number,
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
  } catch {
    throw new DataServiceError("data-service unreachable");
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
  } catch {
    throw new DataServiceError("data-service unreachable");
  }
  const parsed = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new DataServiceError(
      String(parsed.detail ?? `data-service returned ${res.status}`),
      res.status,
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
  source?: string;
  timestamp?: string | null;
};

/** 批量行情（一次外部请求），失败返回空对象由调用方降级 */
export async function fetchQuotes(
  type: string,
  codes: string[],
): Promise<Record<string, Quote>> {
  if (codes.length === 0) return {};
  try {
    const data = await dsGet<{ quotes: Record<string, Quote> }>(
      "/quotes",
      { type, codes: codes.join(",") },
      20_000,
    );
    return data.quotes ?? {};
  } catch {
    return {};
  }
}
