/**
 * 闸2（OPT-4）的三条腿。清单与纯判据在 `ds-contract.ts`，这个文件只做三件事：
 * 读盘上的真源码 → 喂给判据 → 报出红在谁身上；每条腿另配一枚"能点亮它"的合成样本
 * （成对断言纪律：库内扫描证"现在没红的"，合成样本证"闸会红"，两半不互证）。
 */
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import ts from "typescript";

import {
  DS_CONTRACT,
  DS_RESPONSE_FILES,
  NO_LIVE_PROBE,
  coverage,
  declaredButUnused,
  keysAbsentInDsSource,
  loadSnapshot,
  missingContractKeys,
  snapshotDenominator,
  staleEndpoints,
  unregisteredEndpoints,
  REPO_ROOT,
  type SnapshotFile,
} from "./ds-contract";

const WEB_ROOT = path.join(REPO_ROOT, "web");
const SCAN_DIRS = ["lib", "app"];

function sourceFiles(dir: string, out: string[] = []): string[] {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const name of entries) {
    if (name === "node_modules" || name === ".next" || name === "__snapshots__") continue;
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) sourceFiles(p, out);
    else if (/\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name)) out.push(p);
  }
  return out;
}

export function scannedWebFiles(): string[] {
  const files: string[] = [];
  for (const d of SCAN_DIRS) sourceFiles(path.join(WEB_ROOT, d), files);
  return files.sort();
}

/** AST 而不是正则：注释里出现的 `dsGet`、`app/api/quote/...` 都不该被数成调用点。
 *  首跑（10-12）就被真源码教了一次：`dsPost("/hotspots/run?trigger=manual-ui")` 把查询串
 *  一起带进了字面量 ⇒ 端点身份只取 `?`／`#` 之前那一段，不然清单永远对不上。 */
