/**
 * CR9-92（OPT-3 第一批 1a）离线单测：实时条读侧的四件纯判据（节奏／显不显示／最后值／发不发）。
 *
 * 运行方式（零出网）：`npx vitest run lib/realtime.test.ts`
 *
 * 每条判据都配"能点亮它"的合成样本（C34 成对断言）：库内扫描证"现在没有红的"，
 * 合成样本证"改坏了会红"，两半不互证。
 */

import { describe, expect, it } from "vitest";

import {
  INTRADAY_EVERY_TICKS,
  PRICE_POLL_MS,
  REALTIME_BUDGET_MS,
  REALTIME_TEXT,
  displayPrice,
  isStale,
  lastUpdateStamp,
  mergeTick,
  pageVisible,
  partsForTick,
  sessionMayBeOpen,
  shouldPoll,
  sparkPath,
  stripVisible,
  type RealtimeResponse,
} from "./realtime";

function resp(partial: Partial<RealtimeResponse> = {}): RealtimeResponse {
  return {
    type: "stock",
    code: "600519",
    observedAt: "2026-10-13T09:31:02",
    parts: ["price", "intraday"],
    price: { type: "stock", code: "600519", price: 1250, source: "tencent", timestamp: "2026-10-13T09:31:00", currency: "CNY" },
    intraday: {
      interval: "1m",
      date: "2026-10-13",
      bars: 3,
      lastAt: "2026-10-13 09:32",
      source: "tencent",
      points: [
        { t: "09:30", price: 1249, volume: 100 },
        { t: "09:31", price: 1250, volume: 80 },
        { t: "09:32", price: 1251, volume: 60 },
      ],
    },
    crossChecked: true,
    verifyVerdict: "agree",
    consensus: { verdict: "agree", diffPct: 0, thresholdPct: 0.5, provisional: true, basis: "预设值" },
    hasTodayData: true,
    intradayDateIsToday: true,
    wired: true,
    sources: [{ kind: "price", source: "tencent", ok: true, latencyMs: 300, detail: null }],
    degraded: false,
    note: null,
    ...partial,
  };
}

describe("两个节奏：现价 10s、分时 60s（PLAN.md:172）", () => {
  it("第 0 跳取全，之后 5 跳只问现价，第 6 跳再取全", () => {
    expect([0, 1, 2, 3, 4, 5, 6, 7].map(partsForTick)).toEqual([
      "price,intraday",
      "price",
      "price",
      "price",
      "price",
      "price",
      "price,intraday",
      "price",
    ]);
  });

  it("🔁 这两个数乘起来必须正好是 60 秒（改一个就得同时改另一个，否则节奏悄悄漂）", () => {
    expect(PRICE_POLL_MS * INTRADAY_EVERY_TICKS).toBe(60_000);
    expect(PRICE_POLL_MS).toBe(10_000);
    // BFF 预算必须盖住 ds 串行跑腿的最坏值，又不许长成第二条 20s 排队
    expect(REALTIME_BUDGET_MS).toBeGreaterThanOrEqual(9_000);
    expect(REALTIME_BUDGET_MS).toBeLessThan(20_000);
  });

  it("非法跳数（负数／小数）回落「取全」，不静默只问现价", () => {
    expect(partsForTick(-1)).toBe("price,intraday");
    expect(partsForTick(1.5)).toBe("price,intraday");
  });
});

describe("规则①：有当日数据才显示", () => {
  it("只有 `hasTodayData===true` 才出这一块", () => {
    expect(stripVisible(resp())).toBe(true);
    expect(stripVisible(resp({ hasTodayData: false }))).toBe(false);
    expect(stripVisible(resp({ hasTodayData: null }))).toBe(false);
    expect(stripVisible(null)).toBe(false);
    expect(stripVisible(undefined)).toBe(false);
  });

  it("🔁 反向：把当日判据摘掉（`intradayDateIsToday:false` 那一形）⇒ 屏上不许留任何盒子", () => {
    // 上游返回上一交易日的完整序列时 `hasTodayData` 是 false——这一形正是 09-27 周日实测撞出来的
    expect(stripVisible(resp({ hasTodayData: false, intradayDateIsToday: false }))).toBe(false);
  });

  it("现价取到了但一条分时都没有 ⇒ 也不算「当日有数据」（判据只有那一条）", () => {
    expect(stripVisible(resp({ intraday: null, hasTodayData: false }))).toBe(false);
    expect(displayPrice(resp({ price: null }))).toBeNull();
  });
});

