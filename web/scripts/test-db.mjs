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
  // 注意：不得使用无 where 的 chatMessage.deleteMany({})——那会清空开发库中
  // **全部真实会话消息**（2026-09-13 code review 发现的不可逆数据丢失风险）。
  // 级联删除已由上面的断言验证，无需额外清理。

  // 6. 主数据类型完整率（CR9-26①）：hk/crypto 长期 0 行却从未被任何门禁看见，
  // 根因是 groupBy **压根不返回零行类型**——"静默"就是这个机制。故先按六类补零，
  // 再断两件可失败的事：① 补零后的分类型合计 == 全表行数（出现未声明的第七类即红）；
  // ② 已有主数据的类型不得跌回 0 行（同步写坏/误清库的兜底观测）。
  {
    const ALL_TYPES = ["stock", "fund", "bond", "hk", "us", "crypto"];
    const grouped = await p.product.groupBy({ by: ["type"], _count: { _all: true } });
    const counts = Object.fromEntries(ALL_TYPES.map((t) => [t, 0]));
    for (const g of grouped) counts[g.type] = g._count._all;
    const total = await p.product.count();
    const sum = ALL_TYPES.reduce((a, t) => a + counts[t], 0);
    const present = ALL_TYPES.filter((t) => counts[t] > 0);
    const missing = ALL_TYPES.filter((t) => counts[t] === 0);
    check(
      "主数据按类型合计与全表行数吻合（无未声明类型被静默）",
      sum === total,
      `sum=${sum} total=${total} grouped=${JSON.stringify(grouped)}`,
    );
    check(
      "已有主数据的类型未跌回 0 行（stock/fund/bond/us）",
      ["stock", "fund", "bond", "us"].every((t) => counts[t] > 0),
      `counts=${JSON.stringify(counts)}`,
    );
    console.log(
      `  主数据类型完整率 ${present.length}/6｜${ALL_TYPES.map((t) => `${t}=${counts[t]}`).join(" ")}` +
        (missing.length ? `｜缺口：${missing.join(",")}（可达性属 CR9-26，未静默）` : ""),
    );
  }
} finally {
  await p.$disconnect();
}

const fails = results.filter((r) => !r[1]);
console.log(`\n===== ${results.length - fails.length}/${results.length} 通过 =====`);
if (fails.length) {
  for (const [name, , detail] of fails) console.log(`  - ${name}: ${detail}`);
  process.exit(1);
}
