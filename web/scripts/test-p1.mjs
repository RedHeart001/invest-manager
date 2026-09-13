// P1 验收测试：搜索 API（多模式检索/排序/过滤/边界）、点击加权、
// UI 约定（面包屑/导航高亮/骨架屏）、数据完整性。
// 运行：node scripts/test-p1.mjs（需 web 与 data-service 均已启动）

import { PrismaClient } from "@prisma/client";

const BASE = process.env.WEB_URL ?? "http://localhost:3000";
const prisma = new PrismaClient();
const results = [];

function check(name, cond, detail = "") {
  results.push([name, !!cond, detail]);
  console.log(`[${cond ? "PASS" : "FAIL"}] ${name}${cond ? "" : `  <- ${String(detail).slice(0, 180)}`}`);
}

async function search(q, type = "all", limit = 10) {
  const res = await fetch(
    `${BASE}/api/search?q=${encodeURIComponent(q)}&type=${type}&limit=${limit}`,
  );
  return { status: res.status, body: await res.json() };
}

try {
  // ---------- 1. 多模式检索与排序 ----------
  let r = await search("600519");
  check(
    "代码精确检索：600519 首位且基础分满分（100 + 个性化加权 ≤15）",
    r.body.results?.[0]?.code === "600519" &&
      r.body.results[0].score >= 100 &&
      r.body.results[0].score <= 115,
    JSON.stringify(r.body.results?.[0]),
  );

  r = await search("贵州茅台");
  check(
    "名称检索：贵州茅台居首且分数高于其他命中",
    r.body.results?.[0]?.name === "贵州茅台" &&
      r.body.results[0].score > (r.body.results[1]?.score ?? 0),
    JSON.stringify(r.body.results?.slice(0, 3)),
  );

  r = await search("gzmt");
  check(
    "拼音首字母检索命中贵州茅台",
    r.body.results?.some((x) => x.code === "600519"),
    JSON.stringify(r.body.results?.slice(0, 2)),
  );

  r = await search("华夏成长", "fund");
  check(
    "基金名称检索（类别过滤 + 前缀命中）",
    r.body.results?.length > 0 && r.body.results.every((x) => x.type === "fund"),
    JSON.stringify(r.body.results?.slice(0, 2)),
  );

  // ---------- 2. 行情富集 ----------
  r = await search("新能源", "fund", 5);
  check(
    "基金结果行情富集（含价格与涨跌幅）",
    r.body.results?.some((x) => x.price != null && x.changePct != null),
    JSON.stringify(r.body.results?.[0]),
  );

  r = await search("强达转债", "bond", 3);
  check(
    "可转债结果行情富集",
    r.body.results?.some((x) => x.price != null),
    JSON.stringify(r.body.results?.[0]),
  );

  // ---------- 3. 过滤与边界 ----------
  r = await search("茅台", "bond");
  check("类别过滤生效（债券类别下无茅台）", r.status === 200 && r.body.count === 0, JSON.stringify(r.body));

  r = await search("");
  // R14（P2）起：空关键词进入分类浏览模式（browse 结构），不再是"空结果"
  // （2026-09-13 代码审查时更新此过时断言）
  check(
    "空查询进入浏览模式而非报错",
    r.status === 200 && r.body.browse === true && Array.isArray(r.body.items),
    `status=${r.status} body=${JSON.stringify(r.body).slice(0, 120)}`,
  );

  r = await search('茅台" OR "贵州');
  check("FTS 特殊字符不导致 500", r.status === 200, `status=${r.status}`);

  r = await search("zzz不存在的标的999");
  check(
    "无命中查询返回空列表",
    r.status === 200 && Array.isArray(r.body.results) && r.body.count === 0,
    `status=${r.status} count=${r.body.count}`,
  );

  // ---------- 4. 点击加权闭环（含测试数据清理） ----------
  const started = new Date();
  const before = (await search("平安银行", "stock", 1)).body.results[0];
  await fetch(`${BASE}/api/search/click`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: "平安银行", type: "stock", code: "000001" }),
  });
  const after = (await search("平安银行", "stock", 1)).body.results[0];
  check("点击一次后排序分 +3", after.score === before.score + 3, `${before.score} -> ${after.score}`);

  const del = await prisma.searchClickLog.deleteMany({
    where: { query: "平安银行", ts: { gte: started } },
  });
  check("测试点击记录已清理", del.count >= 1, `deleted=${del.count}`);

  const badRes = await fetch(`${BASE}/api/search/click`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: "x" }),
  });
  check("点击接口缺字段 → 400", badRes.status === 400, `status=${badRes.status}`);

  // ---------- 5. UI 约定（SSR HTML） ----------
  const searchHtml = await (await fetch(`${BASE}/search?q=600519`)).text();
  check("搜索页含面包屑", searchHtml.includes('aria-label="面包屑"'));
  check("顶部导航高亮（aria-current）", searchHtml.includes('aria-current="page"'));

  const productHtml = await (await fetch(`${BASE}/product/stock/600519`)).text();
  check(
    "详情页面包屑含当前标的",
    productHtml.includes('aria-label="面包屑"') && productHtml.includes("贵州茅台"),
  );
  check("详情页流式骨架屏（loading.tsx 生效）", productHtml.includes("animate-pulse"));

  // ---------- 6. 数据完整性 ----------
  const counts = {};
  for (const t of ["stock", "fund", "bond"]) {
    counts[t] = await prisma.product.count({ where: { type: t } });
  }
  check(
    "产品主数据齐备（stock>5000 / fund>20000 / bond>500）",
    counts.stock > 5000 && counts.fund > 20000 && counts.bond > 500,
    JSON.stringify(counts),
  );

  const fts = Number((await prisma.$queryRawUnsafe("SELECT COUNT(*) AS c FROM Product_fts"))[0].c);
  // 口径修正（2026-09-13）：含全部类型（P5 新增 us，如 AAPL）——此前仅算 stock/fund/bond 导致误报
  const allCounts = await prisma.product.groupBy({ by: ["type"], _count: true });
  const total = allCounts.reduce((s, x) => s + Number(x._count), 0);
  check(
    "FTS 索引行数与产品总数一致",
    fts === total,
    `fts=${fts} products=${total}（${allCounts.map((x) => `${x.type}:${x._count}`).join(" ")}）`,
  );

  const withText = await prisma.product.findFirst({
    where: { type: "stock", searchText: { not: null } },
    select: { searchText: true },
  });
  check("searchText 已构建（含二元组/拼音）", (withText?.searchText ?? "").includes(" "));
} finally {
  await prisma.$disconnect();
}

const fails = results.filter((r) => !r[1]);
console.log(`\n===== ${results.length - fails.length}/${results.length} 通过 =====`);
if (fails.length) {
  for (const [name, , detail] of fails) console.log(`  - ${name}: ${String(detail).slice(0, 180)}`);
  process.exit(1);
}
