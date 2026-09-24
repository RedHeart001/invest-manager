// 产品代码字符集校验（单一来源，CR7-6/C5 前置抽取）
//
// 此前该正则硬写在 research/start 与 watchlist 两处；B1 新增的 verify 路由
// 按账本约束也须同口径——非法 code 必须在调用 data-service 之前 400，
// 不得消耗外部数据源额度（东财 rate_per_min=12）。
export const CODE_SET = /^[\w.-]{1,20}$/;

/** 行情/研报取数允许的产品类型白名单（BFF 侧防御；ds 侧另有 400 语义） */
export const QUOTE_TYPES = ["stock", "fund", "bond", "crypto", "hk", "us"] as const;
