-- P5 研报失败原因字段（任务熔断 / 提交失败时落库）
-- 手工迁移（FTS5 与应用层表不纳入 Prisma migrate 漂移管理）
ALTER TABLE "ResearchReport" ADD COLUMN "error" TEXT;
