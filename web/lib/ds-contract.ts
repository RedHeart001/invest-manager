/**
 * 闸2（OPT-4，主人 10-12 的字＝「做闸1、闸2」）：跨服务契约的**单一来源清单＋纯判据**。
 *
 * 治的那一形＝10-08 那次「采集器读错键 ⇒ ④ 只剩 note 文本」：两侧各测自己，
 * web 读哪些键、ds 回哪些键，从来没有人把两份放进同一个房间。现有门禁 ①② 都测不到它。
 *
 * 三条腿（`ds-contract.test.ts` 跑库内扫描，每条另带一枚会点亮的合成样本）：
 *  - L1 完整性：web 源码里每一处 ds 调用点都得在这里登记（新端点没登记 ⇒ 红）。
 *  - L2 键名：这里声明要读的键 ⊆ 快照键面（只查有快照的那些），并且每个键都得在 ds
 *    源码里以同名字面量存在（任何一侧改名 ⇒ 红）。快照那一半的分母＝登记项减 `NO_LIVE_PROBE`。
 *    行面整块没采到的另有一半（10-18 补）＝`unverifiedRowFields` 点名＋`UNVERIFIED_ROWS` 逐枚登记
 *    理由；此前 `missingContractKeys` 遇到 `rows:null` 直接 `continue`＝声明过的行键没检查也不响。
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
    path: "/quote/realtime",
    method: "GET",
    requiredTop: [
      "type",
      "code",
      "observedAt",
      "parts",
      "price",
      "intraday",
      "crossChecked",
      "verifyVerdict",
      "consensus",
      "hasTodayData",
      "intradayDateIsToday",
      "wired",
      "sources",
      "degraded",
      "note",
    ],
    requiredRows: { sources: ["kind", "source", "ok", "latencyMs", "detail"] },
    readBy: ["web/app/api/realtime/route.ts", "web/lib/realtime.ts"],
    note: "CR9-92 1a：`hasTodayData`／`intradayDateIsToday` 是**三态**（`null`＝这一轮只问了现价），"
      + "web 侧把它读成 `false` 就是「当日没数据」的假结论；`sources` 是「这一轮点名了谁」的面，不是快照",
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
    readBy: ["web/lib/tools.ts", "web/app/product/[type]/[code]/page.tsx"],
    note: "E-3 刀 A 依据：`reports` 只有定期报告清单（`PERIODIC_KEYWORDS` 四串），兑现不了「分红节点」。"
      + "CR9-98（#65 刀 B）起详情页也读它——读的是 `industry` 那一块（`lib/fund-industry.ts` 判三态），"
      + "`reports` 仍只在 MCP 工具侧用",
  },
  {
    path: "/bond/yieldcurve",
    method: "GET",
    requiredTop: ["degraded", "note", "curve"],
    requiredRows: { curve: ["date", "values"] },
    readBy: ["web/app/product/[type]/[code]/page.tsx"],
    note: "`source` **不在 requiredTop**：它只在成功分支有（`akshare_provider.py:888`），降级分支只回 `{degraded,note,curve}`（`main.py:323`）——声明成必需要求降级响应也带它。消费侧本来就按可选处理（`web/app/product/[type]/[code]/page.tsx:55` 的 `source?: string`、同文件那枚 `yieldData?.source` 三元＝空则整段「· 来源：」不渲染）。10-13 现场腿采到的正是降级态（note＝`yield curve no valid rows`）。",
  },
  {
    path: "/bond/underlying",
    method: "GET",
    requiredTop: ["code", "degraded", "note", "stockCode", "stockName"],
    readBy: ["web/lib/events.ts"],
    note: "#75 的 web 那一半（CR9-111）：转债详情页的事件区先问这一枚拿正股，再拿正股代码去 `/news`。"
      + "两态都带这五枚键（降级＝`main.py:342` 显式写 null，成功＝`main.py:349` 整份展开），"
      + "所以 `stockCode`/`stockName` 可以一起进 required——不像 `/bond/yieldcurve` 的 `source` 只在成功分支有。",
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

/** 快照分母的排除表（10-12 主人「分母口径改成 10」的字）——**这一份是唯一来源**，
 *  现场腿 `test-script/window_contract.py` 用正则现查它，不抄第二份。
 *  治的那一形＝"跑满了也补不到 100%"：10-12 那版现场腿的探针是 9 条、`PASSTHROUGH` 排掉 3 条，
 *  而账上分母写的 11＝12 登记 −`/hotspots/run`（L2 空集），于是 `/hotspots/status`（有 2 枚 requiredTop）
 *  与 `/research/start`（1 枚）永远采不到 ⇒ 排除必须有**写下来的理由**，不能靠"它是透传"这句话。 */
