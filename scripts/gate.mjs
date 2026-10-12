#!/usr/bin/env node
/**
 * 闸1（OPT-4，主人 10-12 的字＝「做闸1、闸2」）：收尾那四道零出网门禁的一条命令。
 *
 * 为什么要它：账上的覆盖面读数是「会自己红的闸＝0 枚」（追加五十六 ⑨）——五道门禁
 * 全靠人手依次敲，而"我到底跑没跑全"这件事本身没有回执。本件把 ①②＋docs 闸串成一条，
 * 并把它自己那几枚判据也做成会红的：
 *   · 逐套 exit 独立判定，**汇总解析不出来＝红**（不许"跑完就算过"）；
 *   · **清单为空＝红**（②那套批跑器曾住在 gitignore 目录里、清单靠反推，恒 `return 0`）；
 *   · `LIVE_SUITES` 名单里的文件在 `tests/` 里找不到＝红（改名/摘除得过这一关）；
 *     反方向留一道明账：新加**要花钱**的套件若没进 `LIVE_SUITES`，会被当离线跑——
 *     兜住它的是它自己会连不上/超时而变红，不是这道闸的分类判据。这一形拦不住"静默通过"，写清楚。
 *   · 抬头写**它对着哪一棵树**（sha＋分支＋dirty 数），治"363/44 与 374/45 之间那笔提交树
 *     没单独跑"那一形。
 *
 * 不做的事（别把它读成"门禁自动化了"）：
 *   · ③（p0/p1）与 ④（verify-all 七套）不在这里——它们要买上游额度，10-09 已定档＝人工到场；
 *   · 不挂 CI、不挂 git hook：`.git/hooks` 不在版本管理里、`--no-verify` 一道口就绕过，
 *     而绕开本就违纪律（理由抄在 FIX-LEDGER 的 OPT-4 行）。
 *   ⇒ 它省下的是"手敲四条＋手抄读数"，仍然要我（或你）按下回车。
 *
 * 用法：
 *   node scripts/gate.mjs              # 等价 --offline
 *   node scripts/gate.mjs --offline --skip vitest
 *   node scripts/gate.mjs --selftest   # 只验判据本身（零子进程、零出网）
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(import.meta.dirname, "..");
const VENV_PY = path.join(ROOT, "data-service", ".venv", "Scripts", "python.exe");
const PY = process.env.PY || (fs.existsSync(VENV_PY) ? VENV_PY : "python");
/** 用 node 直接指到本地入口，不经过 `npx`：Windows 下 spawn `.cmd` 需要 shell（EINVAL 那一形）。 */
const WEB = path.join(ROOT, "web");
const TSC_JS = path.join(WEB, "node_modules", "typescript", "bin", "tsc");
const VITEST_JS = path.join(WEB, "node_modules", "vitest", "vitest.mjs");
/** 要买额度的那两套（③）：不在离线闸里跑，也不许被静默算进 ② 的合计 */
export const LIVE_SUITES = new Set(["test_p0.py", "test_p1.py"]);

const VITEST_RE = [
  /Tests[^\n]*?(\d+) failed[^\n]*?(\d+) passed[^\n]*?\((\d+)\)/,
  /Tests\s+(\d+) passed\s+\((\d+)\)/,
];
const VITEST_FILES = /Test Files\s+(\d+) failed[^\n]*?(\d+) passed[^\n]*?\((\d+)\)|Test Files\s+(\d+) passed\s+\((\d+)\)/;
const SUITE_SUMMARY = [/=====\s*(\d+)\/(\d+)\s*通过\s*=====/, /==\s*[^=：\n]*：\s*(\d+)\/(\d+)\s*通过\s*==/];
const DOCS_NEW = /基线对账：NEW=(\d+)／KNOWN=(\d+)\/(\d+)/;
const DOCS_LINKS = /断链扫描[^\n]*?真引用([^\n]*)/;
const DOCS_TABLES = /表格扫描：表=(\d+) 数据行=(\d+) 错位=(\d+)/;

export function treeStamp({ sha, branch, dirty }) {
  return { sha: sha ?? null, branch: branch ?? null, dirtyPaths: Array.isArray(dirty) ? dirty.length : null };
}

export function offlineSuites(allFiles) {
  const known = new Set(allFiles);
  const missing = [...LIVE_SUITES].filter((f) => !known.has(f));
  return { offline: allFiles.filter((f) => !LIVE_SUITES.has(f)).sort(), liveListedButAbsent: missing };
}

/** ② 的汇总字面有两套；解析不出来必须交回 null 让调用方判红，不许当成 0/0 通过 */
export function parseSuiteSummary(text) {
  for (const re of SUITE_SUMMARY) {
    const m = re.exec(text);
    if (m) return { passed: Number(m[1]), total: Number(m[2]), shape: re.source.slice(0, 12) };
  }
  return null;
}

