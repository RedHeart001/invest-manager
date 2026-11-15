#!/usr/bin/env node
// A3：隔离 Compose 验收。默认只检查 config；--run 才使用本地已有镜像启动容器。
// 不 build/pull，不读根 .env，不调用行情/K线/热点/同步/真实研报/LLM，不自动清理现场。
import { spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { networkInterfaces } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const COMPOSE = join(ROOT, "docker-compose.yml");
const RUN = process.argv.includes("--run");
if (!RUN && !process.argv.includes("--config-only")) {
  throw new Error("默认只验配置；真实隔离容器须显式 --run");
}
const id = `${process.pid}-${randomBytes(4).toString("hex")}`;
const PROJECT = `invest-verify-${process.pid}`;
const WORK = join(ROOT, ".tmp", `compose-verify-${id}`);
const BACKUPS = join(WORK, "backups");
mkdirSync(BACKUPS, { recursive: true });
const ENV_FILE = join(WORK, "synthetic.env");
const AUDIT = join(WORK, "audit.jsonl");
const WEB_IMAGE = "invest-manager-web:verify-local";
const DS_IMAGE = "invest-manager-data-service:verify-local";
const ingestToken = randomBytes(24).toString("hex");
const writeToken = randomBytes(24).toString("hex");
const port = 33000 + (process.pid % 1000);
const audit = [];
let checks = 0;

function check(name, condition, detail = "") {
  checks += 1;
  const row = { name, ok: Boolean(condition), detail };
  audit.push(row);
  writeFileSync(AUDIT, `${JSON.stringify(row)}\n`, { flag: "a" });
  console.log(`[${condition ? "PASS" : "FAIL"}] ${name}${!condition && detail ? ` <- ${detail}` : ""}`);
  if (!condition) throw new Error(name);
}
function execute(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    encoding: "utf8",
    timeout: options.timeout ?? 120_000,
    env: options.env ?? process.env,
    maxBuffer: 8 * 1024 * 1024,
  });
  return {
    status: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    error: result.error,
  };
}
function syntheticEnv(overrides = {}) {
  return {
    INGEST_TOKEN: ingestToken,
    WRITE_TOKEN: writeToken,
    WEB_PORT: String(port),
    WEB_IMAGE,
    DS_IMAGE,
    NODE_IMAGE: "dockerproxy.net/library/node:22-bookworm-slim",
    PY_IMAGE: "dockerproxy.net/library/python:3.12-slim",
    SCHEDULERS_ENABLED: "0",
    DATA_SERVICE_URL: "http://data-service:8000",
    // 与日常 Compose 同形。当前 Docker Desktop 下 internal=true 不落实宿主端口发布；
    // 隔离由独立卷/目录/端口、空外部密钥、关闭调度及不调用真实端点保证，不宣称网络层断网。
    APP_NETWORK_INTERNAL: "false",
    BACKUP_HOST_DIR: BACKUPS.replaceAll("\\", "/"),
    LLM_BASE_URL: "", LLM_API_KEY: "", LLM_MODEL: "", TAVILY_API_KEY: "",
    HTTP_PROXY: "", HTTPS_PROXY: "", NO_PROXY: "localhost,127.0.0.1,web,data-service",
    SKILLS_DIR: "./skills", MCP_CONFIG: "./mcp.json",
    ...overrides,
  };
}
// shell 环境优先于 env-file；显式覆盖所有敏感/网络键，防止继承真实配置。
const composeEnv = { ...process.env, ...syntheticEnv() };
writeFileSync(ENV_FILE, Object.entries(syntheticEnv()).map(([k, v]) => `${k}=${v}`).join("\n") + "\n");
function compose(args, env = composeEnv) {
  return execute("docker", ["compose", "-p", PROJECT, "--env-file", ENV_FILE, "-f", COMPOSE, ...args], { env, timeout: 180_000 });
}
function must(result, label) {
  if (result.status !== 0 || result.error) {
    throw new Error(`${label}：exit=${result.status} ${result.error?.message ?? ""}\n${result.stderr.slice(-1500)}`);
  }
  return result.stdout;
}
function treeStamp(paths) {
  return paths.map((path) => {
    if (!existsSync(path)) return { path, missing: true };
    const stat = statSync(path);
    if (!stat.isDirectory()) {
      return { path, size: stat.size, hash: createHash("sha256").update(readFileSync(path)).digest("hex") };
    }
    return { path, entries: readdirSync(path).sort().map((name) => {
      const full = join(path, name);
      const s = statSync(full);
      return { name, size: s.size, hash: s.isFile() ? createHash("sha256").update(readFileSync(full)).digest("hex") : "dir" };
    }) };
  });
}
async function waitHealth() {
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    const ps = compose(["ps", "--format", "json"]);
    const text = ps.stdout.trim();
    let rows = [];
    try { rows = text.startsWith("[") ? JSON.parse(text) : text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)); } catch { /* retry */ }
    const web = rows.find((r) => r.Service === "web");
    const ds = rows.find((r) => r.Service === "data-service");
    if (web?.Health === "healthy" && ds?.Health === "healthy") return;
    if (ps.status !== 0) throw new Error(`compose ps 失败：${ps.stderr}`);
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("双服务健康等待超时");
}
async function request(path, options = {}) {
  const response = await fetch(`http://127.0.0.1:${port}${path}`, { signal: AbortSignal.timeout(15_000), ...options });
  return { status: response.status, body: await response.text() };
}
function dbQuery(expression) {
  const script = `import {PrismaClient} from '@prisma/client'; const p=new PrismaClient(); console.log(JSON.stringify(await (${expression}))); await p.$disconnect();`;
  return JSON.parse(must(compose(["exec", "-T", "web", "node", "--input-type=module", "-e", script]), "隔离 DB 查询"));
}

