// #65 刀 B（CR9-98，10-13 主人的字＝「行业配置要上屏」）：把 ds `/fund/report` 的
// 行业配置那一块映成屏上要的视图模型。
//
// 为什么单独一个纯函数：这一块有**三态**（有数／上游说没披露／这一轮取不到），而后两态在
// 响应里长得一模一样（`industry: null`）⇒ 只能靠 `degraded`/`note` 分开。不分开就会把
// "这一轮没连上"说成"该基金未披露"——与 CR9-26① 那句列表失败却谎称"已降级至备源"同族。
//
// 文案沿用仓库里已有的那两句（`web/lib/tools.ts:390-394` 的「行业配置截至 X」／「行业配置未披露」），
// 不新造屏幕上的字（屏上文案归主人定；这里只是把 MCP 工具侧已有的措辞复用到页面）。

export type FundReportResp = {
  code: string;
  degraded: boolean;
  note: string | null;
  reports?: { title: string; date: string; id: string }[];
  industry?: { asOf: string; items: { name: string; weight: number }[] } | null;
  source?: string;
};

export type IndustryView =
  | {
      state: "ok";
      asOf: string | null;
      items: { name: string; weight: number }[];
      source: string | null;
    }
  | { state: "undisclosed"; text: string }
  | { state: "unavailable"; text: string };

/**
 * @param resp        ds 的响应；`null`＝这一轮压根没拿到（超时/抛错/不是场外基金）
 * @param fetchError  拿不到时的原因文字（与持仓区同一口径：`holdingsError`）
 */
export function buildIndustryView(
  resp: FundReportResp | null,
  fetchError: string | null,
): IndustryView {
  if (resp == null) return { state: "unavailable", text: fetchError ?? "数据源缺失" };
  const ind = resp.industry;
  if (ind && Array.isArray(ind.items) && ind.items.length > 0) {
    // 顺序与截断都由 ds 一侧给（`akshare_provider.py` 已按 weight 降序、取前 10）⇒
    // 这里**不重排、不再截**：一处排序两个地方各排一次，迟早排出两个不同的屏。
    return {
      state: "ok",
      asOf: ind.asOf || null,
      items: ind.items,
      source: resp.source ?? null,
    };
  }
  // industry 空：这一轮坏了（degraded/note）与上游说没披露，必须是两句话
  if (resp.degraded || resp.note) return { state: "unavailable", text: resp.note ?? "数据源缺失" };
  return { state: "undisclosed", text: "行业配置未披露" };
}
