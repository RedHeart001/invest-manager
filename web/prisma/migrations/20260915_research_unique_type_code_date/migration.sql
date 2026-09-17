-- R4（2026-09-15 code review）：研报去重键缺 type → A股/基金代码段重叠
-- （如 000001 = 平安银行 stock / 华夏成长混合 fund）会跨类型串研报、
-- 同日双类型 ingest 互相覆盖。唯一键升级为 (type, code, date)（对齐 KlineDaily）。
DROP INDEX "ResearchReport_code_date_key";
CREATE UNIQUE INDEX "ResearchReport_type_code_date_key" ON "ResearchReport"("type", "code", "date");
