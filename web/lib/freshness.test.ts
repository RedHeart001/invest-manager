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

import { BROWSE_TYPES, freshnessOfTypes, listSyncedToday, snapshotBadge, snapshotRefreshedToday, staleNotes } from "./freshness";
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

describe("陈旧说明只在有问题时出（#22(b) 改判：正常态一行字都不出）", () => {
  const TODAY = "2026-10-02";
  // cutoff＝昨日（给 1 天宽限：休市日与"服务停一晚"都属正常态，天天出字这句话就没判别力了）
  // `maxPrice` 给一个有值的数＝这一类当前是有价的（`crypto` 那种"有价而 snapshotAt 为 null"
  // 的库内形态由下面单独一条钉住）
  const at = (day: string) => ({ listAt: bj(day, "12:00"), snapAt: bj(day, "13:00"), maxPrice: 12.5 });

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
      [{ type: "bond", listAt: bj(TODAY, "02:10"), snapAt: bj("2026-09-25", "20:22"), maxPrice: 100 }],
      TODAY,
    );
    expect(n).toEqual([{ type: "bond", kind: "snapshot", since: "2026-09-25" }]);
  });

  // CR9-57（主人 10-03 拍板"整列空价格那句要上屏"）：#25 甲 (ii) 原来在这里选择**沉默**，
  // 防的是"把拆腿窗口谎称成陈旧"。这个约束原样保留（措辞不许出现"未更新"，见 search-client），
  // 新增的是"也不许没有话"。⇒ 本条从 🔁「不报」改判为「报 pending」，不是把旧断言放宽。
  it("拆腿窗口现在报 pending：列表今日换过、一个价都没有 ⇒ 说话但不称陈旧", () => {
    expect(
      staleNotes(
        [{ type: "stock", listAt: bj(TODAY, "02:05"), snapAt: null, maxPrice: null }],
        TODAY,
      ),
    ).toEqual([{ type: "stock", kind: "pending", since: TODAY }]);
  });

  it("🔁 pending 不得用 snapshotAt 单独判：有价而 snapshotAt 仍是 null（crypto 的真实形态）⇒ 一个字都不出", () => {
    // 库里 crypto＝250 行有价／`MAX(snapshotAt)` 为 NULL（09-27 那批行由当时的列表阶段
    // 直接写了 lastPrice，而 snapshotAt 这列是刀 1 之后才加的）⇒ 只看 snapshotAt 会把
    // 一列有价格的东西报成"还没跟上"。
    expect(
      staleNotes(
        [{ type: "crypto", listAt: bj(TODAY, "02:05"), snapAt: null, maxPrice: 68000.5 }],
        TODAY,
      ),
    ).toEqual([]);
  });

  it("pending 的 since＝名单换过的那一天（昨日换的、至今没价格 ⇒ 宽限期内不称陈旧但要说）", () => {
    const n = staleNotes(
      [{ type: "fund", listAt: bj("2026-10-01", "02:00"), snapAt: null, maxPrice: null }],
      TODAY,
    );
    expect(n).toEqual([{ type: "fund", kind: "pending", since: "2026-10-01" }]);
  });

  it("同源不重复报：列表陈旧且从未刷过快照 ⇒ 只报 list 一条（成因只有一个，不说两遍）", () => {
    const n = staleNotes(
      [{ type: "stock", listAt: bj("2026-09-12", "22:02"), snapAt: null, maxPrice: null }],
      TODAY,
    );
    expect(n).toEqual([{ type: "stock", kind: "list", since: "2026-09-12" }]);
  });

  // CR9-75 把成对的两半都留住：判据是"在不在 `BROWSE_TYPES` 名单里"，不是"有没有主数据"。
  // 名单**内**（us 从 10-07 起在）会报 ⇒ 见下一条；名单**外**不报 ⇒ 本条。
  it("名单外的类型不报（陈旧说明由 BROWSE_TYPES 圈定，不由主数据是否存在圈定）", () => {
    const n = staleNotes(
      [{ type: "future", listAt: bj("2026-09-12", "22:02"), snapAt: null, maxPrice: null }],
      TODAY,
    );
    expect(n).toEqual([]);
  });

  it("us 进名单后同一条输入会报（CR9-75 的正半：驱动它的是名单，不是类型名）", () => {
    const n = staleNotes(
      [{ type: "us", listAt: bj("2026-09-12", "22:02"), snapAt: null, maxPrice: null }],
      TODAY,
    );
    expect(n).toEqual([{ type: "us", kind: "list", since: "2026-09-12" }]);
  });

  it("六类同日陈旧 ⇒ 六条全报、按 tab 顺序（本函数不截断，上限是渲染层的事）", () => {
    const old = (type: string) => ({ type, ...at("2026-09-01") });
    // 输入刻意倒着给：证明输出顺序来自 `BROWSE_TYPES`，而不是来自调用方传进来的顺序
    const n = staleNotes(
      [old("us"), old("hk"), old("crypto"), old("bond"), old("fund"), old("stock")],
      TODAY,
    );
    // 截断放在 `browse.ts`（那里能一并给出 staleMore）；在这里 slice 会把第三类**静默藏掉**，
    // 而 10-02 的活体探针正是撞在这上面：stock／bond／crypto 同日陈旧，屏上只剩两条。
    expect(n.map((x) => x.type)).toEqual(["stock", "fund", "bond", "crypto", "hk", "us"]);
  });

  it("list 优先于 snapshot：同一类两者都陈旧时只说一次（snapAt 为 null 时两者同源）", () => {
    const n = staleNotes(
      [{ type: "crypto", listAt: bj("2026-09-27", "11:38"), snapAt: bj("2026-09-27", "11:40"), maxPrice: null }],
      TODAY,
    );
    expect(n).toEqual([{ type: "crypto", kind: "list", since: "2026-09-27" }]);
  });

  it("该类 0 行（groupBy 不返回这一类）⇒ 不报：空表在页面上就是空列表，不需要一句陈旧", () => {
    expect(staleNotes([], TODAY)).toEqual([]);
  });

  it("🔁 三种成因混在一晚：list／pending／snapshot 各占一类 ⇒ 各自归各自、顺序仍按 tab", () => {
    const n = staleNotes(
      [
        { type: "stock", listAt: bj("2026-09-12", "23:37"), snapAt: bj(TODAY, "02:01"), maxPrice: 1700 },
        { type: "fund", listAt: bj(TODAY, "02:00"), snapAt: null, maxPrice: null },
        { type: "bond", listAt: bj(TODAY, "02:00"), snapAt: bj("2026-09-25", "20:22"), maxPrice: 100 },
      ],
      TODAY,
    );
    expect(n).toEqual([
      { type: "stock", kind: "list", since: "2026-09-12" },
      { type: "fund", kind: "pending", since: TODAY },
      { type: "bond", kind: "snapshot", since: "2026-09-25" },
    ]);
  });
});

