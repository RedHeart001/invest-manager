// 自选清单（R18，2026-11-01）——清单页的数据整形，与取数解耦以便零出网单测。
//
// 为什么单独一个文件而不是写在 page.tsx 里：分组顺序、未知类型落位、"这一条有没有价"
// 这三件事都是**纯函数可判定**的，塞进 Server Component 就只能靠起服务手测；而它们一出错
// 的形态恰是"看起来正常、实际少了一组"（R16 同族），必须有断言守着。

import type { QuoteLike } from "./quote-enrich";
import { TYPE_LABEL } from "./type-label";

/** 清单页需要的自选行（`prisma.watchlist` 的子集，`createdAt` 只用于排序、不进屏）。 */
export type WatchRow = { type: string; code: string; name: string };

export type WatchItem = {
  type: string;
  code: string;
  name: string;
  price: number | null;
  changePct: number | null;
  currency: string | null;
  /** 这一条拿没拿到实时价。false ⇒ 屏上价格列显示 `--`（**不是** 0，也不是"没数据"的谎） */
  quoted: boolean;
};

export type WatchGroup = { type: string; label: string; items: WatchItem[] };

/**
 * 分组顺序＝**固定表序**，既不是 ASCII 序也不是"按数据量排"。
 * 理由：清单页每次打开时各块的位置必须稳定，否则"股票那一组在哪儿"每次都在动；
 * 按数据量排还会让"加了一个自选"把整页顺序打乱。
 * 表外类型（历史脏数据，正常路径写不进来）排最后、保持出现顺序——不丢、不猜、不报错。
 */
export const WATCH_TYPE_ORDER = ["stock", "fund", "bond", "crypto", "hk", "us"] as const;

export function groupWatchlist(
  rows: WatchRow[],
  quoteMap: Map<string, QuoteLike>,
): WatchGroup[] {
  const byType = new Map<string, WatchRow[]>();
  for (const r of rows) {
    const list = byType.get(r.type);
    if (list) list.push(r);
    else byType.set(r.type, [r]);
  }

  const known = WATCH_TYPE_ORDER.filter((t) => byType.has(t));
  const unknown = [...byType.keys()].filter(
    (t) => !(WATCH_TYPE_ORDER as readonly string[]).includes(t),
  );

  return [...known, ...unknown].map((type) => ({
    type,
    label: TYPE_LABEL[type] ?? type,
    items: (byType.get(type) ?? []).map((r) => {
      const q = quoteMap.get(`${r.type}:${r.code}`);
      return {
        type: r.type,
        code: r.code,
        name: r.name,
        price: q?.price ?? null,
        changePct: q?.changePct ?? null,
        currency: q?.currency ?? null,
        quoted: q?.price != null,
      };
    }),
  }));
}

/**
 * 整批行情是不是**全都没取到**——用于给页面决定要不要出一句降级说明。
 *
 * 判据刻意只有这一个：有自选行、但一条行情都没回来。三条"不许"：
 *  - 不许按"某些条没价"说话：单只标的缺价是上游常态（停牌、新股），逐条报会变成噪音，
 *    而 `browse.ts` 对同一情形的处置也是这样（正常态不出字）。
 *  - 不许猜成因：`fetchQuotes` 把"数据服务不可达""超时""上游空"吞成同一个空对象，
 *    此处若断言是哪一种就是编造（R16）。文案里要并列写出可能成因，由人自己对号。
 *  - 不许把空自选误报成降级：`rows.length === 0` 时返回 false。
 */
export function quotesAllMissing(rows: WatchRow[], quoteMap: Map<string, QuoteLike>): boolean {
  return rows.length > 0 && quoteMap.size === 0;
}
