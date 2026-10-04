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

/** CR8-3：来源链接从"裸 URL"升级为 `{url,title}`——标题在 ds 打分环节本就存在
 *  （`pipeline.py:_topic_urls`），旧契约在返回时丢掉，前端无从渲染。 */
export type SourceRef = { url: string; title: string };

/**
 * 归一化新闻源（OPT-2 刀 1：`newsSource` 单值 → `newsSources` 数组）。三种形态都要认：
 *  1. ds 直接 POST 来的**真数组**（新契约）；
 *  2. 库里新行的 **JSON 数组文本**（这一列仍是 `String?`，不动 schema、无 migration）；
 *  3. **存量裸字符串行**（`"cls"`／`"none"`）——CR8-8 那条教训：只改写侧会留存量缺口，
 *     历史批次的来源在页面上就瞎了。
 * 顺带把空串／空数组归一成 `[]`，渲染层再决定"没有来源"说什么字。
 */
export function toSourceList(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return [...new Set(raw.map((x) => String(x).trim()).filter(Boolean))];
  }
  const s = String(raw ?? "").trim();
  if (!s) return [];
  const flat = (list: unknown[]) => [...new Set(list.map((x) => String(x).trim()).filter(Boolean))];
  if (s.startsWith("[")) {
    // 数组形态解不出来＝半截或被手改坏 ⇒ 当"没有来源"，不许把 `"[oops"` 当成一家源的名字
    const parsed = safeJson<unknown>(s, null);
    return Array.isArray(parsed) ? flat(parsed) : [];
  }
  if (s.startsWith('"')) {
    // 被 JSON 引号包住的单个源名（`"cls"`）：解出来用，别把引号当来源名的一部分
    const parsed = safeJson<unknown>(s, null);
    if (typeof parsed === "string" && parsed.trim()) return [parsed.trim()];
  }
  return [s];
}

/** 归一化来源引用。**读侧必须兼容存量纯字符串行**：历史批次的 `sourceUrls` 里
 *  只有 URL，不重写库就永远拿不到标题 ⇒ 老行回退 `title: ""`（前端显示「原文」）。
 *  与 CR8-8 同一条教训：只改写侧会留下存量缺口。 */
export function toSourceRefs(raw: unknown): SourceRef[] {
  if (!Array.isArray(raw)) return [];
  const out: SourceRef[] = [];
  for (const it of raw) {
    if (typeof it === "string") {
      if (it) out.push({ url: it, title: "" });
    } else if (it && typeof it === "object") {
      const o = it as { url?: unknown; title?: unknown };
      if (typeof o.url === "string" && o.url) {
        out.push({ url: o.url, title: typeof o.title === "string" ? o.title : "" });
      }
    }
  }
  return out;
}

export type DigestRow = {
  id: string;
  date: string;
  title: string;
  summary: string;
  boardTags: string[];
  sourceUrls: SourceRef[];
  related: RelatedProduct[];
  /** OPT-2：这批热点来自哪几家新闻源（读侧已把存量裸字符串/JSON 文本归一成数组） */
  newsSources: string[];
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

/** Prisma 唯一约束冲突（P2002）判定 */
function isUniqueViolation(e: unknown): boolean {
  return typeof e === "object" && e !== null && (e as { code?: string }).code === "P2002";
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
    sourceUrls: toSourceRefs(safeJson<unknown[]>(r.sourceUrls, [])),
    // CR8-8：读侧也要剔退市——只加在 ingest 会留下**存量缺口**：历史行的
    // `relatedCodes` 里已经存着摘牌股，不重写库就永远显示出来。
    // 存量行的 name 同样是当年从 Product 取来的权威名（旧 `resolveRelated` 就这么写），
    // 所以这里不需要再查库。只判 `type === "stock"` ⇒ 口径不扩大到基金。
    related: safeJson<RelatedProduct[]>(r.relatedCodes, []).filter(
      (p) => !(p.type === "stock" && isDelistedName(p.name)),
    ),
    newsSources: toSourceList(r.newsSource),
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
  sourceUrls?: unknown;
  relatedCodes?: RelatedProduct[];
};

export type IngestPayload = {
  date: string;
  trigger?: string;
  engine?: string;
  newsSources?: string[];
  degraded?: boolean;
  note?: string | null;
  items: IngestItem[];
};

/**
 * CR8-8：退市股判据。板块成分表（新浪/同花顺）含陈旧成员，`600200 退市苏吴`、
 * `600086 退市金钰` 这类已摘牌标的会被当"相关产品"推荐，点进详情页是死路。
 * Product 表没有上市状态字段 ⇒ **库内权威名的「退市」前缀是这里唯一可用的信号**。
 * 主人 09-30 定口径：只滤退市；ST/*ST 与北交所**保留**（可正常交易，滤掉＝替用户
 * 判断可投资性）。
 */
export function isDelistedName(name: string): boolean {
  return name.includes("退市");
}

/** 板块成分股过滤（只保留库内存在、且非退市的股票）+ 板块名匹配基金（基金无成分接口，采用名称关键词） */
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
      if (name && !isDelistedName(name)) push({ type: "stock", code: r.code, name, board: r.board });
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
  // 整批共用同一份来源清单（ds 的 payload 是批次级的，逐行重复存会放大 5 倍）
  const newsSourcesJson = (() => {
    const l = toSourceList(payload.newsSources);
    return l.length ? JSON.stringify(l) : null;
  })();

  for (const item of items) {
    const title = String(item.title ?? "").trim().slice(0, 200);
    if (!title || existTitles.has(title)) {
      skipped += 1;
      continue;
    }
    const boardTags = (item.boardTags ?? []).map((t) => String(t).trim()).filter(Boolean);
    const related = await resolveRelated(item.relatedCodes ?? [], boardTags);
    let row;
    try {
      row = await prisma.hotspotDigest.create({
        data: {
          date: dayStart(dateIso),
          title: title.slice(0, 200),
          summary: String(item.summary ?? "").slice(0, 500),
          boardTags: JSON.stringify(boardTags),
          sourceUrls: JSON.stringify(toSourceRefs(item.sourceUrls ?? []).slice(0, 5)),
          relatedCodes: JSON.stringify(related),
          // OPT-2：一个数组落到那一列的 JSON 文本里（`String?` 不改 ⇒ 无 migration）；
          // 空清单落 null，而不是 "[]"——否则读侧要再分一次"没有源"与"源列表为空"。
          newsSource: newsSourcesJson,
          engine: payload.engine ?? null,
          degraded: Boolean(payload.degraded),
          note: payload.note ? String(payload.note).slice(0, 500) : null,
        },
      });
    } catch (e) {
      // CR-11（本轮 code review）：唯一约束 (date,title) 兜住并发 ingest 的
      // "先读后写"竞态——两个实例同时通过 existTitles 检查时，后写者在此被
      // 数据库拒绝（P2002），按"已存在"处理（跳过），不再产生重复卡片。
      if (isUniqueViolation(e)) {
        skipped += 1;
        existTitles.add(title);
        continue;
      }
      throw e;
    }
    existTitles.add(title);
    inserted += 1;
    createdRows.push(toDigestRow(row));
  }

  return { inserted, skipped, rows: createdRows };
}