describe("分类浏览的类型集合（CR9-75：从「锁住不开」换成「锁住已答」）", () => {
  // 主人 2026-10-04 的字＝「#32 甲先做，**先不用开美股 tab**」；10-07 14:0x 他亲手撤了这句
  // （「us 有了之后开新 tab」）⇒ 本条换方向，可它原来那份用途一个字都不减：**把连带义务钉在
  // 动名单的那一刻**——谁改 `BROWSE_TYPES`，就得在这里回答当初被预先问出的两件事：
  //   ① 美股有没有快照刷新？⇒ 有。CR9-74 把 us 收进 `SNAPSHOT_TYPES`，10-07 13:41 实测
  //      `total 179／updated 179／batches 2`，只读 SQL 复核 `priced=179 snapshotAtNotNull=179`
  //      ⇒ `pending` 那一档不会夜夜说话（这才是 10-04 那条边界当时真正在防的事）。
  //   ② 三档陈旧文案适用于英文名吗？⇒ 适用：屏上那句取的是 `STALE_PHRASE` 里的**中文类名**
  //      （「美股」来自 `TYPE_LABEL`），不是标的自己的英文名。
  // 名单继续逐字列出（追加三十五 ⑤：镜像生产的常量红是成本不是风险，改派生而不是放宽）。
  // ⚠️ 一处仍未被证住的边界：`TABS`（住在客户端组件）与这份名单**没有交叉断言**——把 TABS
  //    import 进 lib 测试会连带拖进 `next/navigation` ⇒ 两处一起动目前靠注释与本条。
  it("美股进 BROWSE_TYPES（有 tab；两件连带义务都在上面答了）", () => {
    expect(BROWSE_TYPES).toContain("us");
    expect([...BROWSE_TYPES]).toEqual(["stock", "fund", "bond", "crypto", "hk", "us"]);
  });
});

