// 搜索结果打分（纯函数，便于单测）
// 规则：命中方式取最高分，再叠加个性化加权（自选、历史点击）

export type ScorableProduct = {
  code: string;
  name: string;
  pinyin?: string | null;
  pinyinInitials?: string | null;
  tags?: string | null; // JSON array 字符串
};

export type ScoreOptions = {
  inWatchlist?: boolean;
  clicks?: number;
  ftsHit?: boolean;
};

// B1：同一 tags 字符串不重复 JSON.parse（搜索打分对数百候选逐个调用）
const tagCache = new Map<string, string[]>();

export function parseTags(tags?: string | null): string[] {
  if (!tags) return [];
  const hit = tagCache.get(tags);
  if (hit) return hit;
  let parsed: string[] = [];
  try {
    const v = JSON.parse(tags);
    parsed = Array.isArray(v) ? v.map(String) : [];
  } catch {
    parsed = [];
  }
  // 缓存防膨胀：超上限直接清（tags 去重率高，LRU 收益有限，直接轮换即可）
  if (tagCache.size > 2000) tagCache.clear();
  tagCache.set(tags, parsed);
  return parsed;
}

export function scoreProduct(
  q: string,
  p: ScorableProduct,
  opts: ScoreOptions = {},
): number {
  const nq = q.trim().toLowerCase();
  if (!nq) return 0;

  const code = p.code.toLowerCase();
  const name = p.name.toLowerCase();
  const py = (p.pinyin ?? "").toLowerCase();
  const ini = (p.pinyinInitials ?? "").toLowerCase();

  let s = 0;
  const take = (v: number) => {
    if (v > s) s = v;
  };

  // 代码：精确 > 前缀（用户直接输入代码的场景）
  if (code === nq) take(100);
  else if (code.startsWith(nq)) take(60);

  // 名称：精确 > 前缀 > 包含
  if (name === nq) take(90);
  else if (name.startsWith(nq)) take(55);
  else if (name.includes(nq)) take(30);

  // 拼音
  if (py.startsWith(nq)) take(50);
  else if (py.includes(nq)) take(20);

  // 拼音首字母（如 gzmt → 贵州茅台）
  if (ini.startsWith(nq)) take(45);

  // 标签
  if (parseTags(p.tags).some((t) => t.toLowerCase().includes(nq))) take(15);

  // 仅由 FTS 命中的候选（如多元组部分匹配）
  if (opts.ftsHit && s === 0) s = 25;

  // 个性化加权
  if (opts.inWatchlist) s += 15;
  s += Math.min((opts.clicks ?? 0) * 3, 15);

  return s;
}