describe("规则③：拉不到就交最后已知值", () => {
  it("只问现价的那一跳：分时与当日判据都留着（不闪灭）", () => {
    const merged = mergeTick(resp(), resp({ parts: ["price"], hasTodayData: null, intradayDateIsToday: null, intraday: null }));
    expect(merged.intraday?.bars).toBe(3);
    expect(merged.hasTodayData).toBe(true);
    expect(stripVisible(merged)).toBe(true);
  });

  it("🔁 反向：不做这一步 merge ⇒ 每 6 跳闪灭一次（那是自家节奏造成的闪，不是上游没数据）", () => {
    const raw = resp({ parts: ["price"], hasTodayData: null, intradayDateIsToday: null, intraday: null });
    expect(stripVisible(raw)).toBe(false);
  });

  it("取过分时的那一跳整份换（旧曲线不许盖住新曲线）", () => {
    const next = resp({ intraday: { ...resp().intraday!, bars: 99 } });
    expect(mergeTick(resp(), next).intraday?.bars).toBe(99);
    expect(mergeTick(null, next)).toBe(next);
  });

  it("「最后更新」优先上游自己的时间戳，缺失才回落 ds 的采样时刻", () => {
    expect(lastUpdateStamp(resp())).toBe("09:31:00");
    expect(lastUpdateStamp(resp({ price: { type: "stock", code: "600519", price: 1 } }))).toBe("09:31:02");
    expect(lastUpdateStamp(null)).toBeNull();
  });

  it("stale 四态：从没成过／刚成过／超时没成／这一次就失败了", () => {
    const now = 1_000_000;
    expect(isStale(null, now, 0)).toBe(false); // 从没成过 ⇒ 组件本来就不渲染这一格
    expect(isStale(now - 1_000, now, 0)).toBe(false);
    expect(isStale(now - 61_000, now, 0)).toBe(true);
    expect(isStale(now - 1_000, now, 2)).toBe(true);
  });
});

describe("规则④：页面不可见／非交易时段不请求（粗判据）", () => {
  // 北京时间没有夏令时 ⇒ 用 UTC 构造读数最省事（UTC+8）
  const beijingMon = (h: number, m: number) => Date.UTC(2026, 8, 14, h - 8, m); // 2026-09-14 是周一
  const usMonEdt = (h: number, m: number) => Date.UTC(2026, 8, 14, h + 4, m); // EDT＝UTC-4
  const usMonEst = (h: number, m: number) => Date.UTC(2026, 10, 2, h + 5, m); // 2026-11-02（周一）＝EST＝UTC-5

  it("A股／场内基金：09:31 发，午休 12:00 不发，15:31 不发", () => {
    expect(sessionMayBeOpen("stock", beijingMon(9, 31))).toBe(true);
    expect(sessionMayBeOpen("fund", beijingMon(9, 31))).toBe(true);
    expect(sessionMayBeOpen("stock", beijingMon(12, 0))).toBe(false);
    expect(sessionMayBeOpen("stock", beijingMon(15, 31))).toBe(false);
  });

  it("港股 12:30 午休不发；美股按**美东**钟发（换夏令时也一样）", () => {
    expect(sessionMayBeOpen("hk", beijingMon(12, 30))).toBe(false);
    expect(sessionMayBeOpen("hk", beijingMon(10, 0))).toBe(true);
    expect(sessionMayBeOpen("us", usMonEdt(9, 31))).toBe(true);
    expect(sessionMayBeOpen("us", usMonEdt(8, 0))).toBe(false);
    expect(sessionMayBeOpen("us", usMonEst(9, 31))).toBe(true);
  });

  it("周末不发；本轮没接的类别（crypto／bond）也不发", () => {
    const saturday = Date.UTC(2026, 8, 19, 1, 31); // 2026-09-19 周六，北京 09:31
    expect(sessionMayBeOpen("stock", saturday)).toBe(false);
    expect(sessionMayBeOpen("crypto", beijingMon(9, 31))).toBe(false);
    expect(sessionMayBeOpen("bond", beijingMon(9, 31))).toBe(false);
    expect(shouldPoll("crypto", beijingMon(9, 31))).toBe(false);
  });

  it("没有 document 的环境（SSR／node）当作可见：这条规则的适用面是浏览器", () => {
    expect(typeof document).toBe("undefined");
    expect(pageVisible()).toBe(true);
    expect(shouldPoll("stock", beijingMon(9, 31))).toBe(true);
    expect(shouldPoll("stock", beijingMon(3, 0))).toBe(false);
  });
});

