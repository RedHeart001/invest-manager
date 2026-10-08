import { describe, expect, it } from "vitest";

import { FROM_LABEL, hrefForFrom, parseFrom, planBack } from "./provenance";

// 来路驱动（2026-10-01）：`?from=` 是外部输入（用户可手改 URL），白名单与返回目标
// 推导都收在这个模块里 ⇒ 单测判逻辑，SSR 侧的四种来路由 test-p1 判。

describe("parseFrom（白名单）", () => {
  it("① 三个合法来路各自通过，标签齐全", () => {
    expect(["search", "home", "chat"].map(parseFrom)).toEqual(["search", "home", "chat"]);
    expect(Object.keys(FROM_LABEL).sort()).toEqual(["chat", "home", "search"]);
  });

  it("② 🔁 反向：白名单外一律当作「没有来路」（不得被当成一级去点亮）", () => {
    expect([null, undefined, "", "product", "SEARCH", "chat;rm", "/../"].map(parseFrom)).toEqual([
      null,
      null,
      null,
      null,
      null,
      null,
      null,
    ]);
  });
});

describe("hrefForFrom（无历史时的确定目标）", () => {
  it("③ search 带 q 时重建搜索现场", () => {
    expect(hrefForFrom("search", "贵州茅台")).toBe("/search?q=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0");
  });

  it("③b search 无 q（浏览态进来）退回 /search 本体，不造 /search?q=", () => {
    expect(hrefForFrom("search", null)).toBe("/search");
    expect(hrefForFrom("search", "")).toBe("/search");
  });

  it("③c home→首页、chat→智能助手", () => {
    expect([hrefForFrom("home", null), hrefForFrom("chat", null)]).toEqual(["/", "/chat"]);
  });
});

// #56 甲（10-08 主人手测「粘贴链接后点返回没反应」）：返回按钮的文案与行为必须同源。
// 旧实现文案按 `from`、行为按 `window.history.length > 1`，而历史条目数会把 about:blank、
// 新标签、同一 URL 重复回车都算成"可回退" ⇒ 承诺与目的地可以指向两个不同地方。
describe("planBack（文案与行为取同一个键）", () => {
  it("④ URL 带白名单内 from＝应用内进入 ⇒ 承诺来路且用 back()", () => {
    expect(planBack("search", "贵州茅台", null)).toEqual({
      label: "← 返回搜索",
      useHistoryBack: true,
      fallbackHref: "/search?q=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0",
    });
  });

  it("⑤ URL 不带 from、会话里有来路 ⇒ 文案不承诺，行为必须 push（他那一屏的形状）", () => {
    // sessionStorage 残留 home 时，旧实现写「← 返回首页」却执行 router.back()
    expect([planBack(null, null, "home").label, planBack(null, null, "home").useHistoryBack]).toEqual([
      "← 返回",
      false,
    ]);
    expect(planBack(null, "贵州茅台", "search").fallbackHref).toBe("/search?q=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0");
  });

  it("⑥ 🔁 反向：白名单外的 from 不得被当成应用内进入（否则又是 back 到 about:blank）", () => {
    for (const raw of [undefined, "", "product", "SEARCH", "home;rm"]) {
      expect([planBack(raw, null, null).label, planBack(raw, null, null).useHistoryBack]).toEqual([
        "← 返回",
        false,
      ]);
    }
  });

  it("⑦ 🔁 会话残留只许影响推导目标，不许影响文案", () => {
    const base = planBack("home", null, null);
    for (const stored of ["home", "search", "chat", null] as const) {
      const p = planBack("home", null, stored);
      expect([p.label, p.useHistoryBack]).toEqual([base.label, base.useHistoryBack]);
    }
    expect([planBack(null, null, "chat").fallbackHref, planBack(null, null, null).fallbackHref]).toEqual([
      "/chat",
      "/",
    ]);
  });
});