// 缺 token 与空 token 都必须在 config 阶段失败；不打印配置或 token。
const missing = compose(["config", "--quiet"], { ...composeEnv, INGEST_TOKEN: "" });
check("空 INGEST_TOKEN 被 config 拒绝", missing.status !== 0);
const missingWrite = compose(["config", "--quiet"], { ...composeEnv, WRITE_TOKEN: "" });
check("空 WRITE_TOKEN 被 config 拒绝", missingWrite.status !== 0);
const rendered = JSON.parse(must(compose(["config", "--format", "json"]), "有效 Compose config"));
check("双侧 INGEST_TOKEN 同值", rendered.services.web.environment.INGEST_TOKEN === rendered.services["data-service"].environment.INGEST_TOKEN);
check("双侧 WRITE_TOKEN 同值", rendered.services.web.environment.WRITE_TOKEN === rendered.services["data-service"].environment.WRITE_TOKEN);
check("Web 仅绑定回环", rendered.services.web.ports.length === 1 && rendered.services.web.ports[0].host_ip === "127.0.0.1");
check("DS 未发布宿主端口", !rendered.services["data-service"].ports);
// Compose JSON 对默认 false 可省略 internal 字段；只禁止显式启用 internal。
check("隔离网络与日常 Compose 同形（非 internal，不宣称网络层断网）", rendered.networks.app.internal !== true);
check("隔离模式关闭三类调度", rendered.services["data-service"].environment.SCHEDULERS_ENABLED === "0");
check("Web 刷新进度落在可写命名卷而非镜像目录", rendered.services.web.environment.REFRESH_PROGRESS_FILE === "/app/data/runtime/refresh-progress.json");
check("备份不指向开发 backups", rendered.services["data-service"].volumes.some((v) => v.target === "/backup" && resolve(v.source) === BACKUPS));
console.log(`[config-only] ${checks}/${checks} 通过；现场=${WORK}`);

