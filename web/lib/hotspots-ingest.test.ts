import { beforeEach, describe, expect, it, vi } from "vitest";

// D1（CR7-11）：ingestDigests 两条此前只靠集成测试覆盖的语义——
// ① (date,title) 200 字截断去重（库内与入库双侧一致）
// ② P2002 唯一约束竞态分支（并发 ingest 的"先读后写"兜底，CR-11）
// prisma 全 mock，不触真实库。

const findMany = vi.fn();
const create = vi.fn();
const productFindMany = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    hotspotDigest: { findMany: (...a: unknown[]) => findMany(...a), create: (...a: unknown[]) => create(...a) },
    product: { findMany: (...a: unknown[]) => productFindMany(...a) },
  },
}));

import { ingestDigests, isDelistedName, toDigestRow } from "./hotspots";

const dbRow = (over: Record<string, unknown> = {}) => ({
  id: "r1",
  date: new Date("2026-09-25T00:00:00.000Z"),
  title: "t",
  summary: "",
  boardTags: "[]",
  sourceUrls: "[]",
  relatedCodes: "[]",
  newsSource: null,
  engine: null,
  degraded: false,
  note: null,
  createdAt: new Date(),
  updatedAt: new Date(),
  ...over,
});

beforeEach(() => {
  findMany.mockReset();
  create.mockReset();
  productFindMany.mockReset();
  productFindMany.mockResolvedValue([]); // resolveRelated：无成分股/基金
});

