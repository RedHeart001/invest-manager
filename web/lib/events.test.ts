import { describe, expect, it } from "vitest";

import { groupByDate, pickEventDates, type EventItem } from "./events";

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