if (RUN) {
  for (const image of [WEB_IMAGE, DS_IMAGE]) {
    const inspected = execute("docker", ["image", "inspect", image]);
    check(`本地镜像已存在（不自动 pull）：${image}`, inspected.status === 0);
  }
  const protectedPaths = [
    join(ROOT, "web", "prisma", "dev.db"), join(ROOT, "web", "prisma", "dev.db-wal"), join(ROOT, "web", "prisma", "dev.db-shm"),
    join(ROOT, "web", "runtime"), join(ROOT, "data-service", "runtime"), join(ROOT, "backups"),
  ];
  const before = treeStamp(protectedPaths);
  must(compose(["up", "-d", "--no-build", "web", "data-service"]), "隔离 Compose 启动");
  await waitHealth();
  check("Web/DS 两容器健康", true);
  const health = await request("/api/health");
  check("宿主回环 Web/DB 健康", health.status === 200 && JSON.parse(health.body).db === "ok");
  const lan = Object.values(networkInterfaces()).flat().filter((item) => item && item.family === "IPv4" && !item.internal).map((item) => item.address);
  check("存在可用于 LAN 负例的宿主地址", lan.length > 0);
  let lanReached = false;
  try { await fetch(`http://${lan[0]}:${port}/api/health`, { signal: AbortSignal.timeout(2500) }); lanReached = true; } catch { /* expected */ }
  check("LAN 地址不可访问回环绑定端口", !lanReached);

  const emptyResearch = await request("/api/research?type=stock&code=A3SYNTH");
  check("鉴权负例前 ResearchReport 为空", emptyResearch.status === 200 && JSON.parse(emptyResearch.body).status === "none");
  const noIngest = await request("/api/research/ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  const badIngest = await request("/api/research/ingest", { method: "POST", headers: { "Content-Type": "application/json", "x-ingest-token": "wrong" }, body: "{}" });
  const noWrite = await request("/api/sync?type=bogus", { method: "POST" });
  const badWrite = await request("/api/sync?type=bogus", { method: "POST", headers: { "x-write-token": "wrong" } });
  check("无/错 ingest token 均 401", noIngest.status === 401 && badIngest.status === 401);
  check("无/错 write token 均 401（未进入同步）", noWrite.status === 401 && badWrite.status === 401);
  const tasks = JSON.parse(must(compose(["exec", "-T", "data-service", "python", "-c", "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/research/status'))))"]), "DS 零副作用查询"));
  check("鉴权负例未创建 DS 研究任务", tasks.running === 0 && tasks.total === 0 && tasks.collect?.inFlight === 0);
  const stillEmpty = await request("/api/research?type=stock&code=A3SYNTH");
  check("鉴权负例未写 Web 数据", stillEmpty.status === 200 && JSON.parse(stillEmpty.body).status === "none");

  dbQuery(`p.product.create({data:{type:'stock',code:'A3SYNTH',name:'A3 隔离合成标的'}}).then(()=>({seeded:true}))`);
  const callbackScript = `import json,os,urllib.request
payload={'type':'stock','code':'A3SYNTH','date':'2026-11-14','report':{'ok':True,'rating':'合成','summary':'A3 容器合成回调，不是真实研报','analysts':[],'debate':{'bull':[],'bear':[]},'risk':['synthetic'],'meta':{'engine':'a3-synthetic','llmCalls':0,'sources':['a3-synthetic']}}}
req=urllib.request.Request('http://web:3000/api/research/ingest',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-ingest-token':os.environ['INGEST_TOKEN']},method='POST')
with urllib.request.urlopen(req,timeout=15) as r: print(r.status, r.read().decode())`;
  const callback = must(compose(["exec", "-T", "data-service", "python", "-c", callbackScript]), "容器内合成回调");
  check("DS→Web 正确合成 token 回调成功", callback.startsWith("200 ") && callback.includes('"ok":true'));
  const report = await request("/api/research?type=stock&code=A3SYNTH");
  const reportBody = JSON.parse(report.body);
  check("合成回调落入隔离 ResearchReport", report.status === 200 && reportBody.status === "done" && reportBody.summary?.includes("不是真实研报"));

  const webUid = must(compose(["exec", "-T", "web", "node", "-e", "console.log(process.getuid())"]), "Web UID").trim();
  check("Web 进程非 root", webUid === "1000", `uid=${webUid}`);
  const dsUidScript = `import os
found=[]
for pid in os.listdir('/proc'):
 if not pid.isdigit(): continue
 try:
  cmd=open(f'/proc/{pid}/cmdline','rb').read().replace(b'\\0',b' ').decode()
  if 'uvicorn app.main:app' in cmd:
   status=dict(line.split(':',1) for line in open(f'/proc/{pid}/status') if ':' in line)
   found.append(int(status['Uid'].split()[0]))
 except (FileNotFoundError,ProcessLookupError,PermissionError): pass
print(','.join(map(str,sorted(set(found)))))`;
  const dsUids = must(compose(["exec", "-T", "data-service", "python", "-c", dsUidScript]), "DS 服务 UID").trim();
  check("DS uvicorn 服务进程非 root", dsUids === "1000", `uid=${dsUids}`);

  must(compose(["restart", "web"]), "重启隔离 Web");
  await waitHealth();
  const persisted = await request("/api/research?type=stock&code=A3SYNTH");
  const persistedBody = JSON.parse(persisted.body);
  check("命名卷在 Web 重启后保留合成数据", persisted.status === 200 && persistedBody.status === "done" && persistedBody.summary?.includes("不是真实研报"));

  const backupOutput = must(compose(["exec", "-T", "data-service", "python", "-m", "scripts.backup_db"]), "隔离在线备份");
  const backupName = /\/backup\/(dev-[^\s]+\.db)/.exec(backupOutput)?.[1];
  check("备份写入独立宿主目录且 integrity=ok", Boolean(backupName) && existsSync(join(BACKUPS, backupName)) && backupOutput.includes("integrity_check=ok"));
  const restoreVolume = `${PROJECT}-restore`;
  must(execute("docker", ["volume", "create", restoreVolume]), "创建临时恢复卷");
  const restored = execute("docker", ["run", "--rm", "--network", "none", "-v", `${restoreVolume}:/data`, "-v", `${BACKUPS.replaceAll("\\", "/")}:/backup:ro`, DS_IMAGE, "python", "-m", "scripts.backup_db", "--restore", `/backup/${backupName}`, "--source", "/data/dev.db"]);
  must(restored, "恢复到独立临时卷");
  const verifyRestore = execute("docker", ["run", "--rm", "--network", "none", "-v", `${restoreVolume}:/data`, DS_IMAGE, "python", "-c", "import sqlite3; c=sqlite3.connect('/data/dev.db'); print(c.execute(\\\"select summary from ResearchReport where code='A3SYNTH'\\\").fetchone()[0]); print(c.execute('pragma integrity_check').fetchone()[0])"]);
  const restoreText = must(verifyRestore, "临时恢复卷只读核验");
  check("临时卷恢复含合成回调且完整性正常", restoreText.includes("不是真实研报") && restoreText.includes("ok"));

  const after = treeStamp(protectedPaths);
  check("开发 DB/runtime/backups 前后指纹不变", JSON.stringify(before) === JSON.stringify(after));
  console.log(`[run] ${checks}/${checks} 通过；项目=${PROJECT}，Web=http://127.0.0.1:${port}`);
  console.log(`[run] 现场、隔离容器/卷及临时恢复卷保留；未自动清理：${WORK}`);
}
