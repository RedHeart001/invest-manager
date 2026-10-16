import { beforeEach, describe, expect, it, vi } from "vitest";

const dsGet = vi.fn();
vi.mock("@/lib/data-service", () => ({ dsGet: (...a: unknown[]) => dsGet(...a) }));

import {
  bondEventsFrom,
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

// #75 的 web 那一半（CR9-111）：转债那一臂从"一次都不发"变成"先映射、再拿正股问新闻"。
// 替身按**请求里的那个路径**分流——写死一个响应会把"第二发用的是正股代码"这一枚判别力抹掉。
describe("fetchEvents 转债那一臂（#75 web 半）", () => {
  beforeEach(() => {
    dsGet.mockReset();
  });

  const mapOk = {
    code: "110002",
    degraded: false,
    note: null,
    stockCode: "600519",
    stockName: "贵州茅台",
  };
  const newsOk = {
    code: "600519",
    degraded: false,
    note: null,
    items: [{ date: "2026-03-04", title: "正股公告A" }],
  };

  it("先问映射、再拿**正股代码**去问 /news（判别力在第二发的参数上）", async () => {
    dsGet.mockImplementation(async (p: string) => (p === "/bond/underlying" ? mapOk : newsOk));
    const r = await fetchEvents("bond", "B75-1");
    expect(dsGet.mock.calls.map((c) => c[0])).toEqual(["/bond/underlying", "/news"]);
    expect(dsGet.mock.calls[1][1]).toEqual({ code: "600519" });
    expect(r.degraded).toBe(false);
    expect(Object.keys(r.byDate)).toEqual(["2026-03-04"]);
    expect(r.fromStock).toEqual({ code: "600519", name: "贵州茅台" });
    expect(r.mapStatus).toBe("ok");
  });

  it("来路那句字面钉住（屏上只有这一处出口），正股简称读不出时退回代码", () => {
    expect(bondEventsFrom({ code: "600519", name: "贵州茅台" })).toBe(
      "事件区取的是正股「贵州茅台」的新闻，转债公告源仍未接入",
    );
    expect(bondEventsFrom({ code: "600519", name: null })).toBe(
      "事件区取的是正股「600519」的新闻，转债公告源仍未接入",
    );
  });

  it("🔁 来路句不许长成『转债公告已接入』（那条通道本轮没做）", () => {
    expect(bondEventsFrom({ code: "1", name: null })).not.toContain("已接入");
  });

  it("映射答不出＝不追问新闻、维持接之前那句缺口说明", async () => {
    dsGet.mockResolvedValue({
      code: "110002",
      degraded: true,
      note: "bond code not in convertible map: 110002（映射共 1060 只）",
      stockCode: null,
      stockName: null,
    });
    const r = await fetchEvents("bond", "B75-2");
    expect(dsGet).toHaveBeenCalledTimes(1);
    expect(r).toEqual({
      degraded: true,
      note: DEGRADE_NOTES.bond,
      byDate: {},
      mapStatus: "no-underlying",
    });
  });

  it("在册但那一行的正股代码为空＝同样不发第二发（不许把 null 当代码去打 /news）", async () => {
    dsGet.mockResolvedValue({ ...mapOk, stockCode: null });
    const r = await fetchEvents("bond", "B75-3");
    expect(dsGet).toHaveBeenCalledTimes(1);
    expect(r.mapStatus).toBe("no-underlying");
    expect(r.degraded).toBe(true);
  });

  it("路由不可用（未装载／404／连不上）＝屏上仍是那句缺口说明，成因只落机器可读位", async () => {
    dsGet.mockImplementation(async () => {
      throw new Error("data-service timeout after 30000ms（服务在跑但未及时响应）");
    });
    const r = await fetchEvents("bond", "B75-4");
    expect(r.degraded).toBe(true);
    expect(r.note).toBe(DEGRADE_NOTES.bond);
    expect(r.note).not.toContain("timeout");
    expect(r.mapStatus).toBe("route-failed");
  });

  it("映射通了但新闻降级＝沿用新闻那条 note，不假装成功", async () => {
    dsGet.mockImplementation(async (p: string) =>
      p === "/bond/underlying" ? mapOk : { code: "600519", degraded: true, note: "新闻源暂不可用（东财冷却）", items: [] },
    );
    const r = await fetchEvents("bond", "B75-5");
    expect(r.degraded).toBe(true);
    expect(r.note).toBe("新闻源暂不可用（东财冷却）");
    expect(r.fromStock).toBeUndefined();
  });

  it("🔁 其余类型照旧一次都不发（这一轮只放开 bond）", async () => {
    const r = await fetchEvents("fund", "B75-6");
    expect(dsGet).not.toHaveBeenCalled();
    expect(r.degraded).toBe(true);
    expect(r.mapStatus).toBeUndefined();
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