function fileCount(text) {
  const m = VITEST_FILES.exec(text);
  if (!m) return null;
  return m[1] !== undefined
    ? { failed: Number(m[1]), passed: Number(m[2]), total: Number(m[3]) }
    : { failed: 0, passed: Number(m[4]), total: Number(m[5]) };
}

export function parseVitestSummary(text) {
  const m1 = VITEST_RE[0].exec(text);
  const m2 = m1 ? null : VITEST_RE[1].exec(text);
  if (!m1 && !m2) return null;
  const files = fileCount(text);
  return m1
    ? { failed: Number(m1[1]), passed: Number(m1[2]), total: Number(m1[3]), files }
    : { failed: 0, passed: Number(m2[1]), total: Number(m2[2]), files };
}

export function parseDocsReadings(text) {
  const out = { newAlarms: null, known: null, baselineTotal: null, tables: null, linkLine: null };
  const n = DOCS_NEW.exec(text);
  if (n) out.newAlarms = Number(n[1]), (out.known = Number(n[2])), (out.baselineTotal = Number(n[3]));
  const t = DOCS_TABLES.exec(text);
  if (t) out.tables = { tables: Number(t[1]), rows: Number(t[2]), misaligned: Number(t[3]) };
  const l = DOCS_LINKS.exec(text);
  if (l) out.linkLine = l[1].trim();
  return out;
}

/** 汇总：任何一步 exit≠0、解析不出来、清单为空 ⇒ 整体红。空步骤表也红（恒绿闸那一形）。 */
export function aggregate(steps) {
  const red = steps.filter(
    (s) => s.exit !== 0 || s.unparsed || s.empty === true || s.skipped === "red",
  );
  return { red: red.map((s) => s.name), exit: red.length ? 1 : 0 };
}

function exec(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    cwd: opts.cwd ?? ROOT,
    encoding: "utf8",
    maxBuffer: 256 * 1024 * 1024,
    timeout: opts.timeout ?? 20 * 60 * 1000,
  });
  const stdout = r.stdout ?? "";
  const stderr = r.stderr ?? "";
  if (r.error) return { exit: 127, stdout, stderr, output: `${r.error.message}\n${stdout}${stderr}` };
  return { exit: r.status ?? 1, stdout, stderr, output: `${stdout}${stderr}` };
}

/** vitest 即使不在 TTY 上也照发 ANSI 转义（10-12 闸1 首跑实测：`\x1b[2m      Tests \x1b[22m \x1b[32m16 passed`）
 *  ⇒ 凡按字面行摘读数的解析都得先剥色，否则汇总"看着在、读不出"，闸就把全绿读成假红。 */
