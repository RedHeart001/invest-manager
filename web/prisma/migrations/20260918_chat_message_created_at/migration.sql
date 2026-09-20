-- CR6-P2-6（2026-09-18 code review）：ChatMessage 缺真实时间戳。
-- 此前 getMessages 用 cuid 主键冒充 createdAt：cuid 大致时间有序但不保证
-- 字典序等价于插入序，极端并发下 orderBy id 会错序 → 影响送进 LLM 的历史顺序。
-- SQLite 的 ADD COLUMN 不支持非常量 DEFAULT，故用表重建（与 Prisma 生成风格一致），
-- 落到与 schema 声明一致的 `createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`。
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_ChatMessage" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "sessionId" TEXT NOT NULL,
    "role" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "toolCalls" TEXT,
    "toolCallId" TEXT,
    "name" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ChatMessage_sessionId_fkey" FOREIGN KEY ("sessionId") REFERENCES "ChatSession" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
-- 历史行无真实时间：回填当前时刻（顺序性以真实列为准，旧行相对顺序由 id 兜底）
INSERT INTO "new_ChatMessage" ("content", "id", "role", "sessionId", "toolCalls", "toolCallId", "name", "createdAt")
SELECT "content", "id", "role", "sessionId", "toolCalls", "toolCallId", "name", datetime('now') FROM "ChatMessage";
DROP TABLE "ChatMessage";
ALTER TABLE "new_ChatMessage" RENAME TO "ChatMessage";
CREATE INDEX "ChatMessage_sessionId_idx" ON "ChatMessage"("sessionId");
CREATE INDEX "ChatMessage_sessionId_createdAt_idx" ON "ChatMessage"("sessionId", "createdAt");
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;
