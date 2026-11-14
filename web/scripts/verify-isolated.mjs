// CR10-31：显式隔离冷启动验收。默认只跑 P0，不跑 verify-all。
// P5 空表受控档须同时给命令行与环境开关：
//   VERIFY_P5_COLD_FIXTURE=1 node scripts/verify-isolated.mjs --p5-cold
// 替身只验证空表分支、任务幂等/回调和聊天流，不替代真实行情、研报或 LLM 验收。
// 临时根保留用于取证；只停止本脚本创建的进程，不清理开发实例或真实 backups。
import { spawn, spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { cpSync, existsSync, mkdirSync, openSync, closeSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const P5_COLD = process.argv.includes("--p5-cold");
if (P5_COLD !== (process.env.VERIFY_P5_COLD_FIXTURE === "1")) {
  throw new Error("P5 受控档必须同时设置 --p5-cold 与 VERIFY_P5_COLD_FIXTURE=1；不得用于其他模式");
}

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO_DIR = resolve(WEB_DIR, "..");
const DS_DIR = join(REPO_DIR, "data-service");
const PY = join(DS_DIR, ".venv", "Scripts", "python.exe");
const ROOT = join(REPO_DIR, ".tmp", `verify-${process.pid}-${randomBytes(4).toString("hex")}`);
const RUNTIME = join(ROOT, "runtime");
const REPORTS = join(ROOT, "reports");
const LOGS = join(ROOT, "logs");
for (const dir of [ROOT, RUNTIME, REPORTS, LOGS, join(ROOT, "backups")]) mkdirSync(dir, { recursive: true });
if (!existsSync(PY)) throw new Error(`隔离 Python 不存在：${PY}`);

function assertSafeUrl(raw, name) {
  const url = new URL(raw);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1") throw new Error(`${name} 必须是回环 HTTP 地址`);
  const port = Number(url.port);
  if (!port || [3000, 8000].includes(port)) throw new Error(`${name} 禁止使用开发端口`);
  return url.origin;
}

async function freePort() {
  const server = createServer();
  await new Promise((ok, fail) => server.listen(0, "127.0.0.1", ok).once("error", fail));
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  await new Promise((ok) => server.close(ok));
  if (!port) throw new Error("未分配到隔离端口");
  return port;
}

const webPort = Number(process.env.VERIFY_WEB_PORT ?? await freePort());
const dsPort = Number(process.env.VERIFY_DS_PORT ?? await freePort());
const llmPort = P5_COLD ? Number(process.env.VERIFY_LLM_PORT ?? await freePort()) : 0;
const WEB_URL = assertSafeUrl(`http://127.0.0.1:${webPort}`, "VERIFY_WEB_PORT");
const DS_URL = assertSafeUrl(`http://127.0.0.1:${dsPort}`, "VERIFY_DS_PORT");
const LLM_URL = P5_COLD ? assertSafeUrl(`http://127.0.0.1:${llmPort}`, "VERIFY_LLM_PORT") : "";
if (new Set([webPort, dsPort, llmPort].filter(Boolean)).size !== (P5_COLD ? 3 : 2)) throw new Error("Web/DS/LLM 必须使用不同端口");
const DB = join(ROOT, "migrate", "prisma", "test.db");
const DATABASE_URL = `file:${DB.replaceAll("\\", "/")}`;
const token = randomBytes(24).toString("hex");
const fixtureKey = P5_COLD ? randomBytes(24).toString("hex") : "";
const fixtureAudit = join(ROOT, "p5-fixture-audit.jsonl");
const PRELOAD = join(WEB_DIR, "scripts", "verify-loopback-only.mjs");
const nextDist = `node_modules/.cache/isolated-next-${process.pid}`;
const isolatedTsconfig = join(WEB_DIR, "node_modules", ".cache", `isolated-tsconfig-${process.pid}.json`);
const NODE_OPTIONS = [process.env.NODE_OPTIONS, `--import=${pathToFileURL(PRELOAD).href}`].filter(Boolean).join(" ");
const children = [];
const logFds = [];
const nextEnvPath = join(WEB_DIR, "next-env.d.ts");
const nextEnvBackup = join(ROOT, "next-env.d.ts.before");
let nextEnvSaved = false;

function start(name, command, args, options) {
  const logPath = join(LOGS, `${name}.log`);
  closeSync(openSync(logPath, "a"));
  const fd = openSync(logPath, "a");
  logFds.push(fd);
  const child = spawn(command, args, { ...options, stdio: ["ignore", fd, fd], windowsHide: true });
  children.push(child);
  child.once("exit", (code) => { if (code && !stopping) console.error(`${name} 提前退出：${code}；日志=${join(LOGS, `${name}.log`)}`); });
  return child;
}


function run(command, args, env, name, cwd = WEB_DIR) {
  console.log(`[isolated] ${name}`);
  const result = spawnSync(command, args, { cwd, env, encoding: "utf8", timeout: 120_000 });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) throw new Error(`${name} 失败：exit=${result.status ?? "?"}`);
}

async function waitHealth(url, child, name) {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`${name} 启动退出，日志=${join(LOGS, `${name}.log`)}`);
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
      const body = await res.json();
      if (res.ok && body.status === "ok" && (name !== "web" || body.db === "ok")) return;
    } catch { /* 有界等待 */ }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${name} 健康检查超时；日志=${join(LOGS, `${name}.log`)}`);
}

function treeStamp(paths) {
  return Object.fromEntries(paths.map((path) => {
    if (!existsSync(path)) return [path, null];
    const stat = statSync(path);
    if (!stat.isDirectory()) return [path, createHash("sha256").update(readFileSync(path)).digest("hex")];
    return [path, Object.fromEntries(readdirSync(path).sort().map((name) => {
      const file = join(path, name);
      return [name, statSync(file).isFile() ? createHash("sha256").update(readFileSync(file)).digest("hex") : "<dir>"];
    }))];
  }));
}

let stopping = false;
async function stopChildren() {
  stopping = true;
  for (const child of children.reverse()) {
    if (child.exitCode === null) spawnSync("taskkill.exe", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore" });
  }
  for (const fd of logFds) closeSync(fd);
}

try {
  const env = { ...process.env };
  for (const key of ["LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "TAVILY_API_KEY", "SEARCH_API_KEY"]) env[key] = "";
  Object.assign(env, {
    DATABASE_URL, DB_PATH: DB, DATA_SERVICE_URL: DS_URL,
    WEB_BASE_URL: WEB_URL, WEB_API_BASE: WEB_URL,
    TEST_BASE: WEB_URL, WEB_URL, TEST_DATA: DS_URL,
    INGEST_TOKEN: token, WRITE_TOKEN: token,
    SYNC_STATE_FILE: join(RUNTIME, "sync-state.json"),
    HOTSPOT_STATE_FILE: join(RUNTIME, "hotspot-state.json"),
    LIMITER_STATE_FILE: join(RUNTIME, "limiter-state.json"),
    REFRESH_PROGRESS_FILE: join(RUNTIME, "refresh-progress.json"),
    BACKUP_DIR: join(ROOT, "backups"), NEXT_DIST_DIR: nextDist, NEXT_TSCONFIG_PATH: relative(WEB_DIR, isolatedTsconfig),
    VERIFY_REPORT_DIR: REPORTS, PYTHONPATH: DS_DIR, PYTHONDONTWRITEBYTECODE: "1",
    NO_PROXY: "*", no_proxy: "*", NODE_OPTIONS,
    MCP_CONFIG: join(ROOT, "disabled-mcp.json"),
    VERIFY_DS_PORT: String(dsPort), VERIFY_LLM_PORT: String(llmPort),
    VERIFY_FIXTURE_SERVER: P5_COLD ? "1" : "0",
    VERIFY_FIXTURE_KEY: fixtureKey, VERIFY_FIXTURE_AUDIT: fixtureAudit,
  });
  if (P5_COLD) {
    env.LLM_API_KEY = fixtureKey;
    env.LLM_MODEL = "isolated-fixture";
    env.LLM_BASE_URL = LLM_URL;
  }
  writeFileSync(join(ROOT, "disabled-mcp.json"), JSON.stringify({ servers: [] }));
  writeFileSync(isolatedTsconfig, JSON.stringify({
    extends: join(WEB_DIR, "tsconfig.json").replaceAll("\\", "/"),
    compilerOptions: { baseUrl: WEB_DIR.replaceAll("\\", "/") },
    include: [relative(dirname(isolatedTsconfig), join(WEB_DIR, "next-env.d.ts")).replaceAll("\\", "/"), relative(dirname(isolatedTsconfig), join(WEB_DIR, "**/*.ts")).replaceAll("\\", "/"), relative(dirname(isolatedTsconfig), join(WEB_DIR, "**/*.tsx")).replaceAll("\\", "/"), relative(dirname(isolatedTsconfig), join(WEB_DIR, nextDist, "types/**/*.ts")).replaceAll("\\", "/")],
    exclude: [],
  }, null, 2));
  const protectedPaths = [join(WEB_DIR, "prisma", "dev.db"), join(WEB_DIR, "prisma", "dev.db-wal"),
    join(WEB_DIR, "prisma", "dev.db-shm"), join(WEB_DIR, "runtime", "refresh-progress.json"),
    join(DS_DIR, "runtime", "sync-state.json"), join(DS_DIR, "runtime", "hotspot-state.json"),
    join(DS_DIR, "runtime", "limiter-state.json"), join(REPO_DIR, "backups"), join(WEB_DIR, "tsconfig.json")];
  const before = treeStamp(protectedPaths);
  // Next dev 会改写 next-env.d.ts 的 routes 路径；保存并在 finally 恢复本轮启动前内容。
  cpSync(nextEnvPath, nextEnvBackup);
  nextEnvSaved = true;
  // Prisma CLI 的相对 URL 以 schema 所在目录为基准。只复制 schema/migrations；
  // 不得 junction 整个 prisma（Windows 下会落回仓库 test.db，而非本轮临时目录）。
  const migrateDir = join(ROOT, "migrate");
  mkdirSync(join(migrateDir, "prisma"), { recursive: true });
  cpSync(join(WEB_DIR, "prisma", "schema.prisma"), join(migrateDir, "prisma", "schema.prisma"));
  cpSync(join(WEB_DIR, "prisma", "migrations"), join(migrateDir, "prisma", "migrations"), { recursive: true });
  run(process.execPath, [join(WEB_DIR, "node_modules", "prisma", "build", "index.js"), "migrate", "deploy", "--schema", join(migrateDir, "prisma", "schema.prisma")],
    { ...env, DATABASE_URL: "file:./test.db" }, "临时 SQLite 迁移", migrateDir);
  // CLI 相对 URL 以 schema 目录为基准；把唯一目标库显式对账到启动器的绝对路径。
  if (!existsSync(DB)) throw new Error("迁移未生成临时 SQLite");
  const web = start("web", process.execPath, [join(WEB_DIR, "node_modules", "next", "dist", "bin", "next"), "dev", "--hostname", "127.0.0.1", "--port", String(webPort)], { cwd: WEB_DIR, env });
  await waitHealth(`${WEB_URL}/api/health`, web, "web");
  // P0 只验真实 DS 的 HTTP/DB 冷启动，关闭 lifespan，不触发调度器。
  // P5 使用本地替身，绝不导入真实 DS，因此不会执行真实采集或启动补跑。
  if (P5_COLD) {
    const fixture = start("p5-fixture", process.execPath, [join(WEB_DIR, "scripts", "verify-p5-fixture-server.mjs")], { cwd: WEB_DIR, env });
    await waitHealth(`${DS_URL}/health`, fixture, "fixture DS");
  } else {
    const ds = start("ds", PY, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(dsPort), "--lifespan", "off"], { cwd: DS_DIR, env });
    await waitHealth(`${DS_URL}/health`, ds, "ds");
  }
  if (P5_COLD) {
    // 一个同步子进程完成 ResearchReport 空表证明和最小 Product 种入，避免顺序歧义。
    const prepared = spawnSync(process.execPath, ["--input-type=module", "-e",
      'import {PrismaClient} from "@prisma/client"; const p=new PrismaClient(); const n=await p.researchReport.count(); if(n!==0) throw new Error(`ResearchReport 非空：${n}`); console.log("前置证明：ResearchReport=0", await p.$queryRawUnsafe("PRAGMA database_list"), "products", await p.product.count()); await p.product.createMany({data:[{type:"stock",code:"600519",name:"受控 A 股"},{type:"us",code:"AAPL",name:"受控美股"}]}); console.log("合成 Product=2"); await p.$disconnect();'],
      { cwd: WEB_DIR, env, encoding: "utf8", timeout: 30_000 });
    process.stdout.write(prepared.stdout ?? "");
    process.stderr.write(prepared.stderr ?? "");
    if (prepared.status !== 0) throw new Error("P5 空表证明/合成 Product 种入失败");
  }
  // P5 档有明确的最小合成 Product；P0 档仍要求迁移后的 Product=0。
  run(process.execPath, [join(WEB_DIR, "scripts", "test-db.mjs"), ...(P5_COLD ? ["--minimal"] : ["--cold"])], env, "P0 冷启动结构与写读删");
  if (P5_COLD) {
    run(process.execPath, [join(WEB_DIR, "scripts", "test-p5.mjs")], env, "P5 空表冷启动受控档（11 条）", WEB_DIR);
    const audit = existsSync(fixtureAudit) ? readFileSync(fixtureAudit, "utf8").trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)) : [];
    const researchStarts = audit.filter((row) => row.kind === "research-start").length;
    const callbacks = audit.filter((row) => row.kind === "ingest-callback" && row.status === 200).length;
    const llmCalls = audit.filter((row) => row.kind === "llm").length;
    if (researchStarts !== 2 || callbacks !== 2 || llmCalls !== 1) {
      throw new Error(`P5 受控替身调用数异常：researchStart=${researchStarts} ingest=${callbacks} llm=${llmCalls}`);
    }
    console.log("[isolated] P5 受控替身调用对账：researchStart=2 ingest=2 llm=1；全部为本地合成响应");
  }
  const after = treeStamp(protectedPaths);
  if (JSON.stringify(before) !== JSON.stringify(after)) throw new Error("开发数据库/runtime/backups 前后指纹变化；保留现场供归因");
  console.log(`[isolated] ${P5_COLD ? "P5 冷启动受控档" : "冷启动健康"}与隔离指纹通过。临时现场保留：${ROOT}`);
} catch (error) {
  console.error(`[isolated] 未通过：${error instanceof Error ? error.message : error}`);
  console.error(`[isolated] 临时现场保留：${ROOT}`);
  process.exitCode = 1;
} finally {
  await stopChildren();
  if (nextEnvSaved) cpSync(nextEnvBackup, nextEnvPath);
}
