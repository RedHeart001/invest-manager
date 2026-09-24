// 智能搜索：候选召回（FTS5 + LIKE）→ 加权打分 → 排序 → 价格富集
// 打分规则见 lib/score.ts；召回策略保证中文子串、拼音、首字母、代码均可命中。

import { type Quote } from "./data-service";
import { chatJson } from "./llm";
import { fetchQuotesByType } from "./quote-enrich";
import { prisma } from "./prisma";
import { parseTags, scoreProduct } from "./score";
import { buildMatchQuery } from "./search-text";

export type SearchResult = {
  type: string;
  code: string;
  name: string;
  exchange: string | null;
  tags: string[];
  score: number;
  price?: number | null;
  changePct?: number | null;
  quoteSource?: string;
  /** CR7-4/B2c：非 CNY 品种带币种（HKD/USD），列表展示加单位 */
  currency?: string | null;
};

const CANDIDATE_LIMIT = 300;

type CandidateProduct = {
  id: string;
  type: string;
  code: string;
  name: string;
  pinyin: string | null;
  pinyinInitials: string | null;
  exchange: string | null;
  tags: string | null;
};

async function gatherCandidates(q: string, type?: string): Promise<{
  products: CandidateProduct[];
  ftsIds: Set<string>;
}> {
  const ftsIds = new Set<string>();
  const match = buildMatchQuery(q);
  if (match) {
    try {
      const rows = await prisma.$queryRawUnsafe<{ productId: string }[]>(
        `SELECT productId FROM Product_fts WHERE Product_fts MATCH ? LIMIT ${CANDIDATE_LIMIT}`,
        match,
      );
      rows.forEach((r) => ftsIds.add(r.productId));
    } catch {
      // FTS5 虚表不存在时退化为纯 LIKE
    }
  }

  const nq = q.toLowerCase();
  const liked = await prisma.product.findMany({
    where: {
      ...(type ? { type } : {}),
      OR: [
        { code: { startsWith: q } },
        { name: { contains: q } },
        { pinyin: { startsWith: nq } },
        { pinyinInitials: { startsWith: nq } },
        { searchText: { contains: nq } },
      ],
    },
    select: {
      id: true,
      type: true,
      code: true,
      name: true,
      pinyin: true,
      pinyinInitials: true,
      exchange: true,
      tags: true,
    },
    // B2：候选加稳定排序——短查询（如单字符）会以任意顺序塞满上限，
    // 可能把精确代码命中挤掉；按 code 升序让前缀命中靠前且结果可预期
    orderBy: { code: "asc" },
    take: CANDIDATE_LIMIT,
  });

  const byId = new Map<string, CandidateProduct>();
  liked.forEach((p) => byId.set(p.id, p));

  if (ftsIds.size > 0) {
    const missing = Array.from(ftsIds).filter((id) => !byId.has(id));
    if (missing.length > 0) {
      const ftsProducts = await prisma.product.findMany({
        where: { id: { in: missing }, ...(type ? { type } : {}) },
        select: {
          id: true,
          type: true,
          code: true,
          name: true,
          pinyin: true,
          pinyinInitials: true,
          exchange: true,
          tags: true,
        },
        take: CANDIDATE_LIMIT,
      });
      ftsProducts.forEach((p) => byId.set(p.id, p));
    }
  }

  return { products: Array.from(byId.values()), ftsIds };
}

/** 内部：给定查询词执行一次"召回→打分→排序→截断"（不含行情富集） */
async function scoreQuery(
  q: string,
  type: string | undefined,
  limit: number,
): Promise<SearchResult[]> {
  const { products, ftsIds } = await gatherCandidates(q, type);

  // 个性化加权数据
  const [watchlist, clickGroups] = await Promise.all([
    prisma.watchlist.findMany({ select: { type: true, code: true } }),
    prisma.searchClickLog.groupBy({
      by: ["type", "code"],
      where: { query: q },
      _count: { _all: true },
    }),
  ]);
  const watched = new Set(watchlist.map((w) => `${w.type}:${w.code}`));
  const clicks = new Map(
    clickGroups.map((c) => [`${c.type}:${c.code}`, c._count._all]),
  );

  return products
    .map((p) => ({
      p,
      score: scoreProduct(q, p, {
        inWatchlist: watched.has(`${p.type}:${p.code}`),
        clicks: clicks.get(`${p.type}:${p.code}`) ?? 0,
        ftsHit: ftsIds.has(p.id),
      }),
    }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score || a.p.code.localeCompare(b.p.code))
    .slice(0, limit)
    .map(({ p, score }) => ({
      type: p.type,
      code: p.code,
      name: p.name,
      exchange: p.exchange,
      tags: parseTags(p.tags),
      score,
    }));
}

/**
 * G4（批次 D）：FTS/LIKE 无结果时的 LLM 兜底召回。
 * 让 LLM 从自然语言查询里抽取"产品名/代码/概念关键词"，再走一次检索。
 * 失败（LLM 未配置/不可用/无法抽取）一律静默返回空——兜底不得阻塞搜索。
 */
async function llmFallback(q: string, type: string | undefined, limit: number) {
  const extracted = await chatJson(
    "你是理财产品检索助手，从用户查询中抽取最可能的检索关键词。" +
      '输出 JSON：{"keywords":["关键词1","关键词2"]}。' +
      "关键词应为产品简称、代码或板块概念名（如 贵州茅台、600519、新能源），最多 3 个；" +
      "若无法抽取则返回空数组。不要输出解释。",
    q,
  );
  const kws = Array.isArray((extracted as { keywords?: unknown })?.keywords)
    ? ((extracted as { keywords: unknown[] }).keywords as unknown[])
        .map((k) => String(k).trim())
        .filter(Boolean)
        .slice(0, 3)
    : [];
  if (kws.length === 0) return [] as SearchResult[];
  for (const kw of kws) {
    const hits = await scoreQuery(kw, type, limit);
    if (hits.length > 0) return hits;
  }
  return [] as SearchResult[];
}

export async function searchProducts(opts: {
  q: string;
  type?: string;
  limit?: number;
}): Promise<SearchResult[]> {
  const q = opts.q.trim();
  // B2：limit 裁剪到 1~50（此前负数会走 slice(0,-1) 产生异常条数）
  const limit = Math.min(Math.max(opts.limit ?? 20, 1), 50);
  if (!q) return [];

  let results = await scoreQuery(q, opts.type, limit);

  // G4：无结果 → LLM 抽取关键词兜底重查（失败静默，不阻塞）
  if (results.length === 0) {
    try {
      results = await llmFallback(q, opts.type, limit);
    } catch {
      results = [];
    }
  }

  await enrichWithQuotes(results);
  return results;
}

/** 结果价格富集：按类型批量取行情（B4：公共实现 lib/quote-enrich.ts），失败则保持无价 */
async function enrichWithQuotes(results: SearchResult[]): Promise<void> {
  const quoteMap = await fetchQuotesByType(results);
  for (const r of results) {
    const quote = quoteMap.get(`${r.type}:${r.code}`);
    if (quote) {
      r.price = quote.price;
      r.changePct = quote.changePct;
      r.quoteSource = quote.source;
      r.currency = quote.currency ?? null;
    }
  }
}
