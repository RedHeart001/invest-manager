import { describe, expect, it } from "vitest";

import {
  FROM_LABEL,
  canBackToOrigin,
  hrefForFrom,
  observePath,
  parseFrom,
  planBack,
  resetPathTrace,
  routeKey,
} from "./provenance";

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

// #56 甲（10-08 主人手测「粘贴链接后点返回没反应」）＋第二轮（10-09：粘贴 `?from=home`
// 却回到搜索页／裸 URL 永远掉回上一次搜索过的那一页）：文案与目标必须同源，且 `back()`
// 只能由"本文档路由轨迹"发放，不能由 URL 上的一个可粘贴参数发放。
describe("planBack（文案与目标取同一个键）", () => {
  it("④ URL 带白名单内 from＝承诺那个来路，且给出可独立到达的目标", () => {
    expect(planBack("search", "贵州茅台")).toEqual({
      label: "← 返回搜索",
      href: "/search?q=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0",
    });
  });

  it("⑤ 🔁 反向：裸 URL 不继承会话残留，目标一律首页（他 10-09 报的『一旦搜索过，返回永远都是那一页』）", () => {
    expect(planBack(null, null)).toEqual({ label: "← 返回", href: "/" });
    // `q` 单独出现也不算来路：搜索词来自 URL ≠ 从搜索页进来
    expect(planBack(undefined, "贵州茅台").href).toBe("/");
  });

  it("⑥ 🔁 反向：白名单外的 from 不得被当成应用内进入（外部输入不许点亮一级、也不许选目标）", () => {
    for (const raw of [undefined, "", "product", "SEARCH", "home;rm"]) {
      expect(planBack(raw, null)).toEqual({ label: "← 返回", href: "/" });
    }
  });

  it("⑦ 三种来路各自的目标都落在文案承诺的那一页（chat/home 不夹带 q）", () => {
    expect(["search", "home", "chat"].map((f) => planBack(f, "茅台").href)).toEqual([
      "/search?q=%E8%8C%85%E5%8F%B0",
      "/",
      "/chat",
    ]);
  });
});

describe("路由轨迹（back() 的唯一许可证）", () => {
  it("⑧ 正向：应用内从搜索页推进详情 ⇒ 才敢 back()", () => {
    resetPathTrace();
    observePath("/search?q=%E8%8C%85%E5%8F%B0&type=all");
    observePath("/product/stock/600519?from=search&q=%E8%8C%85%E5%8F%B0");
    expect(canBackToOrigin("/product/stock/600519?from=search&q=%E8%8C%85%E5%8F%B0")).toBe(true);
    // 被回退的那一页自己不能拿这张许可证
    expect(canBackToOrigin("/search?q=%E8%8C%85%E5%8F%B0&type=all")).toBe(false);
  });

  it("⑨ 🔁 反向：他 D 那一屏的完整顺序——先应用内进过一次，再粘贴带 from 的 URL", () => {
    resetPathTrace();
    observePath("/search");
    observePath("/product/stock/600519?from=search");
    expect(canBackToOrigin("/product/stock/600519?from=search")).toBe(true);

    // 地址栏粘贴＝一次新的整页加载，模块状态随旧文档消失；resetPathTrace 就是这一次换文档
    resetPathTrace();
    const pasted = "/product/us/CEG?from=home";
    observePath(pasted);
    // 旧实现只要见到 `from` 就 back() ⇒ 落到上一条历史＝那个搜索页；现在改 push "/"
    expect(canBackToOrigin(pasted)).toBe(false);
  });

  it("⑩ 同一 URL 重复回车（他 C 那一屏）⇒ 观察幂等，轨迹不被自己污染", () => {
    resetPathTrace();
    observePath("/search?q=a");
    observePath("/product/us/CEG?from=search&q=a");
    observePath("/product/us/CEG?from=search&q=a");
    expect(canBackToOrigin("/product/us/CEG?from=search&q=a")).toBe(true);
  });

  it("⑪ routeKey＝路径＋查询（不含 hash），空查询不留 `?`", () => {
    expect(routeKey("/product/us/CEG", new URLSearchParams("from=home&q=茅台"))).toBe(
      "/product/us/CEG?from=home&q=%E8%8C%85%E5%8F%B0",
    );
    expect(routeKey("/product/us/CEG", new URLSearchParams(""))).toBe("/product/us/CEG");
  });
});
