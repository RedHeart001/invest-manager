import { describe, expect, it } from "vitest";

import type { QuoteLike } from "./quote-enrich";
import { groupWatchlist, quotesAllMissing, WATCH_TYPE_ORDER } from "./watchlist";

// R18（2026-11-01）：自选清单页的数据整形。
// 这一组断言守的都是"绿着坏掉"的形态——页面上少一组、顺序乱跳、缺价说成 0 分，
// 起服务手测很难看出来，而它们全部是纯函数可判定的。

const rows = (...spec: [type: string, code: string, name: string][]) =>
  spec.map(([type, code, name]) => ({ type, code, name }));

function quotes(entries: Record<string, Partial<QuoteLike>>): Map<string, QuoteLike> {
  const m = new Map<string, QuoteLike>();
  for (const [k, v] of Object.entries(entries)) {
    m.set(k, { price: null, changePct: null, ...v });
  }
  return m;
}

describe("groupWatchlist（R18）", () => {
  it("① 分组顺序是固定表序，不随输入顺序变", () => {
    // 故意把 us 写在最前、stock 写在最后
    const g = groupWatchlist(
      rows(["us", "CEG", "Constellation"], ["hk", "00700", "腾讯控股"], ["stock", "600519", "贵州茅台"]),
      new Map(),
    );
    expect(g.map((x) => x.type)).toEqual(["stock", "hk", "us"]);
  });

  it("② 🔁 反向：表序里没有的类型不得被丢掉，排在最后且保持出现顺序", () => {
    const g = groupWatchlist(
      rows(["zzz", "X1", "脏数据一"], ["stock", "600519", "贵州茅台"], ["aaa", "X2", "脏数据二"]),
      new Map(),
    );
    expect(g.map((x) => x.type)).toEqual(["stock", "zzz", "aaa"]);
    // 不猜类名、原样透出 type，屏上由 `TYPE_LABEL[t] ?? t` 兜底
    expect(g[1].label).toBe("zzz");
  });

  it("③ 同一类型内的相对顺序＝输入的相对顺序（调用方按 createdAt desc 查，故屏上是新→旧）", () => {
    const g = groupWatchlist(
      rows(["stock", "000001", "平安银行"], ["stock", "600519", "贵州茅台"]),
      new Map(),
    );
    expect(g[0].items.map((x) => x.code)).toEqual(["000001", "600519"]);
  });

  it("④ 行情键按 `type:code` 取——跨类型同名 code 不许串（stock 000001 与 hk 00001 是两只）", () => {
    const g = groupWatchlist(
      rows(["stock", "000001", "平安银行"], ["hk", "00001", "长和"]),
      quotes({ "stock:000001": { price: 11.2 }, "hk:00001": { price: 55.5, currency: "HKD" } }),
    );
    const stock = g.find((x) => x.type === "stock")!.items[0];
    const hk = g.find((x) => x.type === "hk")!.items[0];
    expect(stock.price).toBe(11.2);
    expect(stock.currency).toBeNull();
    expect(hk.price).toBe(55.5);
    expect(hk.currency).toBe("HKD");
  });

  it("⑤ 取不到价 ⇒ price 为 null 且 quoted=false（不许填 0、不许沿用别的字段）", () => {
    const g = groupWatchlist(rows(["stock", "600519", "贵州茅台"]), new Map());
    expect(g[0].items[0].price).toBeNull();
    expect(g[0].items[0].quoted).toBe(false);
  });

  it("⑥ 上游给了价但 changePct 缺失 ⇒ quoted 仍为 true（有价就是有价，涨跌幅缺失另有其因）", () => {
    const g = groupWatchlist(
      rows(["stock", "600519", "贵州茅台"]),
      quotes({ "stock:600519": { price: 1275.16, changePct: null } }),
    );
    expect(g[0].items[0].quoted).toBe(true);
    expect(g[0].items[0].changePct).toBeNull();
  });

  it("⑦ 空自选 ⇒ 零组（页面据此走空态，而不是渲染一个空壳分组）", () => {
    expect(groupWatchlist([], new Map())).toEqual([]);
  });
});

describe("quotesAllMissing（R18 的降级判据）", () => {
  it("⑧ 有自选但一条行情都没有 ⇒ true（这才该出降级说明）", () => {
    expect(quotesAllMissing(rows(["stock", "600519", "贵州茅台"]), new Map())).toBe(true);
  });

  it("⑨ 🔁 反向：空自选 ⇒ false（不许把「还没有自选」说成「行情取不到」）", () => {
    expect(quotesAllMissing([], new Map())).toBe(false);
  });

  it("⑩ 🔁 反向：只要有一条到价 ⇒ false（单只缺价是上游常态，逐条报就是噪音）", () => {
    const r = rows(["stock", "600519", "贵州茅台"], ["stock", "000001", "平安银行"]);
    expect(quotesAllMissing(r, quotes({ "stock:600519": { price: 1275.16 } }))).toBe(false);
  });
});

describe("WATCH_TYPE_ORDER 与类型白名单同集", () => {
  it("⑪ 名单就是六类行情，「全部」不是一类（自选存不进 all）", () => {
    expect([...WATCH_TYPE_ORDER]).toEqual(["stock", "fund", "bond", "crypto", "hk", "us"]);
  });
});
