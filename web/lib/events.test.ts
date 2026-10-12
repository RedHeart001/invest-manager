import { beforeEach, describe, expect, it, vi } from "vitest";

const dsGet = vi.fn();
vi.mock("@/lib/data-service", () => ({ dsGet: (...a: unknown[]) => dsGet(...a) }));

import {
  DEGRADE_NOTES,
  fetchEvents,
  groupByDate,
  narrowByDates,
  pickEventDates,
  type EventItem,
} from "./events";

describe("groupByDate", () => {
  it("按日期分组，过滤空标题/空日期", () => {
    const items: EventItem[] = [
      { date: "2026-03-10", title: "年报超预期" },
      { date: "2026-03-10", title: "券商上调评级", source: "证券时报" },
      { date: "2026-03-12", title: "行业政策发布" },
      { date: "", title: "无日期条目应被过滤" },
      { date: "2026-03-11", title: "" },
    ];
    const byDate = groupByDate(items);
    expect(Object.keys(byDate)).toEqual(["2026-03-10", "2026-03-12"]);
    expect(byDate["2026-03-10"]).toHaveLength(2);
  });
});

describe("pickEventDates（转折点 + 大波动日）", () => {
  const candles = [
    { date: "2026-03-02", close: 100 },
    { date: "2026-03-03", close: 100.5 },
    { date: "2026-03-04", close: 104 }, // +3.48% 大波动
    { date: "2026-03-05", close: 103.5 },
    { date: "2026-03-06", close: 103 },
    { date: "2026-03-09", close: 98 }, // -4.85% 大波动
    { date: "2026-03-10", close: 98.5 },
  ];

  it("命中大波动日与阶段转折点", () => {
    const dates = pickEventDates(candles, ["2026-03-09"]);
    expect(dates).toContain("2026-03-04");
    expect(dates).toContain("2026-03-09");
    expect(dates).not.toContain("2026-03-03");
    expect(dates).not.toContain("2026-03-05");
  });

  it("去重且上限 12 个", () => {
    const many = Array.from({ length: 30 }, (_, i) => ({
      date: `2026-04-${String(i + 1).padStart(2, "0")}`,
      close: 100 + (i % 2 === 0 ? 5 : -4.5),
    }));
    const dates = pickEventDates(many, []);
    expect(dates.length).toBeLessThanOrEqual(12);
  });
});

describe("narrowByDates（CR-10）", () => {
  const byDate = {
    "2026-03-04": [{ date: "2026-03-04", title: "大波动日新闻" }],
    "2026-03-05": [{ date: "2026-03-05", title: "平淡日新闻" }],
    "2026-03-09": [{ date: "2026-03-09", title: "转折点新闻" }],
  };

  it("只保留指定日期的事件", () => {
    const out = narrowByDates(byDate, ["2026-03-04", "2026-03-09"]);
    expect(Object.keys(out).sort()).toEqual(["2026-03-04", "2026-03-09"]);
    expect(out["2026-03-05"]).toBeUndefined();
  });

  it("指定日期在 byDate 中不存在 → 结果为空（不报错）", () => {
    expect(narrowByDates(byDate, ["2099-01-01"])).toEqual({});
  });

  it("空日期集合 → 空结果", () => {
    expect(narrowByDates(byDate, [])).toEqual({});
  });

  it("与 pickEventDates 联动：只留大波动日与转折点", () => {
    const candles = [
      { date: "2026-03-02", close: 100 },
      { date: "2026-03-03", close: 100.5 },
      { date: "2026-03-04", close: 104 }, // +3.48% 大波动
      { date: "2026-03-05", close: 103.5 }, // 平淡
      { date: "2026-03-09", close: 98 }, // 转折点
    ];
    const dates = pickEventDates(candles, ["2026-03-09"]);
    const out = narrowByDates(byDate, dates);
    expect(out["2026-03-04"]).toBeDefined();
    expect(out["2026-03-09"]).toBeDefined();
    expect(out["2026-03-05"]).toBeUndefined();
  });
});

// E-3 刀 A（10-12）：这三句此前没有任何测试钉住（grep「谁钉住旧字面」只命中定义处），
// 所以"改文案"这件事本身是没有回归保护的。下面这组把新字面与两条"不许再说"一起写死。
describe("降级文案（E-3 刀 A 改准）", () => {
  it("三句字面钉住", () => {
    expect(DEGRADE_NOTES.fund).toBe("基金事件源（定期报告公告）暂未接入事件区，仅展示阶段划分");
    expect(DEGRADE_NOTES.bond).toBe("可转债公告源（强赎/下修）暂未接入事件区，仅展示阶段划分");
    expect(DEGRADE_NOTES.crypto).toBe("加密货币事件源暂未接入事件区，仅展示阶段划分");
  });

  it("🔁 crypto 不许再说「没有源」（Tavily 已是 OPT-2 新闻融合的第三家）", () => {
    expect(DEGRADE_NOTES.crypto).not.toContain("免费新闻源");
  });

  it("🔁 fund 不许再承诺「分红节点」（/fund/report 只回定期报告清单）", () => {
    expect(DEGRADE_NOTES.fund).not.toContain("分红");
  });

  it("三句都承认「仅展示阶段划分」（R16：缺口要说出口）", () => {
    for (const t of ["fund", "bond", "crypto"]) expect(DEGRADE_NOTES[t]).toContain("仅展示阶段划分");
  });
});

// fetchEvents 是账上那条「降级路径此前零覆盖」的那一枚：上面三枚纯函数测不到它。
describe("fetchEvents 降级路径", () => {
  beforeEach(() => {
    dsGet.mockReset();
  });

  it("非股票＝一次上游都不发（E-3 的本体）", async () => {
    const r = await fetchEvents("crypto", "E3-C1");
    expect(dsGet).not.toHaveBeenCalled();
    expect(r).toEqual({ degraded: true, note: DEGRADE_NOTES.crypto, byDate: {} });
  });

  it("未登记的类型给一句人话，不是空 note", async () => {
    const r = await fetchEvents("option", "E3-C2");
    expect(dsGet).not.toHaveBeenCalled();
    expect(r.degraded).toBe(true);
    expect(r.note).toBe("该类型暂无事件源");
  });

  it("股票只打 /news 一发，条目按日期归组", async () => {
    dsGet.mockResolvedValue({
      code: "600519",
      degraded: false,
      note: null,
      items: [{ date: "2026-03-04", title: "公告A" }],
    });
    const r = await fetchEvents("stock", "E3-S1");
    expect(dsGet).toHaveBeenCalledTimes(1);
    expect(dsGet.mock.calls[0][0]).toBe("/news");
    expect(r.degraded).toBe(false);
    expect(Object.keys(r.byDate)).toEqual(["2026-03-04"]);
  });

  it("ds 侧降级：note 原样透传，不静默成空列表", async () => {
    dsGet.mockResolvedValue({ code: "E3-S2", degraded: true, note: "新闻源暂不可用（东财冷却）", items: [] });
    const r = await fetchEvents("stock", "E3-S2");
    expect(r.degraded).toBe(true);
    expect(r.note).toBe("新闻源暂不可用（东财冷却）");
    expect(r.byDate).toEqual({});
  });

  it("ds 不可达：note 说「新闻源不可达」并带上原因", async () => {
    dsGet.mockImplementation(async () => {
      throw new Error("data-service unreachable");
    });
    const r = await fetchEvents("stock", "E3-S3");
    expect(r.degraded).toBe(true);
    expect(r.note).toContain("新闻源不可达");
    expect(r.note).toContain("data-service unreachable");
  });
});
