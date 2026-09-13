import { describe, expect, it } from "vitest";

import { parseTags, scoreProduct } from "./score";

const maotai = {
  code: "600519",
  name: "贵州茅台",
  pinyin: "guizhoumaotai",
  pinyinInitials: "gzmt",
  tags: JSON.stringify(["白酒"]),
};

describe("scoreProduct 召回与排序", () => {
  it("空查询返回 0", () => {
    expect(scoreProduct("", maotai)).toBe(0);
    expect(scoreProduct("   ", maotai)).toBe(0);
  });

  it("代码精确匹配得分最高", () => {
    const exact = scoreProduct("600519", maotai);
    const prefix = scoreProduct("6005", maotai);
    const nameHit = scoreProduct("茅台", maotai);
    expect(exact).toBeGreaterThan(prefix);
    expect(prefix).toBeGreaterThan(nameHit);
  });

  it("名称精确 > 名称前缀 > 名称包含", () => {
    expect(scoreProduct("贵州茅台", maotai)).toBeGreaterThan(scoreProduct("贵州", maotai));
    expect(scoreProduct("贵州", maotai)).toBeGreaterThan(scoreProduct("茅台", maotai));
  });

  it("中文子串可命中（二元组场景）", () => {
    const p = { code: "000001", name: "华夏成长混合", pinyin: "huaxiachengzhang", pinyinInitials: "hxcz", tags: null };
    expect(scoreProduct("成长", p)).toBeGreaterThan(0);
    expect(scoreProduct("华夏", p)).toBeGreaterThan(0);
  });

  it("拼音与首字母可命中", () => {
    expect(scoreProduct("guizhou", maotai)).toBeGreaterThan(0);
    expect(scoreProduct("gzmt", maotai)).toBeGreaterThan(0);
    expect(scoreProduct("gz", maotai)).toBeGreaterThan(0);
  });

  it("标签命中得分低于名称命中", () => {
    const tag = scoreProduct("白酒", maotai);
    const name = scoreProduct("贵州", maotai);
    expect(tag).toBeGreaterThan(0);
    expect(name).toBeGreaterThan(tag);
  });

  it("自选加权提升排序", () => {
    const base = scoreProduct("茅台", maotai);
    const watched = scoreProduct("茅台", maotai, { inWatchlist: true });
    expect(watched).toBe(base + 15);
  });

  it("历史点击加权，封顶 15", () => {
    const base = scoreProduct("茅台", maotai);
    expect(scoreProduct("茅台", maotai, { clicks: 2 })).toBe(base + 6);
    expect(scoreProduct("茅台", maotai, { clicks: 100 })).toBe(base + 15);
  });

  it("仅 FTS 命中的候选得基础分 25", () => {
    const other = { code: "999999", name: "无关标的", pinyin: "", pinyinInitials: "", tags: null };
    expect(scoreProduct("茅台", other, { ftsHit: true })).toBe(25);
    expect(scoreProduct("茅台", other)).toBe(0);
  });

  it("违规 JSON 的 tags 不抛错", () => {
    expect(parseTags("not-json")).toEqual([]);
    expect(parseTags(null)).toEqual([]);
    expect(parseTags('["A","B"]')).toEqual(["A", "B"]);
  });
});
