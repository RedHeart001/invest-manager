// OPT-1 路线 C 验收：用真实 LLM 评估 load_skill 技能路由行为
//   指标：明确命中消息的加载率（门槛 ≥90%）/ 明确无关消息的误加载率（门槛 ≤10%）
//   依据：docs/FIX-LEDGER.md OPT-1（2026-09-22 拍板）
//
// 用法：先启动 data-service(8000) + web(3000)（SKILL_ROUTER=llm），再
//   node scripts/eval-skill-router.mjs
// 不进 verify-all：依赖真实 LLM 与数据源，结果供人工拍板。
//
// 判定口径：done.skills 含期望技能 → 命中；期望不加载而 done.skills 非空 → 误加载。

const BASE = process.env.TEST_BASE ?? "http://localhost:3000";
const THRESHOLD_LOAD = 0.9; // 明确命中消息的加载率下限
const THRESHOLD_FALSE = 0.1; // 明确无关消息的误加载率上限

const CASES = [
  // ---- 期望加载（shouldLoad: true + 期望技能名） ----
  { message: "生成今天的热点日报", expect: "hotspot-daily", shouldLoad: true },
  { message: "帮我汇总一下今日市场热点", expect: "hotspot-daily", shouldLoad: true },
  { message: "110022 这只基金的季报怎么看？", expect: "fund-report-analysis", shouldLoad: true },
  { message: "这只基金最新年报里行业配置有什么变化？", expect: "fund-report-analysis", shouldLoad: true },
  { message: "这只票最近为什么涨？帮我看看技术面", expect: "tech-indicators", shouldLoad: true },
  { message: "看看贵州茅台的走势阶段和支撑位", expect: "tech-indicators", shouldLoad: true },
  // ---- 期望不加载（技能无关） ----
  { message: "帮我算一下 1 加 1 等于几", shouldLoad: false },
  { message: "你好，简单介绍一下你自己能做什么", shouldLoad: false },
  { message: "Python 和 JavaScript 哪个更适合写爬虫？", shouldLoad: false },
  { message: "帮我把这段话总结成一句话：市场今天缩量震荡，板块轮动加快。", shouldLoad: false },
  { message: "600519 现在多少钱？", shouldLoad: false },
];

let passed = 0;
let failed = 0;
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

/** 读取 SSE（与 test-p6 相同的事件解析，取 done 事件） */
async function readSse(res, timeoutMs = 90_000) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const events = [];
  let terminated = false;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline && !terminated) {
    const { value, done } = await reader.read();
    if (done) break;
    if (value) buffer += decoder.decode(value, { stream: true });
    while (true) {
      const evIdx = buffer.indexOf("event:");
      if (evIdx < 0) break;
      const dataIdx = buffer.indexOf("data:", evIdx);
      if (dataIdx < 0) break;
      const evEnd = buffer.indexOf("\n", evIdx);
      const dataEnd = buffer.indexOf("\n", dataIdx);
      if (evEnd < 0 || dataEnd < 0 || dataEnd < evEnd) break;
      const ev = buffer.slice(evIdx + 6, evEnd).trim();
      const dataRaw = buffer.slice(dataIdx + 5, dataEnd).trim();
      buffer = buffer.slice(dataEnd + 1);
      let data = {};
      try {
        data = JSON.parse(dataRaw);
      } catch {
        /* 忽略非 JSON */
      }
      events.push({ ev, data });
      if (ev === "done" || ev === "error") {
        terminated = true;
        break;
      }
    }
  }
  return events;
}

async function main() {
  console.log(`\n== 技能路由行为评估（SKILL_ROUTER 应为 llm）：BFF=${BASE} ==\n`);
  const sessionIds = [];

  // 前置：确认服务端处于 llm 档
  const status = await (await fetch(`${BASE}/api/tools/status`)).json();
  const mode = status.namespaces?.skill?.router;
  if (mode !== "llm") {
    console.error(`服务端路由模式为 ${mode}，本脚本仅评估 llm 档（keyword 档行为由 test-p6 覆盖）`);
    process.exit(1);
  }

  let loadHit = 0;
  let loadTotal = 0;
  let falseLoad = 0;
  let falseTotal = 0;

  for (const c of CASES) {
    const res = await fetch(`${BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: c.message }),
    });
    const events = await readSse(res);
    const meta = events.find((e) => e.ev === "meta")?.data ?? null;
    const done = events.find((e) => e.ev === "done")?.data ?? null;
    const err = events.find((e) => e.ev === "error")?.data ?? null;
    if (meta?.sessionId) sessionIds.push(meta.sessionId);

    const label = `${c.shouldLoad ? "期望加载" : "期望不加载"}「${c.message}」`;
    if (err) {
      ok(label, false, `error: ${err.message}`);
      continue;
    }
    const skills = Array.isArray(done?.skills) ? done.skills : [];
    if (c.shouldLoad) {
      loadTotal += 1;
      const hit = skills.includes(c.expect);
      if (hit) loadHit += 1;
      ok(`${label} → ${c.expect}`, hit, `done.skills=${JSON.stringify(skills)}`);
    } else {
      falseTotal += 1;
      const clean = skills.length === 0;
      if (clean) passed += 1;
      else {
        falseLoad += 1;
        failed += 1;
        failures.push(`${label} — 误加载: ${JSON.stringify(skills)}`);
        console.log(`  NG ${label} — 误加载: ${JSON.stringify(skills)}`);
      }
    }
  }

  const loadRate = loadTotal ? loadHit / loadTotal : 1;
  const falseRate = falseTotal ? falseLoad / falseTotal : 0;
  console.log(
    `\n加载率（明确命中）：${loadHit}/${loadTotal} = ${(loadRate * 100).toFixed(0)}%（门槛 ≥${THRESHOLD_LOAD * 100}%）`,
  );
  console.log(
    `误加载率（明确无关）：${falseLoad}/${falseTotal} = ${(falseRate * 100).toFixed(0)}%（门槛 ≤${THRESHOLD_FALSE * 100}%）`,
  );
  console.log(`\n== 逐条结果：${passed} 通过 / ${failed} 失败 ==`);
  if (failures.length) {
    console.log("\n失败项：");
    for (const f of failures) console.log(`  - ${f}`);
  }
  const gateOk = loadRate >= THRESHOLD_LOAD && falseRate <= THRESHOLD_FALSE;
  console.log(gateOk ? "\n✅ 达到验收门槛（不达标则按 OPT-1 退 hybrid 档）" : "\n❌ 未达验收门槛（按 OPT-1 退 hybrid 档）");

  for (const sid of sessionIds) {
    await fetch(`${BASE}/api/chat/sessions/${sid}`, { method: "DELETE" }).catch(() => {});
  }
  process.exit(gateOk && failed === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error("评估执行异常：", e);
  process.exit(1);
});
