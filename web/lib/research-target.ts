// 研报意图的标的提取（2026-09-14 code review 修复）：
// A股 6 位数字优先；其次 3~5 位大写字母美股代码。
// 常规金融缩写（ETF/IPO/GDP/ROE…）会被 `\b[A-Z]{3,5}\b` 误判为美股 ticker
// （用户问"深度分析一下 ETF 基金" → 误为标的 ETF 启动研报）→ 用停用词表排除。

const TICKER_STOPWORDS = new Set([
  "ETF", "LOF", "IPO", "GDP", "CPI", "PPI", "PMI", "ROE", "ROA", "PE", "PB",
  "EPS", "NAV", "AI", "QDII", "REIT", "ST", "USD", "CNY", "RMB",
]);

export type ResearchTarget = { type: "stock" | "us"; code: string };

/** 从用户消息中提取深度研究标的；无法可靠识别时返回 null */
export function extractResearchTarget(message: string): ResearchTarget | null {
  const stock = message.match(/\b(\d{6})\b/);
  if (stock) return { type: "stock", code: stock[1] };
  const us = message.match(/\b([A-Z]{3,5})\b/);
  if (us && !TICKER_STOPWORDS.has(us[1])) return { type: "us", code: us[1] };
  return null;
}
