import { describe, expect, it } from "vitest";

import { buildIndustryView, type FundReportResp } from "./fund-industry";

// #65 刀 B（CR9-98）：行业配置上屏的判据面。
// 这一组要钉住的不是"能不能渲染"，而是**三态不许互相冒充**：ds 响应里
// 「上游说这只没披露」与「这一轮压根没取到」同形（都是 `industry: null`），
// 只有 `degraded`/`note` 能分开它们。把它们说成同一句＝CR9-26① 那句
// "列表失败却谎称已降级至备源"的同一族谎报。

function resp(patch: Partial<FundReportResp> = {}): FundReportResp {
  return { code: "110022", degraded: false, note: null, ...patch };
}

const ITEMS = [
  { name: "制造业", weight: 42.13 },
  { name: "金融业", weight: 18.02 },
  { name: "信息传输、软件和信息技术服务业", weight: 9.44 },
];

describe("buildIndustryView", () => {
  it("有数 ⇒ ok，并原样带出 asOf / items / source", () => {
    const v = buildIndustryView(
      resp({ industry: { asOf: "2026-09-30", items: ITEMS }, source: "akshare-fund-report" }),
      null,
    );
    expect(v.state).toBe("ok");
    if (v.state !== "ok") return;
    expect(v.asOf).toBe("2026-09-30");
    expect(v.items).toEqual(ITEMS);
    expect(v.source).toBe("akshare-fund-report");
  });

  it("顺序与截断只由 ds 一侧决定：给升序输入也不重排（两处各排一次迟早排出两个屏）", () => {
    const ascending = [...ITEMS].reverse();
    const v = buildIndustryView(resp({ industry: { asOf: "2026-09-30", items: ascending } }), null);
    expect(v.state).toBe("ok");
    if (v.state !== "ok") return;
    expect(v.items.map((x) => x.name)).toEqual(ascending.map((x) => x.name));
  });

  it("🔁 industry=null 且这一轮坏了（degraded/note）⇒ unavailable，**不许**读成「未披露」", () => {
    const v = buildIndustryView(resp({ industry: null, degraded: true, note: "eastmoney cooling down" }), null);
    expect(v.state).toBe("unavailable");
    if (v.state !== "unavailable") return;
    expect(v.text).toBe("eastmoney cooling down");
  });

  it("🔁 industry=null 而这一轮是好的 ⇒ undisclosed，字面就是仓库里已有的那句", () => {
    const v = buildIndustryView(resp({ industry: null }), null);
    expect(v.state).toBe("undisclosed");
    if (v.state !== "undisclosed") return;
    expect(v.text).toBe("行业配置未披露");
  });

  it("items 是空数组 ⇒ 不当有数上屏（空表渲染出来就是「该基金没有任何行业配置」的假陈述）", () => {
    const v = buildIndustryView(resp({ industry: { asOf: "2026-09-30", items: [] } }), null);
    expect(v.state).toBe("undisclosed");
  });

  it("整个响应没拿到 ⇒ unavailable，原因取调用方给的那一句（与持仓区 holdingsError 同口径）", () => {
    const v = buildIndustryView(null, "行业配置获取失败");
    expect(v.state).toBe("unavailable");
    if (v.state !== "unavailable") return;
    expect(v.text).toBe("行业配置获取失败");
  });

  it("没拿到且连原因都没有 ⇒ 落到「数据源缺失」，不许交空串上屏", () => {
    const v = buildIndustryView(null, null);
    expect(v.state).toBe("unavailable");
    if (v.state !== "unavailable") return;
    expect(v.text).toBe("数据源缺失");
  });

  it("asOf 是空串 ⇒ 归一成 null（标题退回「行业配置」，不会渲染出「行业配置截至 」这种半句）", () => {
    const v = buildIndustryView(resp({ industry: { asOf: "", items: ITEMS } }), null);
    expect(v.state).toBe("ok");
    if (v.state !== "ok") return;
    expect(v.asOf).toBeNull();
  });

  it("note 有字而 degraded=false 也算「这一轮坏了」（ds 侧 degraded 只在 ProviderError 那一支置真）", () => {
    const v = buildIndustryView(resp({ industry: null, degraded: false, note: "timeout" }), null);
    expect(v.state).toBe("unavailable");
  });
});
