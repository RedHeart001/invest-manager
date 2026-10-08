import { describe, expect, it } from "vitest";

import { klineEmptyReason, klineEmptyText } from "./kline-empty-reason";

// 下面三条 note 都是**盘上实测回执的字面**，不是构想的形态：
//   - `data-service/runtime/us-kline-probe2-1008.out`（21:58，`interval=1d`＝真出网那一次）
//   - `data-service/runtime/us-kline-probe-1008.out`（21:57，我入参写错成 `interval=day`）
//   - `lib/kline.ts:288` 负缓存分支 / `:298` 空响应分支的自家文案
const usCegAllFailed =
  "回源失败：us/CEG: all sources failed: yfinance: yfinance kline failed: Too Many Requests. " +
  "Rate limited. Try after a while.; tencent: tencent does not support code: CEG";
const invalidInterval =
  "回源失败：us/CEG: all sources failed: yfinance: openbb provider serves US daily kline only; " +
  "tencent: tencent kline interval not supported: day";
const negativeCache = "近期回源失败（限流/故障），窗口期内暂不再尝试";
const emptyUpstream = "上游返回空数据（源：tencent），窗口期内暂不重试";

describe("klineEmptyReason（#55 甲 空态成因归一）", () => {
  it("实测形态：主人那一屏的 502 detail → 归一成一行中文", () => {
    expect(klineEmptyReason(usCegAllFailed)).toBe("试过的数据源都没给这个品种的日线");
    expect(klineEmptyText(usCegAllFailed)).toBe(
      "暂无行情数据 · 试过的数据源都没给这个品种的日线",
    );
  });

  it("🔁 成对：note 为空 → 只说「暂无行情数据」，一个成因都不许编", () => {
    expect(klineEmptyReason(null)).toBeNull();
    expect(klineEmptyReason("   ")).toBeNull();
    expect(klineEmptyText(undefined)).toBe("暂无行情数据");
  });

  it("🔁 成对：`all sources failed` 压在单家成因之前——两家都试过 ≠ 一家在限流", () => {
    expect(klineEmptyReason(usCegAllFailed)).toBe("试过的数据源都没给这个品种的日线");
    // 同一份文本去掉链前缀（＝只剩单家 429 子句）必须翻转成限流那一档：
    // 防实现退化成"看到 429 就说限流"，那会把永久缺口读成暂时故障。
    expect(klineEmptyReason("yfinance kline failed: Too Many Requests. Rate limited.")).toBe(
      "数据源暂时取不到（限流或故障），窗口期内不重试",
    );
  });

  it("入参写错那一档（`interval` 不被支持）同样落在「都没给」，不许读成数据源坏了", () => {
    expect(klineEmptyReason(invalidInterval)).toBe("试过的数据源都没给这个品种的日线");
  });

  it("自家文案两档各归各的：负缓存＝窗口期，空响应＝返回空内容", () => {
    expect(klineEmptyReason(negativeCache)).toBe("数据源暂时取不到（限流或故障），窗口期内不重试");
    expect(klineEmptyReason(emptyUpstream)).toBe("数据源返回了空内容");
  });

  it("单家不支持 → 「数据源不提供这个品种」（不含 all sources failed 时才走这一档）", () => {
    expect(klineEmptyReason("tencent does not support code: CEG")).toBe("数据源不提供这个品种");
    // 🔁 成对：不许把"这一家不提供"写成"所有数据源都没有"
    expect(klineEmptyReason("tencent does not support code: CEG")).not.toContain("试过");
  });

  it("表里没有的形态 → 原样带出并截断，绝不静默退回「暂无」", () => {
    const odd = "回源失败：库里没有这一段区间的缓存，而回源被人工暂停";
    expect(klineEmptyReason(odd)).toBe("库里没有这一段区间的缓存，而回源被人工暂停");
    const long = `回源失败：${"未分类成因".repeat(30)}`;
    const out = klineEmptyReason(long) ?? "";
    expect(out).toHaveLength(61); // 60 字 + 省略号
    expect(out.endsWith("…")).toBe(true);
    expect(out).not.toContain("回源失败：");
  });

  it("反向验证：本函数不产出它没有证据的断言（「只有一家」「没有日线源」）", () => {
    for (const note of [usCegAllFailed, negativeCache, emptyUpstream, invalidInterval]) {
      const text = klineEmptyReason(note) ?? "";
      expect(text).not.toMatch(/只有|唯一一家|没有.{0,4}数据源|永久/);
    }
  });
});
