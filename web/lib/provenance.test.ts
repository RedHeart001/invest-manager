import { describe, expect, it } from "vitest";

import { FROM_LABEL, hrefForFrom, parseFrom } from "./provenance";

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
