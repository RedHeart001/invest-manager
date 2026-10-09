import { describe, expect, it } from "vitest";

import { marketClockOf, quoteClockText } from "./market-clock";

// 下面两枚入参是**屏上实测字面**，不是构想的形状：
//   - `2026-10-08T16:00:01` ＝主人 10-09 15:0x 那张 `/product/us/CEG` 截图上的那一串（他据此报「时间还是昨天的」）
//   - `2026-10-09T15:13:47` ＝同一分钟我打开 `/product/stock/600519` 的对照组（见 FIX-LEDGER 第 56 项末 ③）
// 美东那两个偏移数（−4／−5）取的是 2026 年的夏令时边界：11-01（11 月第一个周日）2:00 落回 EST。
const US_EDT = "2026-10-08T16:00:01";
const US_EST = "2026-11-01T16:00:00";
const CN = "2026-10-09T15:13:47";

describe("market-clock（#58 报价时间戳是哪个钟）", () => {
  it("美股夏令时段：点名美东，并补一份北京时刻（那条正确的数不再被读成过期一天）", () => {
    expect(quoteClockText("us", US_EDT)).toBe("美东 2026-10-08 16:00:01（北京 2026-10-09 04:00:01）");
  });

  it("美股冬令时段：偏移跟着换，差值从 +12 小时变 +13 小时（写死偏移的实现会在这里红）", () => {
    expect(quoteClockText("us", US_EST)).toBe("美东 2026-11-01 16:00:00（北京 2026-11-02 05:00:00）");
    // 同一天的两侧：切换前仍是 EDT（+12），切换后是 EST（+13）
    expect(quoteClockText("us", "2026-10-31T16:00:00")).toBe("美东 2026-10-31 16:00:00（北京 2026-11-01 04:00:00）");
  });

  it("🔁 成对：A 股那一屏本来就是北京钟，只点名、不重复换算", () => {
    expect(quoteClockText("stock", CN)).toBe("北京 2026-10-09 15:13:47");
    expect(quoteClockText("fund", CN)).toBe("北京 2026-10-09 15:13:47");
    expect(quoteClockText("bond", CN)).toBe("北京 2026-10-09 15:13:47");
    // 同一串时间，市场不同⇒读法不同：这条正是"昨天 16:00"那个误读的根
    expect(quoteClockText("us", CN)).not.toBe(quoteClockText("stock", CN));
  });

  it("港股＝同一个墙上钟（UTC+8 不换夏令时），点名香港但不写第二遍时刻", () => {
    expect(quoteClockText("hk", "2026-10-09T16:08:32")).toBe("香港 2026-10-09 16:08:32");
  });

  it("🔁 没有钟可点名就不许编：认不得的市场原样透传，形态不合的也不认领", () => {
    expect(marketClockOf("crypto")).toBeNull();
    expect(quoteClockText("crypto", "2026-10-09T08:00:00")).toBe("2026-10-09T08:00:00");
    expect(quoteClockText("us", "20261008160001")).toBe("20261008160001"); // `_ts_iso` 凑不满 14 位时原样返回
    expect(quoteClockText("us", "")).toBeNull();
    expect(quoteClockText("us", null)).toBeNull();
    expect(quoteClockText("us", undefined)).toBeNull();
  });
});
