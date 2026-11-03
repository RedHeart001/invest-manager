/**
 * CR10-13 离线单测：列表载荷的**重复即点名**（`#95` 的甲＋那一半）。
 *
 * `#95` 那一夜读到的只有 `Raw query failed. Code: 2067. Message: UNIQUE constraint failed: Product.type, Product.code`
 * ——谁重复了，账上读不出来（成因只能靠我逐行读码做排除法）。本枚不改数据、不碰唯一键，
 * 只把"重复了哪几枚 `(type,code)`"变成机器可读的 `dupCodes`，**并且要挂在失败那一条返回上**
 * （那一发恰恰是失败那一格读到的）。
 *
 * 刻意不写进 `note`：`web/app/HotspotFeed.tsx:259` 会把 note 取到屏上，而"哪几枚 code 重复"
 * 是开发者向的数（10-05 那条口径：屏上只留"谁缺席、还剩几条"）。第 5 枚用例钉住这条边界。
 *
 * 运行：`npx vitest run lib/sync-dup-codes.test.ts`（零出网，不打 data-service）
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { findDuplicateCodes } from "./sync";

const SYNC_SRC = readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), "sync.ts"),
  "utf-8",
);

/** 调用方真实形状（`_syncTypeInner` 里 `rows` 的枚形）：只多塞本判据要读的三枚键 */
const row = (type: string, code: string, name: string = code) => ({ type, code, name });

describe("CR10-13：findDuplicateCodes 与它的接线", () => {
  it("含重复 ⇒ 点名，按首次出现序，键形 `type:code`", () => {
    const rows = [row("crypto", "BTCUSDT"), row("crypto", "ETHUSDT"), row("crypto", "BTCUSDT")];
    expect(findDuplicateCodes(rows)).toEqual(["crypto:BTCUSDT"]);
  });

  it("🔁 全唯一 ⇒ 该键必须缺席（不许交出一个空数组当「点名了」）", () => {
    expect(findDuplicateCodes([row("stock", "600519"), row("stock", "000001")])).toBeUndefined();
  });

  it("🔁 空载荷 ⇒ 缺席（空载荷保护在更前面，这里不许编出一枚读数）", () => {
    expect(findDuplicateCodes([])).toBeUndefined();
  });

  it("点名有上限＝第 21 枚重复码不许把回执撑大（截到 20，仍算「有重复」）", () => {
    const rows = Array.from({ length: 25 }, (_, i) => [row("crypto", `C${i}`), row("crypto", `C${i}`)]).flat();
    const dups = findDuplicateCodes(rows);
    expect(dups).toHaveLength(20);
    expect(dups![0]).toBe("crypto:C0");
  });

  it("type 前缀参与判据＝同 code 不同 type 不算重复", () => {
    expect(findDuplicateCodes([row("fund", "510300"), row("stock", "510300")])).toBeUndefined();
  });

  it("接线＝构造完 rows 之后立刻数，且成功／失败／缩水三条返回都带着 `dupCodes`", () => {
    const callAt = SYNC_SRC.indexOf("dupCodes = findDuplicateCodes(rows)");
    expect(callAt).toBeGreaterThan(-1);
    expect(callAt).toBeGreaterThan(SYNC_SRC.indexOf("updatedAt: new Date(),"));
    expect(callAt).toBeLessThan(SYNC_SRC.indexOf('if (rows.length === 0)'));
    // 三条返回各带一次（成功／缩水早退／catch）
    const sites = SYNC_SRC.split("\n").filter((l) => l.trim() === "dupCodes,").length;
    const successSite = SYNC_SRC.includes("note, dupCodes, tookMs");
    expect(sites + (successSite ? 1 : 0)).toBe(3);
  });

  it("🔁 尺自己的牙齿＝在内存里摘掉那行数，上面两条字面判据必须同时失效", () => {
    const stripped = SYNC_SRC.split("\n")
      .filter((l) => !l.includes("dupCodes"))
      .join("\n");
    expect(stripped.includes("dupCodes = findDuplicateCodes(rows)")).toBe(false);
    expect(stripped.includes("note, dupCodes, tookMs")).toBe(false);
    expect(stripped.indexOf('if (rows.length === 0)')).toBeGreaterThan(-1);
  });

  it("边界＝`dupCodes` 一次都没进 `note`（屏上那一格不许长开发者向的数）", () => {
    for (const line of SYNC_SRC.split("\n")) {
      if (/^\s*note\s*[:=]/.test(line.trim()) || line.includes("shrinkByDeclaration")) {
        expect(line, `note 组装那行掺进了 dupCodes：${line}`).not.toContain("dupCodes");
      }
    }
  });
});
