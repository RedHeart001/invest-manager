// 币种展示（CR7-4/B2c，2026-09-24 拍板）
//
// 背景：provider 侧 hk/us/sina-bond 早已返回 `currency` 字段，但 TS 契约
// 与展示层全没接——港股在列表与详情页显示成无单位数字（100 实为 100 港币）。
//
// 文案拍板：`419.00 港币`（后缀中文单位）。CNY 保持现状不加单位（A 股语境
// 下"419.00"即人民币，加"元"反而冗余）；映射仅两项，未知值透传原文。
// 纯函数零依赖（与 research-stale / chat-stream-exit 同套路，可单测）。

const CURRENCY_LABEL: Record<string, string> = {
  HKD: "港币",
  USD: "美元",
};

/**
 * 为价格追加币种单位：`currency ∉ {CNY, null, undefined}` 时返回
 * `419.00 港币` 形态；CNY/缺失时原样返回数值文本。
 */
export function priceWithCurrency(
  priceText: string,
  currency?: string | null,
): string {
  if (!currency || currency === "CNY") return priceText;
  const label = CURRENCY_LABEL[currency];
  return label ? `${priceText} ${label}` : `${priceText} ${currency}`;
}