export function stripAnsi(text) {
  return String(text ?? "").replace(/\u001b\[[0-9;]*m/g, "");
}

const tail = (text, n = 3) =>
  text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .slice(-n)
    .join(" ⏎ ");

/** 北京时刻（回执命名与抬头都用它——全站账面的钟点口径） */
export function beijingStamp(d = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(d);
  const g = (t) => parts.find((x) => x.type === t)?.value ?? "00";
  return `${g("month")}${g("day")}-${g("hour")}${g("minute")}`;
}

function receiptPath() {
  const dir = path.join(ROOT, "data-service", "runtime");
  fs.mkdirSync(dir, { recursive: true });
  const taken = fs
    .readdirSync(dir)
    .map((f) => /^gate1-(\d+)-/.exec(f))
    .filter(Boolean)
    .map((m) => Number(m[1]));
  const n = taken.length ? Math.max(...taken) + 1 : 1;
  return path.join(dir, `gate1-${n}-${beijingStamp()}.out`);
}

export function runOffline({ skip = new Set() } = {}) {
  const steps = [];
  const push = (s) => {
    steps.push(s);
    const flag = s.exit === 0 && !s.unparsed && s.empty !== true ? "OK " : "红 ";
    console.log(`${flag} ${s.name.padEnd(26)} exit=${s.exit} ${s.reading ?? ""}`);
  };

  const sha = exec("git", ["rev-parse", "HEAD"]).output.trim();
  const branch = exec("git", ["rev-parse", "--abbrev-ref", "HEAD"]).output.trim();
  const dirty = exec("git", ["status", "--porcelain"]).output.split(/\r?\n/).filter(Boolean);
  console.log(
    `== 闸1（${PY === VENV_PY ? "venv python" : "PATH python"}／node ${process.version}）对着的树：` +
      `${branch} ${sha.slice(0, 7)} dirty=${dirty.length}`,
  );

  const t0 = Date.now();
  if (skip.has("tsc")) push({ name: "tsc（跳过）", exit: 0, skipped: true });
  else if (!fs.existsSync(TSC_JS)) push({ name: "tsc --noEmit", exit: 1, reading: `入口不在：${TSC_JS}` });
  else {
    const r = exec(process.execPath, [TSC_JS, "--noEmit"], { cwd: WEB });
    push({ name: "tsc --noEmit", exit: r.exit, reading: r.exit ? tail(r.output, 6) : "0 error" });
  }

  if (skip.has("vitest")) push({ name: "vitest（跳过）", exit: 0, skipped: true });
  else if (!fs.existsSync(VITEST_JS)) push({ name: "vitest run", exit: 1, reading: `入口不在：${VITEST_JS}` });
  else {
    const r = exec(process.execPath, [VITEST_JS, "run"], { cwd: WEB, timeout: 30 * 60 * 1000 });
    const p = parseVitestSummary(stripAnsi(`${r.stdout}${r.stderr}`));
    push({
      name: "vitest run",
      exit: r.exit,
      unparsed: !p,
      reading: p
        ? `${p.passed}/${p.total} 通过（failed=${p.failed}${p.files ? `｜文件 ${p.files.passed}/${p.files.total}` : ""}）`
        : `汇总解析不出来：${tail(r.output)}`,
    });
  }

  const testDir = path.join(ROOT, "data-service", "tests");
  const files = fs.existsSync(testDir) ? fs.readdirSync(testDir).filter((f) => /^test_.*\.py$/.test(f)) : [];
  const { offline, liveListedButAbsent } = offlineSuites(files);
  if (skip.has("ds")) push({ name: "ds 离线逐套（跳过）", exit: 0, skipped: true });
  else {
    let sum = 0,
      tot = 0,
      unparsedCount = 0;
    const per = [];
    const bad = [];
    for (const f of offline) {
      const r = exec(PY, [path.join("tests", f)], { cwd: path.join(ROOT, "data-service") });
      const p = parseSuiteSummary(stripAnsi(r.stdout));
      per.push({ file: f, exit: r.exit, passed: p?.passed ?? null, total: p?.total ?? null });
      // 三种红各自点名，不互相遮蔽（10-12 实钻：exit≠0 与"解析不出"会同时发生）
      const reasons = [];
      if (r.exit !== 0) reasons.push(`exit=${r.exit}`);
      if (!p) reasons.push("汇总解析不出");
      else if (p.passed !== p.total) reasons.push(`${p.passed}/${p.total}`);
      if (reasons.length) bad.push(`${f}：${reasons.join("＋")}`);
      if (!p) unparsedCount += 1;
      if (p) {
        sum += p.passed;
        tot += p.total;
      }
    }
    push({
      name: "ds 离线逐套",
      exit: bad.length || offline.length === 0 || liveListedButAbsent.length ? 1 : 0,
      empty: offline.length === 0,
      unparsed: unparsedCount > 0,
      suites: per,
      reading:
        offline.length === 0
          ? "清单为空（tests/ 一个离线套件都没扫到）"
          : `${offline.length} 套 ${sum}/${tot}${unparsedCount ? `｜解析不出 ${unparsedCount} 枚` : ""}${
              bad.length ? ` 红：${bad.join(",")}` : ""
            }` +
            `${liveListedButAbsent.length ? `（③名单里的 ${liveListedButAbsent.join(",")} 在 tests/ 里没找到）` : ""}`,
    });
  }

  if (skip.has("docs")) push({ name: "docs 闸（跳过）", exit: 0, skipped: true });
  else {
    const b = exec(PY, [path.join("scripts", "docs-scan.py"), "--baseline", "--print"]);
    const s = exec(PY, [path.join("scripts", "docs-scan.py"), "--selftest"]);
    const l = exec(PY, [path.join("scripts", "docs-scan.py")]);
    const read = parseDocsReadings(stripAnsi(b.output));
    push({
      name: "docs 基线对账",
      exit: b.exit,
      unparsed: read.newAlarms === null,
      reading:
        read.newAlarms === null
          ? `解析不出来：${tail(b.output)}`
          : `NEW=${read.newAlarms}／KNOWN=${read.known}/${read.baselineTotal}` +
            (read.tables ? `｜表格 ${read.tables.tables}·${read.tables.rows}·错位 ${read.tables.misaligned}` : ""),
    });
    push({ name: "docs selftest", exit: s.exit, reading: tail(s.output, 1) });
    push({ name: "docs 断链", exit: l.exit, reading: read.linkLine ? `引用 ${read.linkLine.slice(0, 60)}` : tail(l.output, 1) });
  }

  const agg = aggregate(steps);
  const skipped = steps.filter((s) => s.skipped === true).map((s) => s.name);
  const elapsed = Math.round((Date.now() - t0) / 1000);
  console.log(
    `\n== 闸1 汇总：${agg.red.length ? `红 ${agg.red.length} 枚 ⇒ ${agg.red.join("、")}` : "全绿"}` +
      `（用时 ${elapsed}s${skipped.length ? `｜**跳过了 ${skipped.length} 步：${skipped.join("、")}**，这份回执不等于全量` : ""}）`,
  );
  const file = receiptPath();
  fs.writeFileSync(
    file,
    JSON.stringify(
      {
        at: new Date().toISOString(),
        atBeijing: beijingStamp(),
        tree: treeStamp({ sha, branch, dirty }),
        py: PY,
        node: process.version,
        elapsedS: elapsed,
        steps,
        skipped,
        aggregate: agg,
      },
      null,
      1,
    ) + "\n",
    "utf8",
  );
  console.log(`回执：${path.relative(ROOT, file)}`);
  return agg.exit;
}

export function selftest() {
  const checks = [];
  const ck = (name, cond) => {
    checks.push(cond);
    console.log(`  ${cond ? "PASS" : "FAIL"} ${name}`);
  };

  ck("两套汇总字面都解析得出来（② 的历史形与现形）",
    parseSuiteSummary("===== 42/42 通过 =====")?.passed === 42 &&
      parseSuiteSummary("== 基金定期报告解析单测：7/7 通过 ==")?.total === 7);
  ck("解析不出来交回 null，不当成 0/0 通过", parseSuiteSummary("no summary here") === null);
  ck("带 ANSI 转义的 vitest 收尾行：剥色后才读得出来（闸1 首跑就是被它假红的）",
    parseVitestSummary(stripAnsi("\u001b[2m      Tests \u001b[22m \u001b[1m\u001b[32m16 passed\u001b[39m\u001b[22m\u001b[90m (16)\u001b[39m")).total === 16);
  ck("不剥色时确实读不出来（证明上面那枚样本不是白给的）",
    parseVitestSummary("\u001b[2m      Tests \u001b[22m 16 passed (16)") === null);
  ck("北京时刻的字面形（回执文件名用它）", /^\d{4}-\d{4}$/.test(beijingStamp(new Date())));
  ck("Test Files 那一行也摘得出来（账上的 ① 是「测试数/文件数」两半）",
    parseVitestSummary(stripAnsi("\u001b[2m Test Files \u001b[22m \u001b[32m47 passed\u001b[39m\u001b[22m\u001b[90m (47)\u001b[39m\nTests 393 passed (393)")).files.total === 47);
  ck("vitest 两种收尾行都读得出",
    parseVitestSummary("Tests  3 failed | 371 passed (374)")?.failed === 3 &&
      parseVitestSummary("Tests  374 passed (374)")?.total === 374);
  ck("docs 读数：NEW／KNOWN／表格三枚都摘出来",
    parseDocsReadings("== 基线对账：NEW=0／KNOWN=21/21 ==\n== 表格扫描：表=43 数据行=443 错位=0 ==").newAlarms === 0);

  const list = offlineSuites(["test_p0.py", "test_p1.py", "test_g6_hk.py"]);
  ck("③ 的两套绝不进离线清单", !list.offline.includes("test_p0.py") && list.offline.length === 1);
  ck("tests/ 里少了名单上的套件要说出来",
    offlineSuites(["test_g6_hk.py"]).liveListedButAbsent.join(",") === "test_p0.py,test_p1.py");

  ck("清单为空＝红（恒返 0 的批跑器那一形）", aggregate([{ name: "ds", exit: 0, empty: true }]).exit === 1);
  ck("exit≠0＝红", aggregate([{ name: "tsc", exit: 2 }]).exit === 1);
  ck("汇总解析不出来＝红，哪怕 exit=0", aggregate([{ name: "vitest", exit: 0, unparsed: true }]).exit === 1);
  ck("③ 名单里的文件不见了＝红，不静默少跑两套",
    offlineSuites(["test_g6_hk.py"]).liveListedButAbsent.length === 2);
  ck("全绿时整体 0", aggregate([{ name: "tsc", exit: 0 }, { name: "ds", exit: 0, empty: false }]).exit === 0);
  ck("抬头只报 bool/长度意义上的 dirty 数",
    treeStamp({ sha: "abc", branch: "dev", dirty: ["a", "b"] }).dirtyPaths === 2);

  console.log(`\nselftest ${checks.filter(Boolean).length}/${checks.length} PASS`);
  return checks.every(Boolean) ? 0 : 1;
}

function main(argv) {
  if (argv.includes("--selftest")) return selftest();
  const skip = new Set();
  const i = argv.indexOf("--skip");
  if (i >= 0) (argv[i + 1] || "").split(",").forEach((s) => s && skip.add(s.trim()));
  if (argv.includes("--live")) {
    console.log("闸1 只有 --offline 这一档：③④ 要买上游额度，10-09 已定档＝人工到场执行（不排自动化）。");
    return 2;
  }
  return runOffline({ skip });
}

const invokedDirectly =
  process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) process.exit(main(process.argv.slice(2)));
