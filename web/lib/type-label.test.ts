import { describe, expect, it } from "vitest";

import { QUOTE_TYPES } from "./validate";
import { TYPE_LABEL } from "./type-label";

// R18（2026-11-01）：`TYPE_LABEL` 从两处硬写抽成单一来源后，必须把"与类型白名单同集"
// 这条隐性契约变成可执行的断言——少一个键时界面不会报错，只会把那一类显示成英文标识
// （`TYPE_LABEL[t] ?? t` 的兜底），是典型"绿着坏掉"的形态。

describe("TYPE_LABEL（R18 单一来源）", () => {
  it("① 键集合与 QUOTE_TYPES 完全同集（多一个／少一个都红）", () => {
    expect(Object.keys(TYPE_LABEL).sort()).toEqual([...QUOTE_TYPES].sort());
  });

  it("② 每个值都是非空中文名，且不与键相同（兜底失效时可辨认）", () => {
    for (const t of QUOTE_TYPES) {
      const label = TYPE_LABEL[t];
      expect(typeof label).toBe("string");
      expect(label.length).toBeGreaterThan(0);
      expect(label).not.toBe(t);
    }
  });
});
