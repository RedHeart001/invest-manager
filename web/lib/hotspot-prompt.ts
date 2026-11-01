// R19（2026-11-02）：热点卡「去分析」→ /chat?prompt= 预填。
// prompt 只由既有数据（标题＋摘要）拼接，不新增固定文案；chat 页只预填、不自动发送。
export function buildHotspotChatHref(row: { title: string; summary: string }): string {
  const prompt = `热点深入分析：${row.title}${row.summary ? `\n${row.summary}` : ""}`;
  return `/chat?prompt=${encodeURIComponent(prompt)}`;
}
