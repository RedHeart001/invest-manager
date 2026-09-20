// 行情富集公共逻辑（B4：合并 search.ts / browse.ts 中逐行重复的实现）
// 按类型批量取行情（单类型一次外部请求），返回 "type:code" → quote 的映射；
// 数据源失败时各类型独立降级（fetchQuotes 内部已吞错返回空对象）。

import { fetchQuotes } from "./data-service";

export type EnrichableType = "stock" | "fund" | "bond" | "crypto";

export type QuoteLike = {
  price: number | null;
  changePct: number | null;
  source?: string;
};

const ENRICH_TYPES = new Set(["stock", "fund", "bond", "crypto", "hk", "us"]);

/** 按类型批量取行情，返回 `${type}:${code}` → QuoteLike */
export async function fetchQuotesByType(
  items: { type: string; code: string }[],
): Promise<Map<string, QuoteLike>> {
  const byType = new Map<string, string[]>();
  for (const r of items) {
    if (!ENRICH_TYPES.has(r.type)) continue;
    const list = byType.get(r.type) ?? [];
    list.push(r.code);
    byType.set(r.type, list);
  }
  const quoteMap = new Map<string, QuoteLike>();
  await Promise.all(
    Array.from(byType.entries()).map(async ([type, codes]) => {
      const quotes = await fetchQuotes(type, codes);
      for (const [code, quote] of Object.entries(quotes)) {
        quoteMap.set(`${type}:${code}`, quote as QuoteLike);
      }
    }),
  );
  return quoteMap;
}
