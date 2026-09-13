-- FTS5 全文索引：产品搜索（P1）
-- searchText 由 BFF 在同步时构建（名称 + 中文二元组 + 拼音 + 首字母 + 代码 + 标签），
-- 二元组展开用于中文子串匹配（unicode61 不切分中文）。
-- contentless 设计：索引内容由 sync 全量重建（见 web/lib/sync.ts rebuildFts）。
CREATE VIRTUAL TABLE IF NOT EXISTS "Product_fts" USING fts5(
  productId UNINDEXED,
  searchText,
  tokenize = 'unicode61 remove_diacritics 2'
);