describe("迷你折线（不引 ECharts 的那一条）", () => {
  it("少于 2 个点／宽度为 0 ⇒ 不画（宁可不画也不画一条谎线）", () => {
    expect(sparkPath([], 240, 40)).toBeNull();
    expect(sparkPath([{ t: "09:30", price: 1, volume: 1 }], 240, 40)).toBeNull();
    expect(sparkPath([{ t: "09:30", price: 1, volume: 0 }, { t: "09:31", price: 2, volume: 0 }], 0, 40)).toBeNull();
  });

  it("一条平线也要画得出来（span=0 会把所有点甩到 y=0，那是形状不是数据）", () => {
    const d = sparkPath(
      [
        { t: "09:30", price: 7, volume: 1 },
        { t: "09:31", price: 7, volume: 1 },
        { t: "09:32", price: 7, volume: 1 },
      ],
      240,
      40,
    );
    expect(d).not.toBeNull();
    expect(d).not.toMatch(/NaN/);
    expect((d as string).startsWith("M")).toBe(true);
    expect(((d as string).match(/L/g) ?? []).length).toBe(2);
  });

  it("缺价的点跳过而不是当成 0（0 会被画成一根扎到底部的假针）", () => {
    const d = sparkPath(
      [
        { t: "09:30", price: null, volume: null },
        { t: "09:31", price: 10, volume: 1 },
        { t: "09:32", price: 12, volume: 1 },
      ],
      100,
      10,
    );
    expect((d as string).match(/M|L/g)?.length).toBe(2);
    expect(d).not.toMatch(/NaN/);
  });
});

describe("屏上字面（归主人定：改字要改这张表，这一枚会点名是哪一句）", () => {
  it("六串字面锁住形状，实时条不留任何第二处硬编码文案", () => {
    expect(REALTIME_TEXT.heading).toBe("当日实时");
    expect(REALTIME_TEXT.agree).toBe("两家报价一致");
    expect(REALTIME_TEXT.noSecondSource).toBe("只有一家报价，未做比对");
    expect(REALTIME_TEXT.diverged).toBe("两家报价有出入");
    expect(REALTIME_TEXT.lastUpdate("09:31:02")).toBe("最后更新 09:31:02（北京）");
    expect(REALTIME_TEXT.stale("09:31:02")).toBe("刷新没成功，仍显示 09:31:02 那一次的价");
  });

  // 10-13 下午复核补的那一枚：这一句此前会带着「阈值 0.5%，暂定值」＋偏差百分比上屏，
  // 因为组件的 diverged 分支直接把 ds 的 `note` 当文案用（`RealtimeStrip.tsx:109`）。
  // 数改住 `consensus.{diffPct,thresholdPct,provisional}` 之后，这里钉住"表里这几串不许有数字"——
  // ⚠ 它钉的是这张表，不是 ds 那句 note（note 那一半由 `test_cr9_92_realtime.py` 的 ③ 段钉）。
  it("这张表的判定文案不许含数字／%／'暂定'（比率与阈值取值只住机器可读位，10-05 那条纪律）", () => {
    // 禁的是"数"，不是那个概念——10-17 改字面后 `diverged` 连「阈值」那两个字都不再上屏了。
    // 牙齿：谁把 `0.5%`／`暂定值` 再拼回屏上文案，这一枚点名是哪一句。
    for (const key of ["heading", "agree", "noSecondSource", "diverged"] as const) {
      const text = REALTIME_TEXT[key];
      expect(`${key}:${text}`).not.match(/[0-9０-９]/);
      expect(`${key}:${text}`).not.match(/%|暂定/);
    }
  });
});
