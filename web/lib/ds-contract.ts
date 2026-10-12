/**
 * 闸2（OPT-4，主人 10-12 的字＝「做闸1、闸2」）：跨服务契约的**单一来源清单＋纯判据**。
 *
 * 治的那一形＝10-08 那次「采集器读错键 ⇒ ④ 只剩 note 文本」：两侧各测自己，
 * web 读哪些键、ds 回哪些键，从来没有人把两份放进同一个房间。现有门禁 ①② 都测不到它。
 *
 * 三条腿（`ds-contract.test.ts` 跑库内扫描，每条另带一枚会点亮的合成样本）：
 *  - L1 完整性：web 源码里每一处 ds 调用点都得在这里登记（新端点没登记 ⇒ 红）。
 *  - L2 键名：这里声明要读的键 ⊆ 快照键面（只查有快照的那些），并且每个键都得在 ds
 *    源码里以同名字面量存在（任何一侧改名 ⇒ 红）。
 *  - L3 陈旧：快照采集时刻不得早于 ds 响应构造面（`DS_RESPONSE_FILES`）的最后一次提交。
 *
 * 拦不住的那一半（明说，不是留白）：
 *  - 键名对但**语义/单位**变（`timestamp` 从 ISO 退成 epoch）它抓不到 ⇒ 那一半归 R13 型抽样；
 *  - ds 多出键不算红（加键不破坏调用方，这是 CR9-31 那轮的既有取舍）；
 *  - L2 的存在性检查只证"这个键名还在 ds 源码里"，不证"它就住在这个端点上"
 *    ⇒ 常见键名（code/name/type）在这里判别力低，真正咬得住的是专用键名
 *    （`verifyVerdict`／`crossChecked`／`usesEastmoney` 这一类）。
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export type RowSpec = Record<string, string[]>;

export type EndpointContract = {
  path: string;
  method: "GET" | "POST";
  /** web 读它、缺了就会出错或静默失真的那些键（不是"全部可用键"） */
  requiredTop: string[];
  /** 数组字段每一行必须有的键（键名住在哪一层，这里分层声明） */
  requiredRows?: RowSpec;
  readBy: string[];
  note?: string;
};

/** 快照里一枚端点的采集结果（`topLevel`／`rows` 任一为 null ＝那一半还没采到） */
export type SnapshotEntry = {
  capturedAt: string; // YYYY-MM-DD（北京时间）
  provenance: string;
  topLevel: string[] | null;
  rows: RowSpec | null;
};

export type SnapshotFile = {
  schemaVersion: number;
  capturedBy: string;
  endpoints: Record<string, SnapshotEntry>;
};

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(HERE, "..", "..");

export const DS_CONTRACT: readonly EndpointContract[] = [
  {
    path: "/quote",
    method: "GET",
    requiredTop: ["type", "code", "price", "source", "timestamp"],
    readBy: ["web/app/product/[type]/[code]/page.tsx", "web/lib/tools.ts", "web/app/api/quote/route.ts"],
  },
  {
    path: "/quotes",
    method: "GET",
    requiredTop: ["quotes", "note", "usesEastmoney"],
    readBy: ["web/lib/data-service.ts"],
    note: "`usesEastmoney` 三态（true/false/null）是 CR9-67 丙的契约，缺键＝null 而不是 false",
  },
  {
    path: "/quote/verified",
    method: "GET",
    requiredTop: ["type", "code", "price", "source", "verifyVerdict", "crossChecked"],
    readBy: ["web/app/api/quote/verify/route.ts", "web/app/components/VerifyQuoteButton.tsx"],
    note: "10-08 那一枚读错键的就是这一条：`verifyVerdict` 三态才是分歧率的分子分母",
  },
  {
    path: "/kline",
    method: "GET",
    requiredTop: ["type", "code", "interval", "source", "candles"],
    requiredRows: { candles: ["date", "open", "high", "low", "close", "volume"] },
    readBy: ["web/lib/kline.ts"],
  },
  {
    path: "/products",
    method: "GET",
    requiredTop: ["count", "products", "source"],
    requiredRows: { products: ["type", "code", "name"] },
    readBy: ["web/lib/sync.ts"],
    note: "降级时另带 degraded/note/intentionalSubset；那三个是「可选但有语义」，不列进 required",
  },
  {
    path: "/news",
    method: "GET",
    requiredTop: ["code", "degraded", "note", "items"],
    requiredRows: { items: ["date", "title"] },
    readBy: ["web/lib/events.ts", "web/app/api/events/route.ts"],
  },
  {
    path: "/fund/holdings",
    method: "GET",
    requiredTop: ["degraded", "note", "quarter", "holdings"],
    requiredRows: { holdings: ["code", "name", "weight"] },
    readBy: ["web/app/product/[type]/[code]/page.tsx", "web/lib/tools.ts"],
  },
  {
    path: "/fund/report",
    method: "GET",
    requiredTop: ["degraded", "note", "reports", "industry"],
    requiredRows: { reports: ["title", "date", "id"] },
    readBy: ["web/lib/tools.ts"],
    note: "E-3 刀 A 依据：`reports` 只有定期报告清单（`PERIODIC_KEYWORDS` 四串），兑现不了「分红节点」",
  },
  {
    path: "/bond/yieldcurve",
    method: "GET",
    requiredTop: ["degraded", "note", "source", "curve"],
    requiredRows: { curve: ["date", "values"] },
    readBy: ["web/app/product/[type]/[code]/page.tsx"],
  },
  {
    path: "/hotspots/status",
    method: "GET",
    requiredTop: ["running", "lastResult"],
    readBy: ["web/app/api/hotspots/status/route.ts", "web/app/HotspotFeed.tsx"],
    note: "BFF 侧是 Record<string, unknown> 透传，真正读键的是浏览器那一侧",
  },
  {
    path: "/hotspots/run",
    method: "POST",
    requiredTop: [],
    readBy: ["web/app/api/hotspots/run/route.ts"],
    note: "整份透传，键面归 HotspotFeed ⇒ L2 对它是空集（登记的意义在 L1：这一处调用别再没人管）",
  },
  {
    path: "/research/start",
    method: "POST",
    requiredTop: ["taskId"],
    readBy: ["web/lib/research.ts"],
    note: "被拒走 409，`rejected`/`todayDone` 住在错误体里（CR6-P1-1 的 body 分流），不在这份 required 内",
  },
];

