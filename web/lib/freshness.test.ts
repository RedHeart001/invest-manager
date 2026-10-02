import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// #22(b)／#25 陈旧可见性 ＋ #23 当日幂等闸门的共用判据（`lib/freshness.ts`）。
//
// 这个文件要钉住的不是"有没有一句文案"，而是**日界**：库里存的是 UTC 瞬间，
// 而"这一类今天动过没有"必须按北京日界算（CR9-16 同族）。两个用途共用同一列、
// 同一个 `beijingDateOf` ⇒ 一旦谁自己 parse 了一次，闸门与陈旧说明就会分叉。
//
// 时刻一律用 fake timers 钉死 ⇒ 本套件在任何钟点都可复跑（CR9-35 同族纪律）。

const groupBy = vi.fn();
const findFirst = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: { product: { groupBy: (...a: unknown[]) => groupBy(...a), findFirst: (...a: unknown[]) => findFirst(...a) } },
}));

import { listSyncedToday, snapshotRefreshedToday, staleNotes } from "./freshness";
import { beijingDateOf, beijingToday } from "./time";

/** 北京某个"月-日 时:分"对应的 UTC 瞬间（写用例时用可读的形式，不手算偏移） */
function bj(day: string, hhmm: string): Date {
  return new Date(`${day}T${hhmm}:00+08:00`);
}

describe("北京日界（#23 与 #22(b) 共用的那一把尺）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(bj("2026-10-02", "17:00")); // 北京今日＝2026-10-02
    groupBy.mockReset();
    findFirst.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("beijingDateOf 与 beijingToday 同源（同一时刻必须给同一天）", () => {
    expect(beijingDateOf(new Date())).toBe(beijingToday());
  });

  it("北京 23:59 的行算「今日」——日界按 UTC+8 切，不是按 UTC 零点", async () => {
    findFirst.mockResolvedValue({ updatedAt: bj("2026-10-02", "23:59") });
    expect(await listSyncedToday("stock")).not.toBeNull();
  });

  it("🔁 反向：同一行落在北京次日 00:00 就不算今日（宿主机时区不参与判断）", async () => {
    findFirst.mockResolvedValue({ updatedAt: bj("2026-10-03", "00:00") });
    expect(await listSyncedToday("stock")).toBeNull();
  });

  it("🔁 反向：昨日 23:59 的那一行不得被算成今日（闸门早退判据的全部意义在这里）", async () => {
    findFirst.mockResolvedValue({ updatedAt: bj("2026-10-01", "23:59") });
    expect(await listSyncedToday("stock")).toBeNull();
  });

  it("该类还没有行（findFirst 给 null）⇒ 判据为 null，不抛", async () => {
    findFirst.mockResolvedValue(null);
    expect(await listSyncedToday("hk")).toBeNull();
  });

  it("有行但从未刷过快照（snapshotAt 为 null）⇒ 刷新判据为 null，不抛", async () => {
    findFirst.mockResolvedValue({ snapshotAt: null });
    expect(await snapshotRefreshedToday("stock")).toBeNull();
  });

  it("快照落在北京今日 ⇒ 命中（#23(v)：甲-1 之后贵的那条腿看这一列）", async () => {
    findFirst.mockResolvedValue({ snapshotAt: bj("2026-10-02", "02:40") });
    expect(await snapshotRefreshedToday("fund")).not.toBeNull();
  });
});

describe("陈旧说明只在陈旧时出（#22(b) 改判：正常态一行字都不出）", () => {
  const TODAY = "2026-10-02";
  // cutoff＝昨日（给 1 天宽限：休市日与"服务停一晚"都属正常态，天天出字这句话就没判别力了）
  const at = (day: string) => ({ listAt: bj(day, "12:00"), snapAt: bj(day, "13:00") });

  it("主数据早于前日 ⇒ 报一条 list 成因", () => {
    const n = staleNotes([{ type: "stock", ...at("2026-09-12") }], TODAY);
    expect(n).toEqual([{ type: "stock", kind: "list", since: "2026-09-12" }]);
  });

  it("🔁 正常态不出字：两列都在昨日或更新 ⇒ 空数组", () => {
    expect(staleNotes([{ type: "stock", ...at("2026-10-01") }], TODAY)).toEqual([]);
    expect(staleNotes([{ type: "stock", ...at(TODAY) }], TODAY)).toEqual([]);
  });

  it("列表新、只有快照早于前日 ⇒ 报 snapshot 成因（快照列没被 list 掩盖）", () => {
    const n = staleNotes(
      [{ type: "bond", listAt: bj(TODAY, "02:10"), snapAt: bj("2026-09-25", "20:22") }],
      TODAY,
    );
    expect(n).toEqual([{ type: "bond", kind: "snapshot", since: "2026-09-25" }]);
  });

  it("🔁 拆腿窗口不得谎称陈旧：列表刚换、snapshotAt 还是 null ⇒ 不报快照那条", () => {
    expect(
      staleNotes([{ type: "stock", listAt: bj(TODAY, "02:05"), snapAt: null }], TODAY),
    ).toEqual([]);
  });

  it("同源不重复报：列表陈旧且从未刷过快照 ⇒ 只报 list 一条（成因只有一个，不说两遍）", () => {
    const n = staleNotes([{ type: "stock", listAt: bj("2026-09-12", "22:02"), snapAt: null }], TODAY);
    expect(n).toEqual([{ type: "stock", kind: "list", since: "2026-09-12" }]);
  });

  it("无 tab 的类型不报（us 有主数据却没有入口 ⇒ 报了会把人引向不存在的分类）", () => {
    const n = staleNotes([{ type: "us", listAt: bj("2026-09-12", "22:02"), snapAt: null }], TODAY);
    expect(n).toEqual([]);
  });

  it("五类同日陈旧 ⇒ 五条全报、按 tab 顺序（本函数不截断，上限是渲染层的事）", () => {
    const old = (type: string) => ({ type, ...at("2026-09-01") });
    const n = staleNotes(
      [old("hk"), old("crypto"), old("bond"), old("fund"), old("stock")],
      TODAY,
    );
    // 截断放在 `browse.ts`（那里能一并给出 staleMore）；在这里 slice 会把第三类**静默藏掉**，
    // 而 10-02 的活体探针正是撞在这上面：stock／bond／crypto 同日陈旧，屏上只剩两条。
    expect(n.map((x) => x.type)).toEqual(["stock", "fund", "bond", "crypto", "hk"]);
  });

  it("list 优先于 snapshot：同一类两者都陈旧时只说一次（snapAt 为 null 时两者同源）", () => {
    const n = staleNotes(
      [{ type: "crypto", listAt: bj("2026-09-27", "11:38"), snapAt: bj("2026-09-27", "11:40") }],
      TODAY,
    );
    expect(n).toEqual([{ type: "crypto", kind: "list", since: "2026-09-27" }]);
  });

  it("该类 0 行（groupBy 不返回这一类）⇒ 不报：空表在页面上就是空列表，不需要一句陈旧", () => {
    expect(staleNotes([], TODAY)).toEqual([]);
  });
});
