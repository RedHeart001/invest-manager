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
  KNOWN_STALE_SNAPSHOTS,
  NO_LIVE_PROBE,
  UNCAPTURED_ENDPOINTS,
  UNVERIFIED_ROWS,
  builderMsFor,
  coverage,
  declaredButUnused,
  keysAbsentInDsSource,
  loadSnapshot,
  missingContractKeys,
  newlyStaleEndpoints,
  obsoleteKnownStale,
  obsoleteUncapturedEndpoints,
  obsoleteUnverifiedRows,
  snapshotDenominator,
  staleEndpoints,
  unregisteredEndpoints,
  unnamedUncapturedEndpoints,
  unnamedUnverifiedRows,
  unverifiedRowFields,
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
  const now = Date.now();
  for (const f of DS_RESPONSE_FILES) {
    const out = execFileSync("git", ["log", "-1", "--format=%ct", "--", f], {
      cwd: REPO_ROOT,
      encoding: "utf8",
    }).trim();
    // 脏＝"代码已改、还没提交"那一态；`builderMsFor` 把它拧成"现在"（见 ds-contract.ts 的注释）
    const dirty = execFileSync("git", ["status", "--porcelain", "--", f], {
      cwd: REPO_ROOT,
      encoding: "utf8",
    }).trim() !== "";
    max = Math.max(max, builderMsFor(out ? Number(out) * 1000 : 0, dirty, now));
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
    expect(callSitesIn(`// 见 dsGet("/api/quote/route.ts")\nconst a = 1;`, "fixture.ts")).toEqual([]);
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
    // 分母里没进快照的那几枚：每一枚都必须已有登记 ⇒ "没采到"要有名字与理由，不许只剩一个总数
    const c = coverage(snap) as { 未进快照文件: string[]; 已登记未采: string[]; 无名未采: string[] };
    expect(c.无名未采).toEqual([]);
    expect(c.未进快照文件).toEqual(c.已登记未采);
  });

  it("分母口径（10-12 主人的字＝10；10-13 CR9-92 落 `/quote/realtime` 曾到 11；10-17 CR9-115 撤掉 `/quote/verified` ⇒ 回到 10）：排除表自证，跑满＝100%", () => {
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

  it("行面整块没采到的那一半必须逐枚登记理由（10-18 补：那声 `continue` 此前静默放行）", () => {
    expect(unnamedUnverifiedRows(snap)).toEqual([]);
    // 登记表自证（同 NO_LIVE_PROBE 那三条）：路径名写错＝那条登记静默失效；没理由＝散文承诺
    const paths = DS_CONTRACT.map((c) => c.path);
    expect(Object.keys(UNVERIFIED_ROWS).filter((p) => !paths.includes(p))).toEqual([]);
    expect(Object.entries(UNVERIFIED_ROWS).filter(([, why]) => why.trim().length < 10)).toEqual([]);
    // 每一条登记此刻确实还没验到（不许把已验过的留在表里冒充牙齿）
    for (const p of Object.keys(UNVERIFIED_ROWS)) {
      const c = DS_CONTRACT.find((x) => x.path === p)!;
      expect(unverifiedRowFields(c, snap.endpoints[p] ?? null)).not.toEqual([]);
    }
    // 真牙齿＝把登记表清空，同一把尺当场点名那一枚
    expect(unnamedUnverifiedRows(snap, {})).toEqual(["/bond/yieldcurve 的行面 curve 没采到、也没登记"]);
    expect(obsoleteUnverifiedRows(snap)).toEqual([]);
  });

  it("反向牙齿（C34 成对）：新漏的行面没登记⇒红；行面补上却还挂着⇒另一头红", () => {
    const k = DS_CONTRACT.find((c) => c.path === "/kline")!;
    expect(unverifiedRowFields(k, snap.endpoints["/kline"])).toEqual([]);
    const stripped: SnapshotFile = {
      ...snap,
      endpoints: { ...snap.endpoints, "/kline": { ...snap.endpoints["/kline"], rows: null } },
    };
    expect(unnamedUnverifiedRows(stripped)).toContain("/kline 的行面 candles 没采到、也没登记");
    const filled: SnapshotFile = {
      ...snap,
      endpoints: {
        ...snap.endpoints,
        "/bond/yieldcurve": {
          capturedAt: "2026-10-18",
          provenance: "fixture",
          topLevel: ["curve", "degraded", "note"],
          rows: { curve: ["date", "values"] },
        },
      },
    };
    const yc = DS_CONTRACT.find((c) => c.path === "/bond/yieldcurve")!;
    expect(unverifiedRowFields(yc, filled.endpoints["/bond/yieldcurve"])).toEqual([]);
    expect(obsoleteUnverifiedRows(filled)).toEqual(["/bond/yieldcurve"]);
    expect(unnamedUnverifiedRows(filled)).toEqual([]);
    expect(obsoleteUnverifiedRows(filled, {})).toEqual([]);
  });

  it("分母里整块没进快照的那些必须逐枚登记理由（10-18 补：那两声 `if (!snap) return []` 此前静默放行）", () => {
    expect(unnamedUncapturedEndpoints(snap)).toEqual([]);
    // 登记表自证（同 `NO_LIVE_PROBE`／`UNVERIFIED_ROWS` 那两条）：路径名写错＝那条登记静默失效；没理由＝散文承诺
    const paths = DS_CONTRACT.map((c) => c.path);
    expect(Object.keys(UNCAPTURED_ENDPOINTS).filter((p) => !paths.includes(p))).toEqual([]);
    expect(Object.entries(UNCAPTURED_ENDPOINTS).filter(([, why]) => why.trim().length < 10)).toEqual([]);
    // 两张表不许重叠：一枚端不能既被移出分母、又算成"在分母里没采到"
    expect(Object.keys(UNCAPTURED_ENDPOINTS).filter((p) => p in NO_LIVE_PROBE)).toEqual([]);
    // 每一条登记此刻确实还没进快照（不许把已采到的留在表里冒充牙齿）
    for (const p of Object.keys(UNCAPTURED_ENDPOINTS)) {
      expect(snap.endpoints[p] ?? null).toBeNull();
    }
    // 真牙齿＝把登记表清空，同一把尺当场点名那一枚
    expect(unnamedUncapturedEndpoints(snap, {})).toEqual(["/products"]);
    expect(obsoleteUncapturedEndpoints(snap)).toEqual([]);
  });

  it("反向牙齿（C34 成对）：新落端点没采又没登记⇒红；登记那枚补采到了⇒另一头红逼摘", () => {
    // (a) 抹掉一枚已采到的 ⇒ 它立刻变成"没登记的未采"＝"闸2 清单加了端点而现场腿没采"那一形
    const stripped: SnapshotFile = {
      ...snap,
      endpoints: Object.fromEntries(Object.entries(snap.endpoints).filter(([p]) => p !== "/news")),
    };
    expect(unnamedUncapturedEndpoints(stripped)).toEqual(["/news"]);
    // (b) 假想 `/products` 被 `--only` 点名采到了 ⇒ 那条登记当场过期，而 L2 从此真检查它
    const pk = DS_CONTRACT.find((c) => c.path === "/products")!;
    const filled: SnapshotFile = {
      ...snap,
      endpoints: {
        ...snap.endpoints,
        "/products": {
          capturedAt: "2026-10-19",
          provenance: "fixture",
          topLevel: ["count", "products", "source", "type"],
          rows: { products: ["type", "code", "name"] },
        },
      },
    };
    expect(missingContractKeys(pk, filled.endpoints["/products"])).toEqual([]);
    expect(unnamedUncapturedEndpoints(filled)).toEqual([]);
    expect(obsoleteUncapturedEndpoints(filled)).toEqual(["/products"]);
    expect(coverage(filled).未进快照文件).toEqual([]);
    expect(obsoleteUncapturedEndpoints(filled, {})).toEqual([]);
  });
});