export function callSitesIn(text: string, label: string): string[] {
  const sf = ts.createSourceFile(label, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const endpointOf = (raw: string): string => raw.split(/[?#]/)[0];
  const out: string[] = [];
  const visit = (n: ts.Node): void => {
    if (ts.isCallExpression(n)) {
      const first = n.arguments[0];
      const fn = ts.isIdentifier(n.expression) ? n.expression.text : "";
      if ((fn === "dsGet" || fn === "dsPost") && first && ts.isStringLiteral(first)) {
        out.push(endpointOf(first.text));
      }
      if (first && ts.isTemplateExpression(first)) {
        const m = /\$\{DATA_SERVICE_URL\}(\/[A-Za-z_/]+)/.exec(first.getText(sf));
        if (m) out.push(endpointOf(m[1]));
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

function scannedEndpoints(): string[] {
  return scannedWebFiles().flatMap((abs) => callSitesIn(readFileSync(abs, "utf8"), abs));
}

function dsSourceText(): string {
  const app = path.join(REPO_ROOT, "data-service", "app");
  const parts: string[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir)) {
      const p = path.join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (name.endsWith(".py")) parts.push(readFileSync(p, "utf8"));
    }
  };
  walk(app);
  return parts.join("\n");
}

function allContractKeys(c: (typeof DS_CONTRACT)[number]): string[] {
  return [...c.requiredTop, ...Object.values(c.requiredRows ?? {}).flat()];
}

function builderLatestMs(): number {
  let max = 0;
  for (const f of DS_RESPONSE_FILES) {
    const out = execFileSync("git", ["log", "-1", "--format=%ct", "--", f], {
      cwd: REPO_ROOT,
      encoding: "utf8",
    }).trim();
    if (out) max = Math.max(max, Number(out) * 1000);
  }
  return max;
}

const snap = loadSnapshot();

describe("闸2 L1 完整性：web 里每处 ds 调用点都得登记", () => {
  it("闸自己坏掉时不能静默全绿＝扫到的源码文件必须 > 40、调用点必须 > 8", () => {
    expect(scannedWebFiles().length).toBeGreaterThan(40);
    expect([...new Set(scannedEndpoints())].length).toBeGreaterThan(8);
  });

  it("扫到的端点全部已登记（新增调用没进清单＝红）", () => {
    expect(unregisteredEndpoints(scannedEndpoints(), DS_CONTRACT.map((c) => c.path))).toEqual([]);
  });

  it("清单里没有僵尸端点（登记了但已没人调用＝红）", () => {
    expect(declaredButUnused(scannedEndpoints(), DS_CONTRACT.map((c) => c.path))).toEqual([]);
  });

  it("合成样本能点亮 L1：未登记的调用点会被点名，查询串不冒充新端点", () => {
    expect(unregisteredEndpoints(["/quote", "/brand-new"], ["/quote"])).toEqual(["/brand-new"]);
    expect(declaredButUnused(["/quote"], ["/quote", "/gone"])).toEqual(["/gone"]);
    expect(callSitesIn(`await dsPost("/hotspots/run?trigger=manual-ui", {});`, "fixture.ts")).toEqual([
      "/hotspots/run",
    ]);
    expect(callSitesIn("fetch(`" + "${DATA_SERVICE_URL}/quote/verified?type=1`);", "fixture.ts")).toEqual([
      "/quote/verified",
    ]);
    // 注释里出现的路径不算调用点（10-12 第一版用正则时就把它读成了端点）
    expect(callSitesIn(`// 见 dsGet("/api/quote/verify/route.ts")\nconst a = 1;`, "fixture.ts")).toEqual([]);
  });
});

describe("闸2 L2 键名：清单要的键，快照与 ds 源码都得承认", () => {
  it("每个声明键都在 ds 源码里以同名字面量存在（任一侧改名＝红）", () => {
    const text = dsSourceText();
    const missing = DS_CONTRACT.flatMap((c) =>
      keysAbsentInDsSource(allContractKeys(c), text).map((k) => `${c.path} → ${k}`),
    );
    expect(missing).toEqual([]);
  });

  it("有快照的那些：声明键 ⊆ 快照键面", () => {
    const drift = DS_CONTRACT.flatMap((c) =>
      missingContractKeys(c, snap.endpoints[c.path] ?? null).map(
        (k) => `${c.path} 快照里没有 ${k}`,
      ),
    );
    expect(drift).toEqual([]);
  });

  it("覆盖面读数（不许把「没采到」读成「没问题」）", () => {
    expect(coverage(snap)).toMatchObject({ declared: DS_CONTRACT.length, 分母: 10 });
  });

  it("分母口径（10-12 主人的字＝改成 10）：排除表自证，且跑满＝100%", () => {
    const paths = DS_CONTRACT.map((c) => c.path);
    // 排除表里写错一个路径名＝那条排除静默失效、分母悄悄变化 ⇒ 必须逐条点名
    const ghost = Object.keys(NO_LIVE_PROBE).filter((p) => !paths.includes(p));
    expect(ghost).toEqual([]);
    // 排除没有理由＝散文承诺，拦不住"跑满了也补不到 100%"那一形
    expect(Object.entries(NO_LIVE_PROBE).filter(([, why]) => why.trim().length < 10)).toEqual([]);
    expect(snapshotDenominator(paths).length).toBe(paths.length - Object.keys(NO_LIVE_PROBE).length);
    // `/hotspots/status` 有 requiredTop ⇒ 它必须在分母里（10-12 那版把它当透传排除，永远补不上）
    const status = DS_CONTRACT.find((c) => c.path === "/hotspots/status")!;
    expect(status.requiredTop.length).toBeGreaterThan(0);
    expect(snapshotDenominator(paths)).toContain("/hotspots/status");
    // 合成红样：一份只含排除项的快照，`未进快照文件` 不得把分母外的端点算成"缺"
    const odd: SnapshotFile = {
      schemaVersion: 1,
      capturedBy: "fixture",
      endpoints: { "/hotspots/run": { capturedAt: "2026-10-12", provenance: "f", topLevel: ["a"], rows: null } },
    };
    expect(coverage(odd).未进快照文件).toEqual(snapshotDenominator(paths));
    expect(coverage(odd).topLevelCaptured).toBe(0);
  });

  it("合成样本能点亮 L2：改一个键名／快照少一个键都要红", () => {
    const text = 'data = {"price": 1, "source": "tencent"}';
    expect(keysAbsentInDsSource(["price", "prevClose"], text)).toEqual(["prevClose"]);
    expect(keysAbsentInDsSource(["price"], text)).toEqual([]);
    const c = DS_CONTRACT.find((x) => x.path === "/quote")!;
    const short = { ...snap.endpoints["/quote"], topLevel: ["type", "code", "source", "timestamp"] };
    expect(missingContractKeys(c, short)).toEqual(["price"]);
    expect(missingContractKeys(c, snap.endpoints["/quote"])).toEqual([]);
    const rowsOnly = { ...c, requiredRows: { candles: ["date", "close"] } };
    expect(
      missingContractKeys(rowsOnly, {
        capturedAt: "2026-10-01",
        provenance: "fixture",
        topLevel: null,
        rows: { candles: ["date"] },
      }),
    ).toEqual(["close"]);
  });
});

describe("闸2 L3 陈旧：快照不得比 ds 响应构造面更旧", () => {
  it(`现存快照（${Object.keys(snap.endpoints).length} 枚）不早于 ${DS_RESPONSE_FILES.length} 枚构造面的最后提交`, () => {
    expect(staleEndpoints(snap, builderLatestMs())).toEqual([]);
  });

  it("合成样本能点亮 L3：构造面在快照之后被改过＝过期", () => {
    const builder = Date.parse("2026-10-06T20:43:00+08:00");
    const old: SnapshotFile = {
      schemaVersion: 1,
      capturedBy: "fixture",
      endpoints: {
        "/quote": { capturedAt: "2026-10-01", provenance: "fixture", topLevel: ["price"], rows: null },
      },
    };
    expect(staleEndpoints(old, builder)).toEqual(["/quote"]);
    old.endpoints["/quote"].capturedAt = "2026-10-07";
    expect(staleEndpoints(old, builder)).toEqual([]);
  });
});
