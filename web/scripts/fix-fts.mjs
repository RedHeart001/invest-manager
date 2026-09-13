// 一次性数据修复：FTS 孤儿清理 + 缺失行补齐 + 残留暂存表清除（C15 配套）
import { PrismaClient } from "@prisma/client";

const p = new PrismaClient();
const q = (sql) => p.$queryRawUnsafe(sql);
const c = async (sql) => Number((await q(sql))[0].c);

const before = {
  product: await c("SELECT COUNT(*) c FROM Product"),
  fts: await c("SELECT COUNT(*) c FROM Product_fts"),
  orphan: await c("SELECT COUNT(*) c FROM Product_fts WHERE productId NOT IN (SELECT id FROM Product)"),
  missing: await c("SELECT COUNT(*) c FROM Product WHERE id NOT IN (SELECT productId FROM Product_fts)"),
};
console.log("before:", JSON.stringify(before));

const delOrphan = await p.$executeRawUnsafe(
  "DELETE FROM Product_fts WHERE productId NOT IN (SELECT id FROM Product)",
);
console.log(`删除孤儿 FTS 行: ${delOrphan}`);

const insMissing = await p.$executeRawUnsafe(
  `INSERT INTO Product_fts(productId, searchText)
   SELECT id, COALESCE(searchText, '') FROM Product
   WHERE id NOT IN (SELECT productId FROM Product_fts)`,
);
console.log(`补齐缺失 FTS 行: ${insMissing}`);

// 残留暂存表（L1 遗留；修复后代码已改为 DROP）
const stages = await q(
  "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Product\\_stage\\_%' ESCAPE '\\'",
);
for (const s of stages) {
  await p.$executeRawUnsafe(`DROP TABLE IF EXISTS "${s.name}"`);
  console.log(`已清理残留暂存表: ${s.name}`);
}

const after = {
  product: await c("SELECT COUNT(*) c FROM Product"),
  fts: await c("SELECT COUNT(*) c FROM Product_fts"),
  orphan: await c("SELECT COUNT(*) c FROM Product_fts WHERE productId NOT IN (SELECT id FROM Product)"),
  missing: await c("SELECT COUNT(*) c FROM Product WHERE id NOT IN (SELECT productId FROM Product_fts)"),
};
console.log("after:", JSON.stringify(after));
console.log(
  after.product === after.fts && after.orphan === 0 && after.missing === 0
    ? "RESULT: PASS（FTS 与 Product 完全一致）"
    : "RESULT: FAIL",
);

// 顺带验证搜索可用（转债关键词走 FTS）
const hit = await q("SELECT COUNT(*) c FROM Product_fts WHERE Product_fts MATCH 'zhuanzhai'");
console.log(`FTS 检索 smoke（zhuanzhai）命中=${hit[0].c}`);

await p.$disconnect();
