// 热点 digest 数据层（P3 / M1）：
// - 落库（ingest 回调）：去重（date+title）→ 相关产品解析（板块成分股过滤到库内 + 板块名匹配基金）
// - 查询：默认取最近有数据的日期；按日期取当日卡片流

import { prisma } from "./prisma";

export type RelatedProduct = {
  type: string;
  code: string;
  name: string;
  board?: string;
};

export type DigestRow = {
  id: string;
  date: string;
  title: string;
  summary: string;
  boardTags: string[];
  sourceUrls: string[];
  related: RelatedProduct[];
  newsSource: string | null;
  engine: string | null;
  degraded: boolean;
  note: string | null;
  createdAt: string;
};

function safeJson<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function dayStart(iso: string): Date {
  return new Date(`${iso}T00:00:00.000Z`);
}

type DigestDbRow = {
  id: string;
  date: Date;
  title: string;
  summary: string;
  boardTags: string | null;
  sourceUrls: string | null;
  relatedCodes: string | null;
  newsSource: string | null;
  engine: string | null;
  degraded: boolean | null;
  note: string | null;
  createdAt: Date;
};

export function toDigestRow(r: DigestDbRow): DigestRow {
  return {
    id: r.id,
    date: r.date.toISOString().slice(0, 10),
    title: r.title,
    summary: r.summary,
    boardTags: safeJson<string[]>(r.boardTags, []),
    sourceUrls: safeJson<string[]>(r.sourceUrls, []),
    related: safeJson<RelatedProduct[]>(r.relatedCodes, []),
    newsSource: r.newsSource,
    engine: r.engine,
    degraded: Boolean(r.degraded),
    note: r.note,
    createdAt: r.createdAt.toISOString(),
  };
}

/** 查询：指定日期或"最近有数据的日期" */
export async function listDigests(opts: {
  date?: string | null;
  limit?: number;
}): Promise<{ date: string | null; rows: DigestRow[] }> {
  const limit = Math.min(Math.max(opts.limit ?? 30, 1), 100);
  let dateIso = opts.date && /^\d{4}-\d{2}-\d{2}$/.test(opts.date) ? opts.date : null;

  if (!dateIso) {
    const latest = await prisma.hotspotDigest.findFirst({
      orderBy: { date: "desc" },
      select: { date: true },
    });
    if (!latest) return { date: null, rows: [] };
    dateIso = latest.date.toISOString().slice(0, 10);
  }

  const rows = await prisma.hotspotDigest.findMany({
    where: { date: dayStart(dateIso) },
    orderBy: { createdAt: "desc" },
    take: limit,
  });
  return { date: dateIso, rows: rows.map(toDigestRow) };
}

export async function countDigests(dateIso: string): Promise<number> {
  return prisma.hotspotDigest.count({ where: { date: dayStart(dateIso) } });
}

export type IngestItem = {
  title: string;
  summary?: string;
  boardTags?: string[];
  sourceUrls?: string[];
  relatedCodes?: RelatedProduct[];
};

export type IngestPayload = {
  date: string;
  trigger?: string;
  engine?: string;
  newsSource?: string;
  degraded?: boolean;
  note?: string | null;
  items: IngestItem[];
};

/** 板块成分股过滤（只保留库内存在的股票）+ 板块名匹配基金（基金无成分接口，采用名称关键词） */
async function resolveRelated(
  related: RelatedProduct[],
  boardTags: string[],
): Promise<RelatedProduct[]> {
  const out: RelatedProduct[] = [];
  const seen = new Set<string>();
  const push = (p: RelatedProduct) => {
    const k = `${p.type}:${p.code}`;
    if (seen.has(k)) return;
    seen.add(k);
    out.push(p);
  };

  // 1) 成分股：只保留 Product 表存在的（保证链接可用）
  const stockCodes = related.filter((r) => r.type === "stock").map((r) => r.code);
  if (stockCodes.length > 0) {
    const known = await prisma.product.findMany({
      where: { type: "stock", code: { in: stockCodes } },
      select: { code: true, name: true },
    });
    const nameByCode = new Map(known.map((k) => [k.code, k.name]));
    for (const r of related) {
      if (r.type !== "stock") continue;
      const name = nameByCode.get(r.code);
      if (name) push({ type: "stock", code: r.code, name, board: r.board });
    }
  }

  // 2) 主题基金：板块名在基金名称中的关键词匹配（每板块最多 3 只）
  for (const tag of boardTags.slice(0, 2)) {
    if (!tag || tag.length < 2) continue;
    const funds = await prisma.product.findMany({
      where: { type: "fund", name: { contains: tag } },
      select: { code: true, name: true },
      take: 3,
      orderBy: { code: "asc" },
    });
    for (const f of funds) push({ type: "fund", code: f.code, name: f.name, board: tag });
  }

  return out.slice(0, 16);
}

/** 落库：按 (date, title) 去重，返回新插入的行（供 SSE 广播） */
export async function ingestDigests(
  payload: IngestPayload,
): Promise<{ inserted: number; skipped: number; rows: DigestRow[] }> {
  const dateIso = payload.date;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateIso)) {
    throw new Error("invalid date (expect YYYY-MM-DD)");
  }
  const items = Array.isArray(payload.items) ? payload.items : [];

  const existing = await prisma.hotspotDigest.findMany({
    where: { date: dayStart(dateIso) },
    select: { title: true },
  });
  // 去重口径与落库一致：库内标题已截断到 200 字（代码审查修复，此前前 200 字
  // 相同但更长的标题被判为不同 → 重复行）
  const existTitles = new Set(existing.map((e) => e.title.slice(0, 200)));

  let inserted = 0;
  let skipped = 0;
  const createdRows: DigestRow[] = [];

  for (const item of items) {
    const title = String(item.title ?? "").trim().slice(0, 200);
    if (!title || existTitles.has(title)) {
      skipped += 1;
      continue;
    }
    const boardTags = (item.boardTags ?? []).map((t) => String(t).trim()).filter(Boolean);
    const related = await resolveRelated(item.relatedCodes ?? [], boardTags);
    const row = await prisma.hotspotDigest.create({
      data: {
        date: dayStart(dateIso),
        title: title.slice(0, 200),
        summary: String(item.summary ?? "").slice(0, 500),
        boardTags: JSON.stringify(boardTags),
        sourceUrls: JSON.stringify((item.sourceUrls ?? []).slice(0, 5)),
        relatedCodes: JSON.stringify(related),
        newsSource: payload.newsSource ?? null,
        engine: payload.engine ?? null,
        degraded: Boolean(payload.degraded),
        note: payload.note ? String(payload.note).slice(0, 500) : null,
      },
    });
    existTitles.add(title);
    inserted += 1;
    createdRows.push(toDigestRow(row));
  }

  return { inserted, skipped, rows: createdRows };
}
