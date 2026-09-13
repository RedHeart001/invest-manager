#!/usr/bin/env node
// P7 容器化冒烟脚本：compose up 后一键验证（5 项）
//
//   1. BFF /api/health（web 应用 + DB 连通）
//   2. BFF /api/quote（→ data-service → 外部行情源，含降级标注）
//   3. BFF /api/kline（KlineDaily 增量缓存链路）
//   4. BFF /api/search（Prisma FTS5 检索）
//   5. BFF /api/tools/status（Tool Gateway：内置工具 / 技能 / MCP 连接状态）
//   + 容器内 data-service /health（data-service 端口不对外，只能经 compose exec）
//
// 用法：node scripts/smoke.mjs            （默认 http://localhost:3000）
//      BASE=http://localhost:3100 node scripts/smoke.mjs

import { execFileSync } from "node:child_process";

const BASE = process.env.BASE ?? "http://localhost:3000";
const TIMEOUT = Number(process.env.SMOKE_TIMEOUT_MS ?? 30000);

let passed = 0;
let failed = 0;
let unseeded = false;
const failures = [];

function ok(name, cond, detail = "") {
  if (cond) {
    passed += 1;
    console.log(`  OK ${name}`);
  } else {
    failed += 1;
    failures.push(`${name}${detail ? ` — ${detail}` : ""}`);
    console.log(`  NG ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

async function getJson(path) {
  const res = await fetch(`${BASE}${path}`, { signal: AbortSignal.timeout(TIMEOUT) });
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* 非 JSON（HTML 错误页等） */
  }
  return { status: res.status, body };
}

async function main() {
  console.log(`\n== P7 冒烟：BASE=${BASE}\n`);

  console.log("[1] web /api/health（应用 + 数据库）");
  {
    const { status, body } = await getJson("/api/health");
    ok("HTTP 200 且 db=ok", status === 200 && body?.db === "ok", `status=${status} body=${JSON.stringify(body)}`);
  }

  console.log("[2] /api/quote（BFF → data-service → 行情源）");
  {
    const { status, body } = await getJson("/api/quote?type=stock&code=600519");
    const price = Number(body?.price);
    ok("HTTP 200 且返回价格", status === 200 && Number.isFinite(price) && price > 0, `status=${status} body=${JSON.stringify(body).slice(0, 160)}`);
    if (body?.note) console.log(`     （降级标注：${String(body.note).slice(0, 80)}）`);
  }

  console.log("[3] /api/kline（增量缓存链路）");
  {
    const { status, body } = await getJson("/api/kline?type=stock&code=600519");
    const candles = body?.candles ?? body?.data?.candles ?? [];
    ok("HTTP 200 且返回 K 线", status === 200 && Array.isArray(candles) && candles.length > 0, `status=${status} candles=${Array.isArray(candles) ? candles.length : "n/a"}`);
  }

  console.log("[4] /api/search（Prisma FTS5）");
  {
    // ① 浏览分支：探测库内是否已同步产品主数据（全新数据卷迁移后为空，属预期状态）
    const browse = await getJson("/api/search?type=fund&limit=1");
    const total = Number(browse.body?.total ?? 0);
    ok(
      "浏览分支可用（browse=true）",
      browse.status === 200 && browse.body?.browse === true,
      `status=${browse.status} body=${JSON.stringify(browse.body).slice(0, 120)}`,
    );

    // ② 关键词检索：结构必须合法；库内已有数据时要求能命中
    const { status, body } = await getJson("/api/search?q=110022&limit=5");
    const results = body?.results ?? [];
    ok(
      "关键词检索返回合法结构",
      status === 200 && Array.isArray(results),
      `status=${status} body=${JSON.stringify(body).slice(0, 120)}`,
    );
    if (total > 0) {
      ok("关键词检索有命中", results.length > 0, `results=${results.length}（库内 ${total} 条基金）`);
    } else {
      unseeded = true;
      console.log(
        `     ⚠ 产品主数据为空（全新数据卷的预期状态，库内 ${total} 条）→ 请先执行：\n` +
          `       curl -X POST ${BASE}/api/sync      # 全量同步约 3~8 分钟（受外部源限流影响）`,
      );
    }
  }

  console.log("[5] /api/tools/status（Tool Gateway）");
  {
    const { status, body } = await getJson("/api/tools/status");
    const ns = body?.namespaces ?? {};
    ok(
      "HTTP 200 且三分命名空间齐全",
      status === 200 && (ns.builtin?.count ?? 0) > 0 && Boolean(ns.skill) && Boolean(ns.mcp),
      `status=${status} builtin=${ns.builtin?.count} skills=${ns.skill?.count}`,
    );
    const servers = ns.mcp?.servers ?? [];
    if (servers.length > 0) {
      console.log(`     （MCP: ${servers.map((s) => `${s.name}=${s.state}`).join(", ")}）`);
    }
  }

  console.log("[6] 容器内 data-service /health（端口不对外，走 compose exec）");
  {
    try {
      const out = execFileSync(
        "docker",
        [
          "compose",
          "exec",
          "-T",
          "data-service",
          "python",
          "-c",
          "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5).read().decode())",
        ],
        { encoding: "utf8", timeout: 60000 },
      ).trim();
      ok("容器内 health 返回 ok", /"status"\s*:\s*"ok"/.test(out), out.slice(0, 120));
    } catch (e) {
      ok("容器内 health 返回 ok", false, String(e.message ?? e).slice(0, 160));
    }
  }

  console.log(`\n== 冒烟结果：${passed} 通过 / ${failed} 失败 ==`);
  if (unseeded) {
    console.log("⚠ 数据未初始化：容器冒烟通过，但产品主数据为空（搜索无结果属预期）。");
    console.log(`   执行 curl -X POST ${BASE}/api/sync 同步后再跑一次本脚本即可全绿。`);
  }
  if (failures.length) {
    console.log("\n失败项：");
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
}

main().catch((e) => {
  console.error("冒烟执行异常：", e);
  process.exit(1);
});