export const NO_LIVE_PROBE: Record<string, string> = {
  "/hotspots/run": "L2 是空集（`requiredTop: []`，整份透传）⇒ 键面快照对它没有判据",
  "/research/start": "POST 有副作用（真起一次研报任务）⇒ 永不自动采，要它的人自己点名",
  "/bond/underlying":
    "键面由 ds 侧离线套件 test_cr9_108_bond_map.py（18/18，akshare 全程替身）钉住成功与降级两臂，而现场腿每采一次都要为整张映射表花一枚东财令牌（件内约 4 个 HTTP）、这张表 24 小时才值得变一次 ⇒ 排除；要点名采它就给 window_contract 的 PROBES 加一枚探针",
};

/** ds 侧「谁把响应拼出来」的那几枚文件——L3 拿它们的最后提交时间和快照比 */
export const DS_RESPONSE_FILES = [
  "data-service/app/main.py",
  "data-service/app/providers/chain.py",
  "data-service/app/providers/akshare_provider.py",
  "data-service/app/providers/tencent_provider.py",
  "data-service/app/realtime.py",
];

/**
 * L3 的**已知陈旧**清单（10-13 落 CR9-92 这一轮登记）。
 *
 * 为什么要这张表，而不是把 L3 关掉或改松：这一条腿的构造面是「四枚文件里最新的那次提交」，
 * 所以**任何一次 ds 落码**都会把所有已存快照判成过期——而重采要真打上游、只能在人工窗口做
 * （10-13 A 窗最后一步）。如果不隔离，落 CR9-92 的那一笔就会让闸1 常红，
 * 而常红的闸等于没有闸（CR9-14 那一轮的教训原话：不先隔离，后续任何一批都失去门禁判别力）。
 *
 * 两条牙齿都留着，这张表不是"压红"用的：
 *  - 清单外的过期＝**新增**，当场红；
 *  - 清单里的已经不再过期（重采之后）＝也红，逼着把这一条摘掉，否则它就变成第二个 `PASSTHROUGH`。
 */
/** 构造面的"最新时刻"：最后一次**提交**时间；工作区里已改但未提交的那一枚按"现在"算。
 *
 * 为什么要带上脏的那一半：L3 原来只看 `git log`，于是"代码已改、快照还没跟上"这一态它是瞎的——
 * 10-13 落 CR9-92 时 `main.py` 在提交前就已经改了，而 `git log -1` 只看得见上一次提交（10-06），
 * 结果"已登记为已知陈旧"的清单在提交那一刻反而对不上尺（与 CR9-24「代码已改、未证进程」同一形）。
 * 脏文件只会把尺**拧紧**（判成更新＝更容易判过期），不会反过来放过真过期。 */
export function builderMsFor(committedMs: number, isDirty: boolean, nowMs: number): number {
  return Math.max(committedMs, isDirty ? nowMs : 0);
}

/** 已知陈旧清单自证用：这些条目的来路（谁把构造面改新的、什么时候重采）。
 *  登记表为空＝L3 两条牙齿都在跑：清单外的过期当场红，清单里的不再过期也红（逼着摘）。
 *  每条的 `why` 有 ≥20 字符的下限（`ds-contract.test.ts:231`），且要写清"谁把构造面改新的＋哪一轮重采"。 */
