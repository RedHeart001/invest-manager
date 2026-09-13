-- P4 会话消息：function calling 配对字段
-- 手工迁移（FTS5 与应用层表不纳入 Prisma migrate 漂移管理）
ALTER TABLE "ChatMessage" ADD COLUMN "toolCallId" TEXT;
ALTER TABLE "ChatMessage" ADD COLUMN "name" TEXT;
