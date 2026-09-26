// 产品代码字符集校验（单一来源，CR7-6/C5 前置抽取）
//
// 此前该正则硬写在 research/start 与 watchlist 两处；B1 新增的 verify 路由
// 按账本约束也须同口径——非法 code 必须在调用 data-service 之前 400，
// 不得消耗外部数据源额度（东财 rate_per_min=12）。
export const CODE_SET = /^[\w.-]{1,20}$/;

/** 行情/研报取数允许的产品类型白名单（BFF 侧防御；ds 侧另有 400 语义） */
export const QUOTE_TYPES = ["stock", "fund", "bond", "crypto", "hk", "us"] as const;

/**
 * 取数类入参的成对校验：type 走白名单、code 走字符集，二者都过才允许出网。
 * 返回归一化后的 `{type, code}`，或 `{error}`（调用方据此 400 / 结构化失败）。
 *
 * CR9-10（2026-09-26 拍板接线）：`/api/events` 此前只判 code 非空、LLM 工具执行路径
 * 完全不判，两者都把任意串直送 data-service——与 CR7-6/C5 给 quote/kline/verify
 * 定的"白名单前移，非法入参不得耗东财额度（rate_per_min=12）"口径不一致。
 * 错误说明里带主语（CR9-30 同族）：截断并压掉空白，避免把任意长串原样回灌。
 */
export function checkSubject(
  type?: string | null,
  code?: string | null,
  defaultType: string = "stock",
): { type: string; code: string } | { error: string } {
  const t = type || defaultType;
  if (!QUOTE_TYPES.includes(t as (typeof QUOTE_TYPES)[number])) {
    return { error: `unsupported type: ${t}` };
  }
  const c = (code ?? "").trim();
  if (!CODE_SET.test(c)) {
    return { error: `invalid code: ${c.replace(/\s+/g, " ").slice(0, 40) || "(空)"}` };
  }
  return { type: t, code: c };
}
