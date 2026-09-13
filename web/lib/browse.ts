// 分类浏览（R14）：选中类型标签即浏览该类全部产品，支持涨幅/名称/代码排序
// - 全局排序基于 Product 行情快照列（lastChangePct，同步/刷新任务写入）
// - 当前页仍做实时行情富集（P1 管线）；实时缺失时回退展示快照值
// - 名称排序按拼音字母序（pinyin），空值沉底

import { type Quote } from "./data-service";
import { fetchQuotesByType } from "./quote-enrich";
import { prisma } from "./prisma";
import { parseTags } from "./score";

export type BrowseSort = "changePct" | "name" | "code";
export type BrowseOrder = "asc" | "desc";

export type BrowseItem = {
  type: string;
  code: string;
  name: string;
  exchange: string | null;
  tags: string[];
  price: number | null;
  changePct: number | null;
  quoteSource?: string;
  /** true = 展示的是快照值（实时行情不可用时） */
  stale: boolean;
};

export type BrowseResult = {
  items: BrowseItem[];
  total: number;
  page: number;
  pageSize: number;
  pages: number;
};

const MAX_PAGE_SIZE = 50;

export function normalizeBrowse(opts: {
  sort?: string | null;
  order?: string | null;
  page?: string | null;
  pageSize?: string | null;
}): { sort: BrowseSort; order: BrowseOrder; page: number; pageSize: number } {
  const sort: BrowseSort =
    opts.sort === "name" || opts.sort === "code" || opts.sort === "changePct"
      ? opts.sort
      : "changePct";
  const defaultOrder: BrowseOrder = sort === "changePct" ? "desc" : "asc";
  const order: BrowseOrder =
    opts.order === "asc" || opts.order === "desc" ? opts.order : defaultOrder;
  const page = Math.max(1, Math.floor(Number(opts.page ?? "1")) || 1);
  const pageSize = Math.min(
    MAX_PAGE_SIZE,
    Math.max(5, Math.floor(Number(opts.pageSize ?? "20")) || 20),
  );
  return { sort, order, page, pageSize };
}

export async function browseProducts(opts: {
  type: string; // 具体类型或 "all"
  sort: BrowseSort;
  order: BrowseOrder;
  page: number;
  pageSize: number;
}): Promise<BrowseResult> {
  const where = opts.type === "all" ? {} : { type: opts.type };

  const orderBy =
    opts.sort === "changePct"
      ? [
          { lastChangePct: { sort: opts.order, nulls: "last" } as const },
          { code: "asc" as const },
        ]
      : opts.sort === "name"
        ? [
            { pinyin: { sort: opts.order, nulls: "last" } as const },
            { code: "asc" as const },
          ]
        : [{ code: opts.order }];

  const [total, rows] = await Promise.all([
    prisma.product.count({ where }),
    prisma.product.findMany({
      where,
      orderBy,
      skip: (opts.page - 1) * opts.pageSize,
      take: opts.pageSize,
      select: {
        type: true,
        code: true,
        name: true,
        exchange: true,
        tags: true,
        lastPrice: true,
        lastChangePct: true,
      },
    }),
  ]);

  // 当前页实时富集（B4：公共实现 lib/quote-enrich.ts；失败回退快照值）
  const quoteMap = await fetchQuotesByType(rows);


  const items: BrowseItem[] = rows.map((r) => {
    const q = quoteMap.get(`${r.type}:${r.code}`);
    const stale = !q;
    return {
      type: r.type,
      code: r.code,
      name: r.name,
      exchange: r.exchange,
      tags: parseTags(r.tags),
      price: q?.price ?? r.lastPrice ?? null,
      changePct: q?.changePct ?? r.lastChangePct ?? null,
      quoteSource: q?.source,
      stale,
    };
  });

  return {
    items,
    total,
    page: opts.page,
    pageSize: opts.pageSize,
    pages: Math.max(1, Math.ceil(total / opts.pageSize)),
  };
}
