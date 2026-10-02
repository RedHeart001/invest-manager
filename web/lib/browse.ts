// 分类浏览（R14）：选中类型标签即浏览该类全部产品，支持涨幅/名称/代码排序
// - 全局排序基于 Product 行情快照列（lastChangePct，同步/刷新任务写入）
// - 当前页仍做实时行情富集（P1 管线）；实时缺失时回退展示快照值
// - 名称排序按拼音字母序（pinyin），空值沉底
// - **#22(b)／#25 陈旧可见性**：该类的主数据或价格快照早于昨日（北京日界）时，
//   随结果给一句说明；正常态一条都不出（那时这句话零信息量）

import { type Quote } from "./data-service";
import { type StaleNote, freshnessOfTypes, staleNotes } from "./freshness";
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
  /** CR9-6：非 CNY 品种（港股/美股）必须带币种，否则分类浏览显示成无单位数字 */
  currency?: string | null;
  quoteSource?: string;
};

export type BrowseResult = {
  items: BrowseItem[];
  total: number;
  page: number;
  pageSize: number;
  pages: number;
  /** #22(b)／#25：陈旧说明（正常态为空数组＝页面上一个字都不出） */
  stale: StaleNote[];
  /** 超出展示上限而被收起的条数（不静默丢弃——被藏掉的那一类正是这句话要防的） */
  staleMore: number;
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

  // 陈旧可见性（#22(b)／#25）：与列表同一批取，省掉第二次全表扫的等待
  // （`groupBy` 走 `type` 上的分组＋两个 MAX，3.4 万行量级、每请求一次）
  const [total, rows, freshness] = await Promise.all([
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
    freshnessOfTypes(opts.type === "all" ? {} : { type: opts.type }),
  ]);

  // 当前页实时富集（B4：公共实现 lib/quote-enrich.ts；失败回退快照值）
  const quoteMap = await fetchQuotesByType(rows);


  const items: BrowseItem[] = rows.map((r) => {
    const q = quoteMap.get(`${r.type}:${r.code}`);
    return {
      type: r.type,
      code: r.code,
      name: r.name,
      exchange: r.exchange,
      tags: parseTags(r.tags),
      price: q?.price ?? r.lastPrice ?? null,
      changePct: q?.changePct ?? r.lastChangePct ?? null,
      currency: q?.currency ?? null, // CR9-6：实时币种透传；快照回退无币种时留空（CNY 语义下不显示后缀）
      quoteSource: q?.source,
    };
  });

  // 陈旧说明（#22(b)／#25）：展示上限 2 条属于渲染层口径（CR8-1「一批最多两条」），
  // 但**被收起的条数必须一起交出去**——10-02 活体探针撞上 stock／bond／crypto 三类同日
  // 陈旧，只 slice(0,2) 会把第三类静默藏掉，而"藏掉一类陈旧"正是这句话要防的形态。
  const stale = staleNotes(freshness);
  return {
    items,
    total,
    page: opts.page,
    pageSize: opts.pageSize,
    pages: Math.max(1, Math.ceil(total / opts.pageSize)),
    stale: stale.slice(0, 2),
    staleMore: Math.max(0, stale.length - 2),
  };
}