export const KNOWN_STALE_SNAPSHOTS: Record<string, string> = {
  // 10-13 13:47 `window_contract.py --live --write` 重采后销账（原两条＝`/quote`／`/kline`，
  // 由 CR9-92 落码判过期）。
  // 10-16 19:0x 重采后销账（原十条＝`/quote`…`/hotspots/status` 整块，由 CR9-108 把 `main.py`＋
  // `providers/akshare_provider.py` 改新而判过期；键面一处没变，新路由不进 `DS_CONTRACT`＝分母仍 11）。
  // 这一格只在"有人把构造面改新、快照还没重采"时才有内容。
  // 10-18 12:0x 续＝本轮又改了 `app/realtime.py` 里那枚漂到空行的 `acquire` 锚点注释（号换成符号）；清单仍这 9 枚、不必新增。
  // 10-18 登记＝同一形，且**只有注释变了**：`main.py` 的备份调度那一行与 `/quote/verified` 的
  // docstring、`providers/chain.py` 的 `verify_metric` 注意段——那三句说的是 CR9-115 之前的世界
  // （「无补跑」「按需调用」），PLAN `:179` 预留的「两处注释随第二批更正」没随第二批走完。
  // 键面一处没变，但 `builderMsFor` 把脏文件拧成 `Date.now()` ⇒ 现存 9 枚整块判过期。
  // 摘法＝10-19 人工窗口 `test-script/window_contract.py --live --write` 重采后**这 9 条一起删**
  // （重采之后 `obsoleteKnownStale` 会当场红逼摘＝设计，不是故障）。逐条写的"谁把构造面改新"：
  // 10-19 00:2x 重采后销账＝原 9 枚（`/bond/yieldcurve`／`/fund/holdings`／`/fund/report`／`/hotspots/status`／
  // `/kline`／`/news`／`/quote`／`/quote/realtime`／`/quotes`）整块删除，`capturedAt` 全部落到 2026-10-19、
  // 键面一处没变（`非200=[]`、消失键 `{}`）。这一格从此为空＝两条牙齿都在跑：清单外的过期当场红，
  // 清单里的不再过期也红。`/bond/yieldcurve` 的 `rows` 重采后仍是 null（`curve` 是 `[date, values]` 那种
  // 数组套数组，`key_surface()` 只认数组里的 dict）⇒ 它挂在 `UNVERIFIED_ROWS` 那一格，不在这里。
};

/** L3 的"新增"那一半：不在已知清单里的过期才该红 */
export function newlyStaleEndpoints(
  snap: SnapshotFile,
  builderLatestMs: number,
  known: Record<string, string> = KNOWN_STALE_SNAPSHOTS,
): string[] {
  return staleEndpoints(snap, builderLatestMs).filter((p) => !(p in known));
}

/** 清单自己也得有人清：重采之后就没人过期了，那一条必须摘，不然这张表只会长 */
export function obsoleteKnownStale(
  snap: SnapshotFile,
  builderLatestMs: number,
  known: Record<string, string> = KNOWN_STALE_SNAPSHOTS,
): string[] {
  const stillStale = new Set(staleEndpoints(snap, builderLatestMs));
  return Object.keys(known).filter((p) => !stillStale.has(p)).sort();
}

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

/**
 * L2 的另外一半：`missingContractKeys` 只能比"快照里有的那一半"，行面整块没采到时它 `continue`
 * ⇒ 声明的 `requiredRows` 一条都没检查、闸却全绿（10-18 实测：`/bond/yieldcurve` 的快照
 * `rows:null`，那次现场腿采到的是降级态）。这里把它点出来，交给 `UNVERIFIED_ROWS` 逐枚登记理由。
 */
export function unverifiedRowFields(c: EndpointContract, snap: SnapshotEntry | null): string[] {
  if (!snap) return [];
  return Object.keys(c.requiredRows ?? {}).filter((f) => !snap.rows?.[f]);
}

/**
 * 未验证行面的登记表（键＝端点路径，值＝为什么还没验到）——与 `KNOWN_STALE_SNAPSHOTS` 同形：
 * 空白不是"没问题"，但也不许长成第二个 PASSTHROUGH，所以重采补上行面后必须从这里摘掉
 * （`obsoleteUnverifiedRows` 会当场红逼摘）。
 */
export const UNVERIFIED_ROWS: Record<string, string> = {
  "/bond/yieldcurve":
    "快照 `rows:null`＝10-16 现场腿采到的是降级态（`note=yield curve no valid rows`）⇒ `requiredRows.curve` 的 `[date,values]` 从未被行面验证；重采拿到成功态后随整块摘掉（要「跑」字）",
};

/** 没登记的未验证行面＝静默盲区 ⇒ 必须点名 */
export function unnamedUnverifiedRows(
  snap: SnapshotFile,
  known: Record<string, string> = UNVERIFIED_ROWS,
): string[] {
  return DS_CONTRACT.flatMap((c) =>
    unverifiedRowFields(c, snap.endpoints[c.path] ?? null)
      .filter((f) => !(c.path in known))
      .map((f) => `${c.path} 的行面 ${f} 没采到、也没登记`),
  );
}