describe("ingestDigests（D1：去重与竞态）", () => {
  it("① 库内已有前 200 字相同的长标题 → 截断去重命中，skipped", async () => {
    const longTitle = "长".repeat(250);
    findMany.mockResolvedValue([{ title: longTitle }]); // 库内存的是未截断原串
    create.mockResolvedValue(dbRow());
    const res = await ingestDigests({
      date: "2026-09-25",
      items: [{ title: longTitle.slice(0, 200) }], // 新批次标题被截断到 200
    });
    expect(res.skipped).toBe(1);
    expect(res.inserted).toBe(0);
    expect(create).not.toHaveBeenCalled();
  });

  it("①b 同批内重复标题 → 第二条 skipped", async () => {
    findMany.mockResolvedValue([]);
    create.mockResolvedValue(dbRow());
    const res = await ingestDigests({
      date: "2026-09-25",
      items: [{ title: "同一条新闻" }, { title: "同一条新闻" }],
    });
    expect(res.inserted).toBe(1);
    expect(res.skipped).toBe(1);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("② create 抛 P2002（并发先读后写竞态）→ 按已存在处理，不重复卡片", async () => {
    findMany.mockResolvedValue([]); // 读时库里没有
    create.mockRejectedValueOnce({ code: "P2002" }); // 写时撞唯一约束
    create.mockResolvedValue(dbRow());
    const res = await ingestDigests({
      date: "2026-09-25",
      items: [{ title: "竞态标题" }, { title: "后续正常标题" }],
    });
    expect(res.inserted).toBe(1); // 第二条正常入库
    expect(res.skipped).toBe(1); // P2002 的那条跳过
  });

  it("②b 非 P2002 错误原样上抛（不吞真实故障）", async () => {
    findMany.mockResolvedValue([]);
    create.mockRejectedValueOnce(new Error("db down"));
    await expect(
      ingestDigests({ date: "2026-09-25", items: [{ title: "x" }] }),
    ).rejects.toThrow("db down");
  });

  it("③ 非法 date 前置拒绝", async () => {
    await expect(
      ingestDigests({ date: "20260925", items: [] }),
    ).rejects.toThrow("invalid date");
  });
});

// CR8-8（2026-09-30）：板块成分表含陈旧成员（`600200 退市苏吴`、`600086 退市金钰`），
// resolveRelated 原样当"相关产品"推荐 ⇒ 点进详情页是死路。主人定口径：**只滤退市**，
// ST/*ST 与北交所保留。判据取 Product 的库内权威名（Product 无上市状态字段）。
describe("resolveRelated（CR8-8：退市股不得作为相关产品）", () => {
  const onlyStocks = (rows: Array<{ code: string; name: string }>) =>
    productFindMany.mockImplementation((args: { where?: { type?: string } }) =>
      Promise.resolve(args?.where?.type === "stock" ? rows : []),
    );

  const stored = () =>
    JSON.parse(create.mock.calls[0][0].data.relatedCodes) as Array<{ code: string; name: string }>;

  const ingestWith = async (relatedCodes: Array<{ code: string; name: string }>) => {
    findMany.mockResolvedValue([]);
    create.mockResolvedValue(dbRow());
    await ingestDigests({
      date: "2026-09-30",
      items: [
        {
          title: "创新药BD出海持续兑现",
          boardTags: [],
          relatedCodes: relatedCodes.map((r) => ({ type: "stock", board: "创新药", ...r })),
        },
      ],
    });
  };

  it("① 库内权威名含「退市」的成分股被剔除，其余保留", async () => {
    onlyStocks([
      { code: "600200", name: "退市苏吴" },
      { code: "600056", name: "中国医药" },
    ]);
    await ingestWith([
      { code: "600200", name: "退市苏吴" },
      { code: "600056", name: "中国医药" },
    ]);
    expect(stored().map((r) => r.code)).toEqual(["600056"]);
  });

  it("①b 🔁 反向：ST / *ST / 北交所一律保留（口径只有退市）", async () => {
    onlyStocks([
      { code: "600080", name: "ST金花" },
      { code: "600311", name: "*ST荣华" },
      { code: "920047", name: "诺思兰德" },
      { code: "600056", name: "中国医药" },
    ]);
    await ingestWith([
      { code: "600080", name: "ST金花" },
      { code: "600311", name: "*ST荣华" },
      { code: "920047", name: "诺思兰德" },
      { code: "600056", name: "中国医药" },
    ]);
    expect(stored().map((r) => r.code)).toEqual(["600080", "600311", "920047", "600056"]);
  });

  it("①c 判据取库内权威名，不取成分表回传名（成分表那侧的名字不可信）", async () => {
    onlyStocks([{ code: "600200", name: "退市苏吴" }]);
    // 成分表侧传来的名字里没有「退市」，只有库内名字有 ⇒ 仍须被滤
    await ingestWith([{ code: "600200", name: "江苏吴中" }]);
    expect(stored()).toEqual([]);
  });

  it("①d 库内查不到的成分股仍按原语义丢弃（本修复不放宽既有过滤）", async () => {
    onlyStocks([{ code: "600056", name: "中国医药" }]);
    await ingestWith([
      { code: "600056", name: "中国医药" },
      { code: "999999", name: "库内无此标的" },
    ]);
    expect(stored().map((r) => r.code)).toEqual(["600056"]);
  });

  it("①e isDelistedName 真值表：只认「退市」，不认 ST/北交所", () => {
    expect([isDelistedName("退市金钰"), isDelistedName("退市苏吴")]).toEqual([true, true]);
    expect([
      isDelistedName("ST金花"),
      isDelistedName("*ST荣华"),
      isDelistedName("诺思兰德"),
      isDelistedName("中国医药"),
    ]).toEqual([false, false, false, false]);
  });
});

// CR8-3（2026-10-01）：`sourceUrls` 从裸 URL 升级为 `{url,title}`（标题此前在 ds
// 返回时被丢掉，前端拿不到 ⇒ 三个无差别的「原文」）。写侧归一化 + 读侧兼容存量
// 纯字符串行——同 CR8-8 那条教训：**只改写侧会留下存量缺口**。
describe("sourceUrls（CR8-3：{url,title} 透传与存量兼容）", () => {
  const storedUrls = () =>
    JSON.parse(create.mock.calls[0][0].data.sourceUrls) as Array<{
      url: string;
      title: string;
    }>;

  const ingestUrls = async (sourceUrls: unknown) => {
    findMany.mockResolvedValue([]);
    create.mockResolvedValue(dbRow());
    await ingestDigests({
      date: "2026-10-01",
      items: [{ title: "标题透传", sourceUrls }],
    });
  };

  const readUrls = (raw: string) =>
    toDigestRow(dbRow({ sourceUrls: raw }) as Parameters<typeof toDigestRow>[0]).sourceUrls;

  it("① 新契约 {url,title} 原样落库", async () => {
    await ingestUrls([{ url: "https://a.com/x", title: "芯片设备板块领涨" }]);
    expect(storedUrls()).toEqual([{ url: "https://a.com/x", title: "芯片设备板块领涨" }]);
  });

  it("①b 旧契约裸字符串 → 补 title 空串，不整条丢弃", async () => {
    await ingestUrls(["https://old.com/1", "https://old.com/2"]);
    expect(storedUrls()).toEqual([
      { url: "https://old.com/1", title: "" },
      { url: "https://old.com/2", title: "" },
    ]);
  });

  it("①c 🔁 反向：脏元素（null/数字/空串/无 url/空 url）被滤，合法元素不受牵连", async () => {
    await ingestUrls([
      null,
      7,
      "",
      { title: "没有链接" },
      { url: "" },
      { url: "https://ok.com", title: undefined },
    ]);
    expect(storedUrls()).toEqual([{ url: "https://ok.com", title: "" }]);
  });

  it("①d 非数组入参按原语义落空数组（本改动不放宽既有兜底）", async () => {
    await ingestUrls("https://not-an-array");
    expect(storedUrls()).toEqual([]);
  });

  it("①e 仍截断到 5 条（本改动不放宽既有上限）", async () => {
    await ingestUrls(
      Array.from({ length: 8 }, (_, i) => ({ url: `https://a.com/${i}`, title: `t${i}` })),
    );
    expect(storedUrls()).toHaveLength(5);
  });

  it("② 读侧：存量行的裸字符串补 title 空串（不重写库也能渲染）", () => {
    expect(readUrls('["https://old.com/1"]')).toEqual([
      { url: "https://old.com/1", title: "" },
    ]);
  });

  it("②b 读侧：新形状原样读出，标题不丢", () => {
    expect(readUrls('[{"url":"https://a.com/x","title":"标题 A"}]')).toEqual([
      { url: "https://a.com/x", title: "标题 A" },
    ]);
  });

  it("②c 读侧：脏 JSON 仍回退空数组", () => {
    expect(readUrls("{not json")).toEqual([]);
  });
});

// CR8-8 的另一半：ingest 侧过滤只治**新批次**，历史行的 relatedCodes 里已经存着
// 摘牌股 ⇒ 读侧（toDigestRow）必须同样剔除，否则"修了但首页还看得到"。
describe("toDigestRow（CR8-8 读侧：存量行的退市成分不再出现）", () => {
  const rowWith = (related: unknown) =>
    toDigestRow(
      dbRow({ relatedCodes: JSON.stringify(related) }) as Parameters<typeof toDigestRow>[0],
    );

  it("② 存量 relatedCodes 里的退市股在读取时被剔除，其余原样保留（顺序不变）", () => {
    const row = rowWith([
      { type: "stock", code: "600056", name: "中国医药", board: "创新药" },
      { type: "stock", code: "600200", name: "退市苏吴", board: "创新药" },
      { type: "fund", code: "012737", name: "广发创新药ETF联接A", board: "创新药" },
    ]);
    expect(row.related.map((p) => p.code)).toEqual(["600056", "012737"]);
  });

  it("②b 🔁 反向：只判 stock——名称含「退市」的**基金**不得被剔（口径不扩大）", () => {
    const row = rowWith([
      { type: "fund", code: "019999", name: "退市股票主题基金", board: "创新药" },
      { type: "stock", code: "600080", name: "ST金花", board: "创新药" },
    ]);
    expect(row.related.map((p) => p.code)).toEqual(["019999", "600080"]);
  });

  it("②c 脏 JSON 仍按原语义回退空数组（本修复不放宽既有兜底）", () => {
    const row = toDigestRow(
      dbRow({ relatedCodes: "{not json" }) as Parameters<typeof toDigestRow>[0],
    );
    expect(row.related).toEqual([]);
  });
});
