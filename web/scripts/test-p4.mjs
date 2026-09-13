// P4 部分验收（LLM 配置前的可验证范围；function calling 端到端待 LLM key 配置后补测）
//  1. 会话持久化：创建/列表/详情/追加消息/删除
//  2. /api/chat：LLM 未配置时 SSE 返回明确错误事件，且会话与消息已保存
//  3. /chat 页面 SSR：标题、输入框、免责声明、导航

import { PrismaClient } from "@prisma/client";

const BASE = process.env.TEST_BASE ?? "http://localhost:3000";
const prisma = new PrismaClient();

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

async function main() {
  console.log(`\n== P4 验收（部分）：BFF=${BASE}\n`);

  // ---------- 1. 会话持久化 ----------
  console.log("[1] 会话持久化");
  let sid = "";
  {
    const res = await fetch(`${BASE}/api/chat/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "【测试】P4 会话" }),
    });
    const body = await res.json();
    sid = body.id ?? "";
    ok("创建会话", res.status === 200 && sid.length > 0, JSON.stringify(body).slice(0, 100));

    const list = await (await fetch(`${BASE}/api/chat/sessions`)).json();
    ok("列表包含新会话", (list.sessions ?? []).some((s) => s.id === sid));

    const put = await fetch(`${BASE}/api/chat/sessions`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: sid, role: "user", content: "测试消息" }),
    });
    ok("追加消息", put.status === 200);

    const detail = await (await fetch(`${BASE}/api/chat/sessions/${sid}`)).json();
    ok("详情含消息", (detail.messages ?? []).some((m) => m.content === "测试消息"));
  }

  // ---------- 2. chat SSE（自适应：LLM 已配置 → function calling E2E；未配置 → 明确指引） ----------
  console.log("[2] /api/chat 流式端点（function calling 端到端）");
  {
    const res = await fetch(`${BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: sid, message: "贵州茅台现在多少钱？" }),
    });
    ok("SSE 200 + text/event-stream", res.status === 200 && String(res.headers.get("content-type")).includes("text/event-stream"), `status=${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const events = [];
    let deltaLen = 0;
    const deadline = Date.now() + 120_000;

    // 单一持续 read（race 超时不丢弃 in-flight 数据块）
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
      return null; // 超时但 read 仍在进行
    };

    parse_loop: while (Date.now() < deadline) {
      const rr = await readChunk();
      if (rr) {
        const { value, done } = rr;
        if (done) break;
        if (value) buffer += decoder.decode(value, { stream: true });
      }
      // 内层解析：数据不完整时仅退出内层（等下一个 chunk），不得跳出读取循环
      let terminated = false;
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
          /* 忽略 */
        }
        events.push({ ev, data });
        if (ev === "delta") deltaLen += String(data.content ?? "").length;
        if (ev === "done" || ev === "error") {
          terminated = true;
          break;
        }
      }
      if (terminated) break parse_loop;
    }
    const byEv = (name) => events.filter((e) => e.ev === name);
    const errEv = byEv("error")[0]?.data ?? null;

    if (errEv && errEv.code === "llm_not_configured") {
      ok("LLM 未配置 → 明确指引事件", String(errEv.message ?? "").includes("web/.env"));
      console.log("  （LLM 未配置，跳过 function calling E2E 断言）");
    } else {
      ok("收到 meta", byEv("meta").length > 0);
      ok("发生工具调用（status/tool_result）", byEv("status").length > 0 || byEv("tool_result").length > 0, `status=${byEv("status").length} toolResult=${byEv("tool_result").length}`);
      ok("收到流式正文（delta 非空）", deltaLen > 10, `deltaLen=${deltaLen}`);
      const toolErr = byEv("tool_result").filter((e) => e.data.ok === false);
      ok("工具执行全部成功（行情源可用）", toolErr.length === 0, JSON.stringify(toolErr).slice(0, 160));
      ok("正常 done 收尾", byEv("done").length > 0, `events=${events.map((e) => e.ev).join(",")}`);
      const assistantText = events.filter((e) => e.ev === "delta").map((e) => e.data.content ?? "").join("");
      ok("回答引用了真实数据（茅台/价格数字）", /茅台|\d{3,}/.test(assistantText), assistantText.slice(0, 120));
    }

    const detail = await (await fetch(`${BASE}/api/chat/sessions/${sid}`)).json();
    ok("用户消息已持久化", (detail.messages ?? []).some((m) => m.content === "贵州茅台现在多少钱？"));
  }

  // ---------- 3. /chat 页面 SSR ----------
  console.log("[3] /chat 页面 SSR");
  {
    const res = await fetch(`${BASE}/chat`, { signal: AbortSignal.timeout(60000) });
    const html = await res.text();
    ok("HTTP 200", res.status === 200, `status=${res.status}`);
    ok("标题与说明", html.includes("智能助手") && html.includes("不构成投资建议"));
    ok("输入框与发送", html.includes("输入问题") || html.includes("发送"));
    ok("新会话按钮", html.includes("新会话"));
  }

  // ---------- 清理 ----------
  if (sid) {
    await fetch(`${BASE}/api/chat/sessions/${sid}`, { method: "DELETE" });
    const check = await fetch(`${BASE}/api/chat/sessions/${sid}`);
    ok("删除会话", check.status === 404, `status=${check.status}`);
  }

  // ---------- 4. 多轮上下文记忆（同一会话指代消解） ----------
  console.log("[4] 多轮上下文（第二轮指代第一轮主体）");
  {
    // 新会话：第一轮问茅台，第二轮用"它"指代
    const mk = await fetch(`${BASE}/api/chat/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "【测试】多轮上下文" }),
    });
    const mkBody = await mk.json();
    const sid2 = mkBody.id;

    const ask = (msg) =>
      fetch(`${BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: sid2, message: msg }),
      });

    const readAll = async (res, timeoutMs = 90_000) => {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let text = "";
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
          if (ev === "delta") text += String((JSON.parse(dataRaw) ?? {}).content ?? "");
          if (ev === "error") terminated = true;
          if (ev === "done") terminated = true;
        }
      }
      return text;
    };

    const r1 = await ask("贵州茅台的股票代码是什么？");
    const t1 = await readAll(r1);
    ok("第一轮回答包含代码 600519", /600519/.test(t1), t1.slice(0, 80));

    const r2 = await ask("它属于哪个产品类型？");
    const t2 = await readAll(r2);
    ok("第二轮理解指代（回答股票/stock）", /股票|stock/i.test(t2), t2.slice(0, 80));

    await fetch(`${BASE}/api/chat/sessions/${sid2}`, { method: "DELETE" });
  }

  console.log(`\n== 结果：${passed} 通过 / ${failed} 失败 ==`);
  if (failures.length) {
    console.log("\n失败项：");
    for (const f of failures) console.log(`  - ${f}`);
    await prisma.$disconnect();
    process.exit(1);
  }
  await prisma.$disconnect();
}

main().catch(async (e) => {
  console.error("测试执行异常：", e);
  await prisma.$disconnect().catch(() => {});
  process.exit(1);
});
