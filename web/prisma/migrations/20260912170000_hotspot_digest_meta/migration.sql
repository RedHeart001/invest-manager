-- P3 热点 digest 降级标注字段（R12/R10：digest 与界面显式标注降级状态）
-- 手工迁移（FTS5 与应用层表不纳入 Prisma migrate 漂移管理）
ALTER TABLE "HotspotDigest" ADD COLUMN "newsSource" TEXT;
ALTER TABLE "HotspotDigest" ADD COLUMN "engine" TEXT;
ALTER TABLE "HotspotDigest" ADD COLUMN "degraded" BOOLEAN;
ALTER TABLE "HotspotDigest" ADD COLUMN "note" TEXT;
