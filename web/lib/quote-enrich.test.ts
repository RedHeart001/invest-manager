import { describe, expect, it, vi } from "vitest";

import { DS_QUOTES_MAX_CODES, chunkCodes } from "./quote-enrich";

// 接线断言用的替身：`fetchQuotesByType` 内部调 `./data-service` 的 `fetchQuotes`。
// ⚠️ 这一组存在的理由是一次**钻出来的空档**（2026-11-01）：只测 `chunkCodes` 时，
// 把 `fetchQuotesByType` 里的 `for (const chunk of chunkCodes(codes))` 回退成
// `for (const chunk of [codes])` ——6 条断言**全绿**，因为纯函数本身没坏、坏的是没人调它。
// ⇒ 判据必须是"**实际发出的 codes 组数**"，不是"chunkCodes 会不会切"。
const sent: string[][] = [];
vi.mock("./data-service", () => ({
  fetchQuotes: async (_type: string, codes: string[]) => {
    sent.push(codes);
    return { quotes: Object.fromEntries(codes.map((c) => [c, { price: 1, changePct: 0 }])), usesEastmoney: false };
  },
}));

// R18（2026-11-01）：`/quotes` 的服务端硬上限是**静默截断**（`main.py` 的 `[:100]`），
// 越过的 code 一个价都不回来、不报错。自选清单页按类型送全量 ⇒ 必须在此分批。
// 这组断言守的就是"第 101 只开始安静地没有价格"这一形。

describe("chunkCodes（R18 分批）", () => {
  const codes = (n: number) => Array.from({ length: n }, (_, i) => `c${i}`);

  it("① 不超上限 ⇒ 原样一批（常见的 ≤50 条路径不许多出一次出网）", () => {
    expect(chunkCodes(codes(50))).toEqual([codes(50)]);
  });

  it("② 恰好等于上限 ⇒ 仍是一批（边界不多切）", () => {
    expect(chunkCodes(codes(DS_QUOTES_MAX_CODES))).toHaveLength(1);
  });

  it("③ 🔁 反向：上限 +1 ⇒ 切成两批，且**一条都不许丢**（旧实现丢的就是这第 101 条）", () => {
    const input = codes(DS_QUOTES_MAX_CODES + 1);
    const out = chunkCodes(input);
    expect(out).toHaveLength(2);
    expect(out.flat()).toEqual(input); // 逐条相等，不是"长度相等"
    expect(out[0]).toHaveLength(DS_QUOTES_MAX_CODES);
    expect(out[1]).toHaveLength(1);
  });

  it("④ 每批都不超上限（判据从数据取，不硬编码批数）", () => {
    const input = codes(347);
    const out = chunkCodes(input);
    for (const c of out) expect(c.length).toBeLessThanOrEqual(DS_QUOTES_MAX_CODES);
    expect(out.flat()).toEqual(input);
    expect(out.length).toBe(Math.ceil(347 / DS_QUOTES_MAX_CODES));
  });

  it("⑤ 空输入 ⇒ 零批（不许造一个空批去打 ds——那会 400 codes is empty）", () => {
    expect(chunkCodes([])).toEqual([]);
  });

  it("⑥ 上限常量与 ds 侧镜像（改了 ds 的切片长度就要改这里）", () => {
    expect(DS_QUOTES_MAX_CODES).toBe(100);
  });
});

describe("fetchQuotesByType 真的用上了分批（接线，不是纯函数）", () => {
  it("⑦ 🔁 反向：150 只同类 ⇒ 实际发出 **2 次** fetchQuotes，且每次都 ≤ 上限", async () => {
    const { fetchQuotesByType } = await import("./quote-enrich");
    sent.length = 0;
    const items = Array.from({ length: 150 }, (_, i) => ({ type: "stock", code: `c${i}` }));
    const m = await fetchQuotesByType(items);
    expect(sent).toHaveLength(2);
    for (const batch of sent) expect(batch.length).toBeLessThanOrEqual(DS_QUOTES_MAX_CODES);
    expect(sent[0].length + sent[1].length).toBe(150);
    // 第 101 条（旧实现静默丢掉的那一条）必须在结果里
    expect(m.has("stock:c100")).toBe(true);
    expect(m.size).toBe(150);
  });

  it("⑧ 🔁 反向：60 只同类 ⇒ 仍只发 1 次（分批不许给常见路径凭空多出出网）", async () => {
    const { fetchQuotesByType } = await import("./quote-enrich");
    sent.length = 0;
    await fetchQuotesByType(Array.from({ length: 60 }, (_, i) => ({ type: "stock", code: `d${i}` })));
    expect(sent).toHaveLength(1);
  });

  it("⑨ 跨类型各自独立分批，键按 type:code 组装（不串类）", async () => {
    const { fetchQuotesByType } = await import("./quote-enrich");
    sent.length = 0;
    const m = await fetchQuotesByType([
      { type: "stock", code: "600519" },
      { type: "hk", code: "00700" },
      { type: "zzz", code: "X" }, // 表外类型：不许出网
    ]);
    expect(sent).toHaveLength(2); // stock 一次 + hk 一次，zzz 被 ENRICH_TYPES 挡掉
    expect([...m.keys()].sort()).toEqual(["hk:00700", "stock:600519"]);
  });
});
