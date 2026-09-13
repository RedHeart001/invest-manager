import { PrismaClient } from "@prisma/client";
const p = new PrismaClient();
const rows = [];
for (const m of ["product","klineDaily","hotspotDigest","researchReport","chatSession","chatMessage","syncState"]) {
  try { rows.push(`${m}=${await p[m].count()}`); } catch (e) { rows.push(`${m}=ERR`); }
}
const byType = await p.product.groupBy({ by: ["type"], _count: true });
rows.push("types: " + byType.map((x) => `${x.type}:${x._count}`).join(" "));
console.log(rows.join(" | "));
await p.$disconnect();