describe("闸2 L3 陈旧：快照不得比 ds 响应构造面更旧", () => {
  const builder = builderLatestMs();

  it(`现存快照里「清单外」的过期＝0（构造面共 ${DS_RESPONSE_FILES.length} 枚，已知陈旧另有清单）`, () => {
    expect(newlyStaleEndpoints(snap, builder)).toEqual([]);
    // 原始读数仍然要说得出（不许把"已隔离"读成"没问题"）
    expect(staleEndpoints(snap, builder).sort()).toEqual(Object.keys(KNOWN_STALE_SNAPSHOTS).sort());
  });

  it("已知陈旧清单自证：每条都在分母里（重采这条路存在）、都带理由、且**确实还过期**", () => {
    const paths = DS_CONTRACT.map((c) => c.path);
    const denom = snapshotDenominator(paths);
    expect(Object.keys(KNOWN_STALE_SNAPSHOTS).filter((p) => !paths.includes(p))).toEqual([]);
    expect(Object.keys(KNOWN_STALE_SNAPSHOTS).filter((p) => !denom.includes(p))).toEqual([]);
    expect(Object.entries(KNOWN_STALE_SNAPSHOTS).filter(([, why]) => why.trim().length < 20)).toEqual([]);
    // 现场腿重采之后这一条会变红＝"清单比现实长"那一形——这是设计，不是故障：
    // 摘掉它才是正确处置（10-13 A 窗的收尾第 4 步写着这件事）。
    expect(obsoleteKnownStale(snap, builder)).toEqual([]);
  });

  it("合成样本能点亮 L3：构造面在快照之后被改过＝过期，不在清单里的那一枚必须被点名", () => {
    const b = Date.parse("2026-10-06T20:43:00+08:00");
    const entry = (day: string): SnapshotFile["endpoints"][string] => ({
      capturedAt: day,
      provenance: "fixture",
      topLevel: ["price"],
      rows: null,
    });
    const old: SnapshotFile = {
      schemaVersion: 1,
      capturedBy: "fixture",
      endpoints: { "/quote": entry("2026-10-01"), "/news": entry("2026-10-01") },
    };
    expect(staleEndpoints(old, b)).toEqual(["/news", "/quote"]);
    // 隔离只在「清单里」的那一枚——`known` 由夹具自己给，不读生产清单
    // （10-13 收尾第 4 步把 `KNOWN_STALE_SNAPSHOTS` 清空后，读生产配置的那句就跟着翻了）
    expect(newlyStaleEndpoints(old, b, {})).toEqual(["/news", "/quote"]);
    expect(newlyStaleEndpoints(old, b, { "/quote": "fixture-known" })).toEqual(["/news"]);
    expect(obsoleteKnownStale(old, b, { "/quote": "fixture-known", "/kline": "fixture-known" })).toEqual([
      "/kline",
    ]);
    old.endpoints["/news"] = entry("2026-10-07");
    expect(newlyStaleEndpoints(old, b, { "/quote": "fixture-known" })).toEqual([]);
  });

  it("构造面时刻那把尺自己也要两半样本：脏的那一枚要拧成「现在」，干净的不许动", () => {
    const committed = Date.parse("2026-10-06T20:43:00+08:00");
    const now = Date.parse("2026-10-13T09:00:00+08:00");
    expect(builderMsFor(committed, false, now)).toBe(committed);
    expect(builderMsFor(committed, true, now)).toBe(now);
    expect(builderMsFor(0, true, now)).toBe(now); // 还没进版本管理的新文件（10-13 的 `realtime.py`）
    expect(builderMsFor(0, false, now)).toBe(0);
  });
});
