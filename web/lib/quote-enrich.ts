// 行情富集公共逻辑（B4：合并 search.ts / browse.ts 中逐行重复的实现）
// 按类型批量取行情（单类型一次外部请求），返回 "type:code" → quote 的映射；
// 数据源失败时各类型独立降级（fetchQuotes 内部已吞错返回空对象）。

import { fetchQuotes } from "./data-service";

export type EnrichableType = "stock" | "fund" | "bond" | "crypto";

export type QuoteLike = {
  price: number | null;
  changePct: number | null;
  source?: string;
  /** CR7-4/B2c：非 CNY 品种带币种（HKD/USD），供展示层加单位 */
  currency?: string | null;
};

const ENRICH_TYPES = new Set(["stock", "fund", "bond", "crypto", "hk", "us"]);

/**
 * ds `/quotes` 的**服务端硬上限**：`main.py` 的 `codes.split(",")[:100]`——超出部分被
 * **静默截断**（不报错、不提示，就是那些 code 一个价都不回来）。
 *
 * 为什么在这里分批而不是"反正调用方都不到 100"：`search.ts`／`browse.ts` 每页最多 50 条，
 * 确实越不过去；但 **2026-11-01 的自选清单页（R18）按类型送全量**——某一类自选超过 100 只时，
 * 第 101 只起会安静地没有价格，屏上是一串 `--`，看起来像"上游没数据"，实际是被截断了。
 * 这正是本仓库反复登记的那一形（"绿着坏掉"）：没有断言、没有日志、界面不报错。
 *
 * ⚠️ 这个数是**镜像 ds 的常量**，不是我们自己的选择。ds 侧改上限时这里要跟着改
 * （`data-service/app/main.py` 的 `/quotes` 路由，`code_list` 的切片长度）。
 */
export const DS_QUOTES_MAX_CODES = 100;

/** 按 `DS_QUOTES_MAX_CODES` 切块；空数组返回空（不产出一个空批去出网）。 */
export function chunkCodes(codes: string[], size = DS_QUOTES_MAX_CODES): string[][] {
  if (codes.length === 0) return [];
  const n = Math.max(1, Math.floor(size));
  const out: string[][] = [];
  for (let i = 0; i < codes.length; i += n) out.push(codes.slice(i, i + n));
  return out;
}

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
      // 同一类型的多个切块**顺序发**而不是 `Promise.all`：ds 侧 /quotes 走的是按源族
      // 限速的令牌桶（东财 rate_per_min 是 IP 级），同时打进去只会让它们互相排队，
      // 还多出并发超时的可能。切块数通常就是 1（≤100 只），这条路径平白无成本。
      for (const chunk of chunkCodes(codes)) {
        const { quotes } = await fetchQuotes(type, chunk);
        for (const [code, quote] of Object.entries(quotes)) {
          quoteMap.set(`${type}:${code}`, quote as QuoteLike);
        }
      }
    }),
  );
  return quoteMap;
}
