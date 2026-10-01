-- 刀 1（#22(b)）：给 Product 的行情快照加"新鲜度时刻"列。
--
-- 为什么手写而不用 `prisma migrate dev`：本库有一批 Prisma 不认识的 SQLite **虚表**
-- （Product_fts / _config / _content / _data / _docsize / _idx，见
-- 20260911041104_product_fts 那份手写迁移）。`migrate dev` 的漂移比对会把它们判成
-- "schema 里不存在、应当 drop"，10-01 实测它就报了
--   You are about to drop the `Product_fts` table, which is not empty (35223 rows)
-- ——非交互环境下它自己停了，DB 未被触碰。所以本项目的加列一律手写 SQL + `migrate deploy`。
--
-- 语义：snapshotAt = 这一行的 lastPrice/lastChangePct 是哪一刻取到的；
-- null = 从未被快照刷新写过（list 阶段的全量替换不写它，见 web/lib/market-snapshot.ts）。

ALTER TABLE "Product" ADD COLUMN "snapshotAt" DATETIME;
