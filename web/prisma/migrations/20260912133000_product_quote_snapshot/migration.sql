-- R14 分类浏览：Product 行情快照列（手工迁移；FTS5 虚表由应用层维护，
-- 不纳入 Prisma migrate，避免 migrate dev 漂移检测误删）
ALTER TABLE "Product" ADD COLUMN "lastPrice" FLOAT;
ALTER TABLE "Product" ADD COLUMN "lastChangePct" FLOAT;
