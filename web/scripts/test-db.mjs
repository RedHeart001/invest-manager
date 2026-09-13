// P0 数据库层测试：表结构、迁移、唯一索引、Prisma Client 写读删回环。
// 运行：node scripts/test-db.mjs（需先 prisma migrate dev）

import { PrismaClient } from "@prisma/client";

const p = new PrismaClient();
const results = [];

function check(name, cond, detail = "") {
  results.push([name, !!cond, detail]);
  console.log(`[${cond ? "PASS" : "FAIL"}] ${name}` + (cond ? "" : `  <- ${detail}`));
}

try {
  // 1. 迁移已应用（SQLite COUNT 经 Prisma 返回 BigInt）
  const mig = await p.$queryRaw`SELECT COUNT(*) AS c FROM _prisma_migrations`;
  const migCount = Number(mig[0].c);
  check("迁移已应用（count >= 1）", migCount >= 1, `count=${migCount}`);

  // 2. 8 张业务表全部存在
  const tables = (
    await p.$queryRaw`SELECT name FROM sqlite_master WHERE type='table'`
  ).map((r) => r.name);
  const expected = [
    "Product",
    "HotspotDigest",
    "ResearchReport",
    "ChatSession",
    "ChatMessage",
    "Watchlist",
    "SearchClickLog",
    "KlineDaily",
  ];
  for (const t of expected) {
    check(`表存在：${t}`, tables.includes(t), `tables=${tables.join(",")}`);
  }

  // 3. 关键唯一索引
  const indexes = (
    await p.$queryRaw`SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'`
  ).map((r) => r.name);
  check(
    "唯一索引 Product(type,code)",
    indexes.includes("Product_type_code_key"),
    indexes.join(",")
  );
  check(
    "唯一索引 KlineDaily(type,code,date)",
    indexes.includes("KlineDaily_type_code_date_key"),
    indexes.join(",")
  );

  // 4. Prisma Client 写/读/删回环
  await p.product.upsert({
    where: { type_code: { type: "stock", code: "TEST001" } },
    update: { name: "测试标的" },
    create: { type: "stock", code: "TEST001", name: "测试标的", tags: '["测试"]' },
  });
  const found = await p.product.findUnique({
    where: { type_code: { type: "stock", code: "TEST001" } },
  });
  check("Prisma Client upsert + findUnique 回环", found?.name === "测试标的", JSON.stringify(found));

  // 唯一约束冲突应抛错
  let dupRejected = false;
  try {
    await p.product.create({ data: { type: "stock", code: "TEST001", name: "重复" } });
  } catch {
    dupRejected = true;
  }
  check("唯一约束生效（重复插入被拒绝）", dupRejected);

  await p.product.deleteMany({ where: { code: "TEST001" } });
  const leftover = await p.product.count({ where: { code: "TEST001" } });
  check("测试数据已清理（不影响真实产品数据）", leftover === 0, `leftover=${leftover}`);

  // 5. ChatSession/ChatMessage 外键 + 级联删除
  const s = await p.chatSession.create({ data: { title: "测试会话" } });
  await p.chatMessage.create({
    data: { sessionId: s.id, role: "user", content: "hello" },
  });
  const msgs = await p.chatMessage.findMany({ where: { sessionId: s.id } });
  check("ChatSession/ChatMessage 外键关系", msgs.length === 1);
  await p.chatSession.delete({ where: { id: s.id } });
  const remaining = await p.chatMessage.count({ where: { sessionId: s.id } });
  check("删除会话级联删除其消息", remaining === 0, `remaining=${remaining}`);
  await p.chatMessage.deleteMany({});
} finally {
  await p.$disconnect();
}

const fails = results.filter((r) => !r[1]);
console.log(`\n===== ${results.length - fails.length}/${results.length} 通过 =====`);
if (fails.length) {
  for (const [name, , detail] of fails) console.log(`  - ${name}: ${detail}`);
  process.exit(1);
}
