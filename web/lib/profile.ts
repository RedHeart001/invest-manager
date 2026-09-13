// 规则模板画像（PLAN M3 身份区定稿：不用 LLM，零延迟、可单测、无幻觉）
// 字段缺失时逐项降级，绝不编造。

import type { Quote } from "@/lib/data-service";

export type ProductLike = {
  type: string;
  name: string;
  code: string;
  exchange: string | null;
  tags: string[];
};

export type QuoteEnriched = Quote & {
  marketCap?: number | null;
  floatCap?: number | null;
  peTtm?: number | null;
  peDyn?: number | null;
  pb?: number | null;
  turnover?: number | null;
  marketCapRank?: number | null;
};

function fmtCap(v: number | null | undefined): string | null {
  if (v == null || !Number.isFinite(v) || v <= 0) return null;
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)} 万亿`;
  if (v >= 1e8) return `${(v / 1e8).toFixed(0)} 亿`;
  return `${(v / 1e4).toFixed(0)} 万`;
}

function fmtNum(v: number | null | undefined, digits = 2): string | null {
  if (v == null || !Number.isFinite(v)) return null;
  return v.toFixed(digits);
}

function exchangeLabel(exchange: string | null): string | null {
  if (exchange === "SH") return "沪市";
  if (exchange === "SZ") return "深市";
  if (exchange === "BJ") return "北交所";
  return null;
}

/** 场内基金（ETF/LOF）判定：与 data-service 前缀规则一致 */
const ETF_PREFIXES = ["15", "16", "18", "50", "51", "52", "53", "56", "58"];

export function isExchangeTradedFund(code: string): boolean {
  return ETF_PREFIXES.some((p) => code.startsWith(p));
}

/** 一句话画像：按类型模板拼接，全部字段缺失时返回降级文案 */
export function buildProfile(
  product: ProductLike,
  quote: QuoteEnriched | null,
): string {
  const parts: string[] = [];
  const tags = product.tags.filter(Boolean);

  if (product.type === "stock") {
    const ex = exchangeLabel(product.exchange);
    if (ex) parts.push(`${ex}A股`);
    parts.push(...tags);
    const cap = fmtCap(quote?.marketCap);
    if (cap) parts.push(`总市值 ${cap}`);
    const pe = fmtNum(quote?.peTtm);
    if (pe) parts.push(`PE(TTM) ${pe}`);
    const pb = fmtNum(quote?.pb);
    if (pb) parts.push(`PB ${pb}`);
  } else if (product.type === "fund") {
    // P1 同步的场外基金 tags[0] 为基金类型（股票型/混合型…）
    parts.push(...tags);
    parts.push(isExchangeTradedFund(product.code) ? "场内基金" : "场外基金");
    if (quote?.price != null) parts.push(`单位净值 ${quote.price.toFixed(4)}`);
  } else if (product.type === "bond") {
    parts.push(...tags);
    if (!tags.includes("可转债")) parts.push("可转债");
    const ex = exchangeLabel(product.exchange);
    if (ex) parts.push(ex);
  } else if (product.type === "crypto") {
    parts.push("加密货币");
    if (quote?.marketCapRank != null) parts.push(`市值排名第 ${quote.marketCapRank}`);
  }

  const out = [...new Set(parts.filter(Boolean))].join(" · ");
  return out || "暂无画像数据（字段缺失）";
}
