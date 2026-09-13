// 搜索文本与查询分词：中文用「二元组」展开，配合 FTS5 unicode61 分词器
// 实现子串匹配（unicode61 不会切分中文，"贵州茅台" 是单个 token，
// 展开为 "贵州 州茅 茅台" 后 "茅台" 才能命中）。

/** 抽取字符串中的 CJK 连续段 */
function cjkRuns(text: string): string[] {
  return text.match(/[一-鿿]+/g) ?? [];
}

/** 生成中文二元组（含单字回退） */
export function bigrams(text: string): string[] {
  const out: string[] = [];
  for (const run of cjkRuns(text)) {
    if (run.length === 1) {
      out.push(run);
      continue;
    }
    for (let i = 0; i + 2 <= run.length; i++) {
      out.push(run.slice(i, i + 2));
    }
  }
  return out;
}

/** ASCII 词元（代码、拼音、首字母） */
function asciiTokens(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9]+/g) ?? []);
}

/** 构建落库的 searchText（FTS5 索引源） */
export function buildSearchText(p: {
  name: string;
  code: string;
  pinyin?: string | null;
  pinyinInitials?: string | null;
  tags?: string[] | null;
}): string {
  const parts = new Set<string>();
  parts.add(p.name);
  for (const b of bigrams(p.name)) parts.add(b);
  if (p.pinyin) parts.add(p.pinyin);
  if (p.pinyinInitials) parts.add(p.pinyinInitials);
  parts.add(p.code);
  for (const t of p.tags ?? []) {
    parts.add(t);
    for (const b of bigrams(t)) parts.add(b);
  }
  return Array.from(parts).join(" ").toLowerCase();
}

/** 用户查询 → FTS5 MATCH 表达式（token 间 OR） */
export function buildMatchQuery(q: string): string | null {
  const tokens = new Set<string>();
  for (const b of bigrams(q)) tokens.add(b);
  for (const t of asciiTokens(q)) tokens.add(t);
  // 整体查询串也作为 token（覆盖完整名称查询）
  const whole = q.trim().toLowerCase();
  if (whole.length >= 2) tokens.add(whole);

  if (tokens.size === 0) return null;
  return Array.from(tokens)
    .map((t) => `"${t.replace(/"/g, '""')}"`)
    .join(" OR ");
}
