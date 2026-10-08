// #55 甲（10-08 主人手测 `/product/us/CEG` 报回「粘贴美股没数据」）：K 线空态要说明**为什么没有**。
//
// 此前 `ProductCharts.tsx:519` 在 0 根时固定渲染「暂无行情数据」，而成因一直在 `KlineResult.note`
// 里（`lib/kline.ts` 的 8 处 `notes.push`）——只是从没上屏。现网实测形态＝ds 的 502 detail 原样
// 透传，21:58 探针 `us-kline-probe2-1008.out` 的字面是：
//   all sources failed: yfinance: yfinance kline failed: Too Many Requests. Rate limited.
//   Try after a while.; tencent: tencent does not support code: CEG
// 那是写给开发看的英文长句，直接上屏既不是一行、也不是人话。
//
// 归一的红线＝**只压缩、不编造**：note 里没有的话一句不说。上面那枚实测里 yfinance 那一支是
// 429（此刻限流＝暂时），tencent 那一支才是不提供 us（永久）——两支混在 `all sources failed`
// 里，所以能诚实说的只有"试过的几家都没给"；"美股日线只有一家源"这类话属于 #55 乙／丙，
// 必须先实测才允许上屏。
//
// 顺序＝最强断言在前：`all sources failed` 是链的固定前缀，`data-service/app/providers/chain.py:37`
// 只在**每一家都失败**时才走到那一行 ⇒ 它比任何单个子句更能代表整体。把它排第一，避免把
// "两家都试过"降级成"一家在限流"。

/** 屏上一行的上限：中文 60 字足够说完一句成因，又不会把那一格撑成两行。 */
const MAX_LEN = 60;

const RULES: { readonly test: RegExp; readonly text: string }[] = [
  { test: /all sources failed/i, text: "试过的数据源都没给这个品种的日线" },
  { test: /均无|返回空|空数据|got nothing/i, text: "数据源返回了空内容" },
  {
    test: /限流|429|too many requests|rate limit|窗口期|暂不|不再尝试|冷却|cooling/i,
    text: "数据源暂时取不到（限流或故障），窗口期内不重试",
  },
  { test: /不支持|does not support|not supported/i, text: "数据源不提供这个品种" },
  {
    test: /超时|timeout|连接|connection|remotedisconnected|网络|network/i,
    text: "数据源连不上",
  },
];

/** `notes.push(`回源失败：${…}`)` 这类自家前缀对读屏的人没有信息量，去掉后再判/再截。 */
const LEADING_LABEL = /^(?:历史区间|增量)?(?:回源)?失败[：:]/;

/**
 * 把 `KlineResult.note` 归一成一句人话；没有成因（note 为空）时返回 `null`，
 * 调用方**不许**替它编一个原因。
 */
export function klineEmptyReason(note: string | null | undefined): string | null {
  const raw = note?.trim();
  if (!raw) return null;
  const body = raw.replace(LEADING_LABEL, "");
  const hit = RULES.find((r) => r.test.test(body));
  if (hit) return hit.text;
  // 表里没有的形态：原样带出（截断），宁可不漂亮也不丢信息——静默改判"暂无数据"
  // 就是本条要消灭的那个形状。
  return body.length > MAX_LEN ? `${body.slice(0, MAX_LEN)}…` : body;
}

/** 空态那一格的字面：有成因就带上，没有就只说"暂无"。 */
export function klineEmptyText(note: string | null | undefined): string {
  const reason = klineEmptyReason(note);
  return reason ? `暂无行情数据 · ${reason}` : "暂无行情数据";
}