// #22(b) 乙（主人 10-16 定档）＝「快照截至 X（覆盖 N/M）」的数据层出口。
// 这一枚要钉的不是文案（文案住在 `app/search/search-client.tsx`，归主人改），而是三个
// 「不许」：不许谎报时刻、不许在没有分母时编一个 0/0、不许把分子当总行数。
describe("快照出处 snapshotBadge（#22(b) 乙）", () => {
  const row = (type: string, total: number, snapCount: number, snapAt: Date | null) => ({
    type,
    listAt: snapAt,
    snapAt,
    maxPrice: 1,
    total,
    snapCount,
  });

  it("覆盖数与总行数逐类相加，asOf 取各类快照里**最近**的那一枚", () => {
    const b = snapshotBadge([
      row("stock", 5573, 5572, bj("2026-10-01", "20:17")),
      row("bond", 1061, 314, bj("2026-10-02", "02:40")),
    ]);
    expect(b).toEqual({
      asOf: bj("2026-10-02", "02:40"),
      covered: 5886,
      total: 6634,
      byType: [
        { type: "stock", total: 5573, snapCount: 5572, snapAt: bj("2026-10-01", "20:17"), absent: false },
        { type: "bond", total: 1061, snapCount: 314, snapAt: bj("2026-10-02", "02:40"), absent: false },
      ],
    });
  });

  it("🔁 反向：asOf 不得取最早那一枚（把昨天说成更旧＝反向误导）", () => {
    const b = snapshotBadge([
      row("stock", 10, 5, bj("2026-09-20", "09:00")),
      row("fund", 10, 5, bj("2026-10-02", "09:00")),
    ]);
    expect(b?.asOf).toEqual(bj("2026-10-02", "09:00"));
  });

  it("没有行 ⇒ null（hk 那一形：没有分母就不说话，不许写 0/0）", () => {
    expect(snapshotBadge([])).toBeNull();
    expect(snapshotBadge([row("hk", 0, 0, null)])).toBeNull();
  });

  it("🔁 半样本：同一类只要有一行，就必须给出数而不是 null", () => {
    expect(snapshotBadge([row("hk", 1, 0, null)])).not.toBeNull();
  });

  it("有行但一行快照都没落过 ⇒ 不谎报时刻（asOf 为 null），覆盖仍照实说", () => {
    expect(snapshotBadge([row("crypto", 250, 0, null)])).toEqual({
      asOf: null,
      covered: 0,
      total: 250,
      byType: [{ type: "crypto", total: 250, snapCount: 0, snapAt: null, absent: false }],
    });
  });

  it("groupBy 的那一列分子读的是 `_count.snapshotAt`（字段名改错就要红，不是静默变 0）", async () => {
    groupBy.mockResolvedValue([
      { type: "stock", _max: { updatedAt: null, snapshotAt: null, lastPrice: null }, _count: { _all: 7, snapshotAt: 3 } },
    ]);
    const rows = await freshnessOfTypes({ type: "stock" });
    expect(rows[0]).toMatchObject({ total: 7, snapCount: 3 });
    expect(snapshotBadge(rows)).toEqual({
      asOf: null,
      covered: 3,
      total: 7,
      byType: [{ type: "stock", total: 7, snapCount: 3, snapAt: null, absent: false }],
    });
  });

  it("🔁 反向：Prisma 没给 `_count.snapshotAt` 时按 0 计，不得把 undefined 加进分母", async () => {
    groupBy.mockResolvedValue([
      { type: "stock", _max: { updatedAt: null, snapshotAt: null, lastPrice: null }, _count: { _all: 7 } },
    ]);
    const rows = await freshnessOfTypes({ type: "stock" });
    expect(rows[0].snapCount).toBe(0);
    expect(snapshotBadge(rows)?.covered).toBe(0);
  });

  // B3（主人 10-18 的字＝「先补全B3文案」）＝「缺在哪一类」必须是读得出的一维。
  // 屏上那句「覆盖 N／M」不动（10-17 已定稿＝一字不改）——补的是机器可读位。
  const SCOPE = ["stock", "fund", "hk"];
  const twoRows = [row("stock", 5576, 5575, bj("2026-10-17", "02:02")), row("fund", 28086, 23856, bj("2026-10-17", "02:08"))];

  it("B3：给了范围名单 ⇒ byType 按名单顺序逐类给 total/snapCount/snapAt", () => {
    const b = snapshotBadge(twoRows, SCOPE);
    expect(b?.byType).toEqual([
      { type: "stock", total: 5576, snapCount: 5575, snapAt: bj("2026-10-17", "02:02"), absent: false },
      { type: "fund", total: 28086, snapCount: 23856, snapAt: bj("2026-10-17", "02:08"), absent: false },
      { type: "hk", total: 0, snapCount: 0, snapAt: null, absent: true },
    ]);
  });

  it("🔁 牙齿：tab 里有入口而库里一行都没有的那一类，必须被说成 absent，不许在求和里静默消失", () => {
    // hk 正是这一形（10-18 现查库内 hk 无行）。摘掉 byType 那圈补齐 ⇒ 这一条红，
    // 而上面三条老断言（只读求和）在全绿——证明求和本身看不见缺席。
    const hk = snapshotBadge(twoRows, SCOPE)?.byType.find((x) => x.type === "hk");
    expect(hk).toMatchObject({ total: 0, snapCount: 0, absent: true });
    expect(snapshotBadge(twoRows, SCOPE)?.byType.map((x) => x.type)).toEqual(SCOPE);
  });

  it("🔁 反向：不传名单时不得凭空造出库里没有的那一类（浏览单类时尤其要说清范围）", () => {
    expect(snapshotBadge(twoRows)?.byType.map((x) => x.type)).toEqual(["stock", "fund"]);
  });

  it("补 byType 之后 covered/total/asOf 三个值逐字不变（缺席那一类不进分母＝屏上那句仍然说实话）", () => {
    const plain = snapshotBadge(twoRows);
    const withHk = snapshotBadge(twoRows, SCOPE);
    // 这三枚才是屏上那句话读的东西：名单里多出一类缺席，求和一位都不许动。
    expect(withHk?.covered).toBe(plain?.covered);
    expect(withHk?.total).toBe(plain?.total);
    expect(withHk?.asOf).toEqual(plain?.asOf);
    expect(withHk).toMatchObject({ asOf: bj("2026-10-17", "02:08"), covered: 29431, total: 33662 });
  });
});