/** 清单自己也得有人清：行面补上了这条还挂着＝红（否则这张表只会长） */
export function obsoleteUnverifiedRows(
  snap: SnapshotFile,
  known: Record<string, string> = UNVERIFIED_ROWS,
): string[] {
  return Object.keys(known)
    .filter((p) => {
      const c = DS_CONTRACT.find((x) => x.path === p);
      return c !== undefined && unverifiedRowFields(c, snap.endpoints[p] ?? null).length === 0;
    })
    .sort();
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

/** 覆盖面读数：这闸今天到底覆盖了几枚端点的哪几半（不许把"没数据"读成"没问题"）
 *  分母＝登记项减 `NO_LIVE_PROBE` ⇒ 「跑满现场腿＝分母 100%」这条是码算出来的，不是散文承诺的。 */
export function snapshotDenominator(declared: readonly string[] = DS_CONTRACT.map((c) => c.path)): string[] {
  return declared.filter((p) => !(p in NO_LIVE_PROBE));
}

/**
 * 分母里**整块没进快照文件**的那几枚（逐枚登记理由）。这一形此前是静默的：`missingContractKeys`
 * 与 `unverifiedRowFields` 都以 `if (!snap) return []` 开头 ⇒ 端点没采到＝一条键都不检查、闸全绿。
 * 10-18 现查＝分母 10、快照 9，缺的那一枚是 `/products`。
 * ⚠️ 它与 `NO_LIVE_PROBE` 不是一回事：那三枚被移出了分母（各有理由），`/products` **在分母里**、
 * 现场腿也带着它的探针（`window_contract.py` 的 `PROBES`），只是被同文件的 `EXPENSIVE` 挡在默认
 * 计划外 ⇒ 不 `--only /products` 点名就永远采不到，而 `探针集合 == 分母` 那枚自测照样绿。
 * 与 `UNVERIFIED_ROWS` 同形：登记要带理由、补上了必须摘（`obsoleteUncapturedEndpoints` 当场红逼摘）。
 * 10-19 现值＝**表为空**（`/products` 已采到 ⇒ 覆盖面 10/10，见下面那格销账沿革）；空表是原设计，
 * 不是"这张表没用了"——闸的判别力改由 `ds-contract.test.ts` 那两枚合成样本提供（摘掉一枚已采到的
 * ⇒ 空登记表也必须点名它）。
 */
export const UNCAPTURED_ENDPOINTS: Record<string, string> = {
  // 销账沿革（CR9-124，10-19 11:52:48）＝`/products` 由现场腿点名真采到：`status 200`·`error null`·
  // `vanished []`·`topLevel [count,degraded,note,products,source,type]`·
  // `rows.products [code,exchange,name,pinyin,pinyinInitials,tags,type]` ⇒ 那条登记当场过期（留着＝
  // `obsoleteUncapturedEndpoints` 红）。00:29 那次没采到的成因已随 CR9-124 抬掉＝客户端预算 30s→180s
  // （`test-script/window_lib.py` 的 `http_json(..., timeout=30.0)` 现可由单条探针自定；ds 侧那条
  // A 股全量名单是 `ak.stock_zh_a_spot` 的 120s 看门狗那支）。这一趟的代价＝逻辑 2 发：
  // durable `eastmoney 136→137`（主源试完被拒）＋`akshare-obs 12→13`（`ak.stock_zh_a_spot` 那支备源）。
};

/** 没登记的"整块没进快照"＝盲区 ⇒ 必须点名（闸2 清单新落一枚端点而现场腿没采，就红在这里） */
export function unnamedUncapturedEndpoints(
  snap: SnapshotFile,
  known: Record<string, string> = UNCAPTURED_ENDPOINTS,
): string[] {
  return snapshotDenominator().filter((p) => !snap.endpoints[p] && !(p in known)).sort();
}

/** 表自己也得有人清：那枚端点真进了快照，这条登记立刻过期＝逼摘（否则这张表只会长） */
export function obsoleteUncapturedEndpoints(
  snap: SnapshotFile,
  known: Record<string, string> = UNCAPTURED_ENDPOINTS,
): string[] {
  return Object.keys(known).filter((p) => snap.endpoints[p] !== undefined).sort();
}

export function coverage(snap: SnapshotFile): Record<string, unknown> {
  const declared = DS_CONTRACT.map((c) => c.path);
  const denom = snapshotDenominator(declared);
  const withTop = denom.filter((p) => snap.endpoints[p]?.topLevel);
  const withRows = denom.filter((p) => Object.keys(snap.endpoints[p]?.rows ?? {}).length > 0);
  const uncaptured = denom.filter((p) => !snap.endpoints[p]);
  return {
    declared: declared.length,
    分母: denom.length,
    排除: NO_LIVE_PROBE,
    topLevelCaptured: withTop.length,
    rowsCaptured: withRows.length,
    未进快照文件: uncaptured,
    已登记未采: Object.keys(UNCAPTURED_ENDPOINTS).sort(),
    无名未采: unnamedUncapturedEndpoints(snap),
  };
}
