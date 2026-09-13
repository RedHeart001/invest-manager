import { describe, expect, it } from "vitest";

import { bigrams, buildMatchQuery, buildSearchText } from "./search-text";

describe("中文二元组展开", () => {
  it("中文串展开为二元组", () => {
    expect(bigrams("贵州茅台")).toEqual(["贵州", "州茅", "茅台"]);
  });

  it("单字返回自身", () => {
    expect(bigrams("茅")).toEqual(["茅"]);
  });

  it("混合串只取中文段", () => {
    expect(bigrams("华夏成长混合A")).toEqual([
      "华夏",
      "夏成",
      "成长",
      "长混",
      "混合",
    ]);
  });
});

describe("searchText 构建", () => {
  const text = buildSearchText({
    name: "贵州茅台",
    code: "600519",
    pinyin: "guizhoumaotai",
    pinyinInitials: "gzmt",
    tags: ["白酒"],
  });

  it("包含名称、二元组、拼音、首字母、代码、标签", () => {
    for (const token of ["贵州茅台", "茅台", "guizhoumaotai", "gzmt", "600519", "白酒"]) {
      expect(text).toContain(token);
    }
  });

  it("全小写（与查询侧归一化一致）", () => {
    expect(text).toBe(text.toLowerCase());
  });
});

describe("MATCH 查询构建", () => {
  it("中文查询含二元组与整串", () => {
    const m = buildMatchQuery("茅台");
    expect(m).toContain('"茅台"');
  });

  it("拼音查询保留 ASCII 词元", () => {
    const m = buildMatchQuery("gzmt");
    expect(m).toContain('"gzmt"');
  });

  it("空查询返回 null", () => {
    expect(buildMatchQuery("   ")).toBeNull();
  });

  it("双引号被转义（防注入 FTS 语法）", () => {
    const m = buildMatchQuery('a"b');
    expect(m).not.toContain('"a"b"');
  });
});
