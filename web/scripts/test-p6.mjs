// P6 验收（M7：Skills + MCP + Tool Gateway）
//  1. Tool Gateway 状态面板：三分命名空间（builtin/skill/mcp）/ 技能清单 / MCP 连接状态
//  2. 技能上下文经济：元信息常驻、正文仅命中注入、未命中不占上下文
//  3. /api/chat 的 meta 事件携带命中技能与工具总数（含 MCP 汇入）
//  4. 技能正文不通过接口泄漏
//  5. 页面回归：/chat SSR 正常（网关改动未破坏既有链路）
//
// 依赖：data-service(8000) + web(3000) 已启动

const BASE = process.env.TEST_BASE ?? "http://localhost:3000";

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

/** 读取 SSE，返回事件数组（事件未结束时仅退出内层，不丢 in-flight 数据） */
async function readSse(res, timeoutMs = 90_000) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const events = [];
  let terminated = false;
  const deadline = Date.now() + timeoutMs;
  let pendingRead = null;
  const readChunk = async () => {
    if (!pendingRead) pendingRead = reader.read();
    const winner = await Promise.race([
      pendingRead.then((r) => ({ r })),
      new Promise((r) => setTimeout(() => r(null), 500)),
    ]);
    if (winner) {
      pendingRead = null;
      return winner.r;
    }
    return null;
  };
  while (Date.now() < deadline && !terminated) {
    const rr = await readChunk();
    if (rr) {
      const { value, done } = rr;
      if (done) break;
      if (value) buffer += decoder.decode(value, { stream: true });
    }
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

async function chatMeta(message, sessionIds) {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  const events = await readSse(res);
  const meta = events.find((e) => e.ev === "meta")?.data ?? null;
  const done = events.find((e) => e.ev === "done")?.data ?? null;
  if (meta?.sessionId) sessionIds.push(meta.sessionId);
  return { meta, done, events };
}

async function main() {
  console.log(`\n== P6 验收（M7 Skills + MCP）：BFF=${BASE}\n`);
  const sessionIds = [];

  // ---------- 1. 状态面板 ----------
  console.log("[1] Tool Gateway 状态面板 /api/tools/status");
  let status = null;
  {
    const res = await fetch(`${BASE}/api/tools/status`);
    status = await res.json();
    ok("HTTP 200", res.status === 200, `status=${res.status}`);

    const ns = status.namespaces ?? {};
    ok("builtin 工具数 = 9（L1 7 + L2 2）", ns.builtin?.count === 9, `count=${ns.builtin?.count}`);
    ok(
      "builtin 含 P6 新增 get_fund_report",
      (ns.builtin?.tools ?? []).includes("get_fund_report"),
    );
    ok(
      "builtin 工具名无命名空间前缀（P4 兼容）",
      (ns.builtin?.tools ?? []).every((n) => !n.includes(":")),
      JSON.stringify(ns.builtin?.tools).slice(0, 120),
    );

    ok("skill 数 = 3", ns.skill?.count === 3, `count=${ns.skill?.count}`);
    ok(
      "首批技能清单正确",
      JSON.stringify(ns.skill?.skills) ===
        JSON.stringify(["fund-report-analysis", "hotspot-daily", "tech-indicators"]),
      JSON.stringify(ns.skill?.skills),
    );
    ok("技能正文 token 上限配置可见", ns.skill?.maxBodyChars > 0, `cap=${ns.skill?.maxBodyChars}`);
    ok("同时激活数上限配置可见", ns.skill?.maxActive > 0, `max=${ns.skill?.maxActive}`);
    ok(
      "技能路由模式可见（OPT-1：keyword/llm/hybrid）",
      ["keyword", "llm", "hybrid"].includes(ns.skill?.router),
      `router=${ns.skill?.router}`,
    );

    ok("mcp 命名空间存在", Boolean(ns.mcp));
    const servers = ns.mcp?.servers ?? [];
    ok("mcp 白名单 server 已声明", servers.length >= 1, JSON.stringify(servers).slice(0, 160));
    const local = servers.find((s) => s.name === "local-util");
    ok(
      "stdio server（local-util）已连接",
      local?.state === "connected",
      `state=${local?.state} reason=${local?.reason ?? ""}`,
    );
    ok("MCP 工具数 ≥1", (local?.tools ?? 0) >= 1, `tools=${local?.tools}`);

    ok(
      "技能正文未通过接口泄漏",
      !JSON.stringify(status).includes("硬性约束") && !JSON.stringify(status).includes("执行步骤"),
    );
  }

  // ---------- 2. 技能上下文经济 ----------
  // OPT-1（2026-09-22）：路由模式分档。keyword 档保持确定性断言；llm/hybrid 档命中
  // 与否由主 LLM 决定（行为评估移交 eval-skill-router.mjs），此处只断言结构。
  console.log("[2] 技能注入策略（元信息常驻 / 正文按需）");
  const routerMode = status.namespaces?.skill?.router ?? "keyword";
  console.log(`  路由模式：${routerMode}`);
  {
    const miss = await chatMeta("帮我算一下 1 加 1 等于几", sessionIds);
    ok("未命中技能：meta.skills 为空", Array.isArray(miss.meta?.skills) && miss.meta.skills.length === 0, JSON.stringify(miss.meta?.skills));
    ok(
      routerMode === "keyword" ? "meta.toolCount ≥ 10（9 内置 + MCP）" : "meta.toolCount ≥ 11（9 内置 + MCP + load_skill）",
      (miss.meta?.toolCount ?? 0) >= (routerMode === "keyword" ? 10 : 11),
      `toolCount=${miss.meta?.toolCount}`,
    );
    ok(
      "done.skills 为数组（实际激活汇报）",
      Array.isArray(miss.done?.skills),
      JSON.stringify(miss.done?.skills),
    );

    const hot = await chatMeta("今天市场热点有哪些？", sessionIds);
    const fund = await chatMeta("110022 这只基金的季报怎么看", sessionIds);
    const tech = await chatMeta("这票最近为什么涨", sessionIds);
    const multi = await chatMeta("热点日报 和 均线 还有 基金季报 一起看", sessionIds);

    if (routerMode === "keyword") {
      ok("命中热点技能", (hot.meta?.skills ?? []).includes("hotspot-daily"), JSON.stringify(hot.meta?.skills));
      ok("命中基金报告技能", (fund.meta?.skills ?? []).includes("fund-report-analysis"), JSON.stringify(fund.meta?.skills));
      ok("命中技术面技能", (tech.meta?.skills ?? []).includes("tech-indicators"), JSON.stringify(tech.meta?.skills));
      ok("同时激活数被限制（≤3）", (multi.meta?.skills ?? []).length <= 3, JSON.stringify(multi.meta?.skills));
    } else {
      // llm 档：构建期不再注入，meta.skills 恒为空；done.skills 由 loader 汇报实际加载
      ok("llm/hybrid 档：meta.skills 恒为空（正文注入已废除）", (hot.meta?.skills ?? []).length === 0, JSON.stringify(hot.meta?.skills));
      for (const [label, r] of [["热点", hot], ["基金", fund], ["技术面", tech]]) {
        ok(`${label}消息：done.skills 结构正确（是否真加载由 LLM 决定）`, Array.isArray(r.done?.skills), JSON.stringify(r.done?.skills));
      }
      ok("done.skills 不超过激活上限", (multi.done?.skills ?? []).length <= 3, JSON.stringify(multi.done?.skills));
    }
  }

  // ---------- 3. 页面回归 ----------
  console.log("[3] 页面回归");
  {
    const res = await fetch(`${BASE}/chat`, { signal: AbortSignal.timeout(60_000) });
    const html = await res.text();
    ok("/chat HTTP 200", res.status === 200, `status=${res.status}`);
    ok("页面要素完整", html.includes("智能助手") && html.includes("不构成投资建议"));
  }

  // ---------- 清理 ----------
  for (const sid of sessionIds) {
    await fetch(`${BASE}/api/chat/sessions/${sid}`, { method: "DELETE" }).catch(() => {});
  }

  console.log(`\n== 结果：${passed} 通过 / ${failed} 失败 ==`);
  if (failures.length) {
    console.log("\n失败项：");
    for (const f of failures) console.log(`  - ${f}`);
    process.exit(1);
  }
}

main().catch((e) => {
  console.error("测试执行异常：", e);
  process.exit(1);
});