/** ds 侧「谁把响应拼出来」的那几枚文件——L3 拿它们的最后提交时间和快照比 */
export const DS_RESPONSE_FILES = [
  "data-service/app/main.py",
  "data-service/app/providers/chain.py",
  "data-service/app/providers/akshare_provider.py",
  "data-service/app/providers/tencent_provider.py",
];

export const SNAPSHOT_PATH = path.join(HERE, "ds-contract.snapshot.json");

export function loadSnapshot(file: string = SNAPSHOT_PATH): SnapshotFile {
  return JSON.parse(readFileSync(file, "utf8")) as SnapshotFile;
}

/** L1：一处 ds 调用点的端点路径（纯文本判据，交给调用方喂 AST／正则都行） */
export function unregisteredEndpoints(scanned: string[], declared: string[]): string[] {
  return [...new Set(scanned)].filter((p) => !declared.includes(p)).sort();
}

export function declaredButUnused(scanned: string[], declared: string[]): string[] {
  return [...new Set(declared)].filter((p) => !scanned.includes(p)).sort();
}

/** L2：声明要读、快照里却没有的键 */
export function missingContractKeys(c: EndpointContract, snap: SnapshotEntry | null): string[] {
  if (!snap) return [];
  const out: string[] = [];
  if (snap.topLevel) out.push(...c.requiredTop.filter((k) => !snap.topLevel!.includes(k)));
  for (const [field, keys] of Object.entries(c.requiredRows ?? {})) {
    const surface = snap.rows?.[field];
    if (!surface) continue;
    out.push(...keys.filter((k) => !surface.includes(k)));
  }
  return out;
}

/** L2 的另一半：键名在 ds 源码里还以同名字面量存在吗（只证存在，不证住在哪个端点） */
export function keysAbsentInDsSource(keys: string[], dsSourceText: string): string[] {
  return keys.filter((k) => !dsSourceText.includes(`"${k}"`));
}

/** L3：快照比 ds 响应构造面更旧 ⇒ 这一枚过期了 */
export function staleEndpoints(snap: SnapshotFile, builderLatestMs: number): string[] {
  return Object.entries(snap.endpoints)
    .filter(([, e]) => Date.parse(`${e.capturedAt}T23:59:59+08:00`) < builderLatestMs)
    .map(([p]) => p)
    .sort();
}

/** 覆盖面读数：这闸今天到底覆盖了几枚端点的哪几半（不许把"没数据"读成"没问题"） */
export function coverage(snap: SnapshotFile): Record<string, unknown> {
  const declared = DS_CONTRACT.map((c) => c.path);
  const withTop = declared.filter((p) => snap.endpoints[p]?.topLevel);
  const withRows = declared.filter((p) => Object.keys(snap.endpoints[p]?.rows ?? {}).length > 0);
  const uncaptured = declared.filter((p) => !snap.endpoints[p]);
  return {
    declared: declared.length,
    topLevelCaptured: withTop.length,
    rowsCaptured: withRows.length,
    未进快照文件: uncaptured,
  };
}
