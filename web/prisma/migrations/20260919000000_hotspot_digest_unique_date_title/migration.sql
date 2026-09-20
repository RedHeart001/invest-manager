-- CR-11（本轮 code review）：HotspotDigest 去重键 (date, title) 此前只在应用层
-- 「先查后写」，且无唯一索引 → 并发 ingest（多 web 实例 / 定时与手动同时触发）时
-- 同批标题可同时通过检查 → 同日同标题重复行 → Dashboard 重复卡片。
--
-- 先清理历史重复行（同 date+title 只保留最早插入的一行，按 rowid 判定），
-- 再建唯一索引，使并发写入被数据库拦截（应用层配合改 upsert）。
DELETE FROM "HotspotDigest"
WHERE rowid NOT IN (
  SELECT MIN(rowid) FROM "HotspotDigest" GROUP BY "date", "title"
);

CREATE UNIQUE INDEX "HotspotDigest_date_title_key" ON "HotspotDigest"("date", "title");
