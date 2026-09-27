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

// CR9-38（2026-09-27）：`res.json()` 在 dev 服务返回 HTML 时抛 `Unexpected token '<'`，
// 套件**没打印汇总行就崩**，verify-all 只能按 CR9-25 记 `0/19`（一个断言没跑完却像跑完了）。
// 统一走 jsonOf：非 JSON 一律带状态码与响应前缀显式失败，让"环境坏了"和"功能坏了"长得不一样。
async function jsonOf(res, what) {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(
      `${what}: 期望 JSON 但拿到 status=${res.status} content-type=${res.headers.get("content-type")} ` +
        `body=${text.slice(0, 120).replace(/\s+/g, " ")}`,
    );
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
    const body = await jsonOf(res, "POST /api/chat/sessions（创建）");
    sid = body.id ?? "";
    ok("创建会话", res.status === 200 && sid.length > 0, JSON.stringify(body).slice(0, 100));

    const list = await jsonOf(await fetch(`${BASE}/api/chat/sessions`), "GET /api/chat/sessions（列表）");
    ok("列表包含新会话", (list.sessions ?? []).some((s) => s.id === sid));

    const put = await fetch(`${BASE}/api/chat/sessions`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: sid, role: "user", content: "测试消息" }),
    });
    ok("追加消息", put.status === 200);

    const detail = await jsonOf(
      await fetch(`${BASE}/api/chat/sessions/${sid}`),
      "GET /api/chat/sessions/:id（详情）",
    );
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

    const detail = await jsonOf(
      await fetch(`${BASE}/api/chat/sessions/${sid}`),
      "GET /api/chat/sessions/:id（流式后回读）",
    );
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
    const mkBody = await jsonOf(mk, "POST /api/chat/sessions（多轮会话）");
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
      const events = []; // CR9-38：断言要看事件流本身（有哪些事件、工具入参是什么）
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
          // 帧内容不保证是完整 JSON（C3：LLM 流的尾帧常无换行结尾），解析不了就留空对象，
          // 但事件名照常记账——CR9-38 的断言要看的是"有哪些事件、工具入参是什么"。
          let data = {};
          try {
            data = JSON.parse(dataRaw) ?? {};
          } catch {
            /* 忽略坏帧 */
          }
          events.push({ ev, data });
          if (ev === "delta") text += String(data.content ?? "");
          if (ev === "error" || ev === "done") terminated = true;
        }
      }
      return { text, events, status: res.status };
    };

    // CR9-38（2026-09-27）：原来两条断言是"回答里有没有 600519"“有没有'股票/stock'"——
    // 那是拿**模型措辞**当验收，同一轮改动下批次跑 18/19、单跑 3 次里 2 次 19/19，
    // 门禁在此条上没有判别力。改判结构化证据（PLAN P4 要的是多轮能接上，不是散文写法）：
    //   ① 两轮都必须真正走完（done 收尾、无 error、有正文）——第二轮走不完才是回归；
    //   ② 会话里必须攒出 user/assistant 交替四条，这是"它"能被消解的**输入契约**；
    //   ③ 指代是否消解对：模型若发起工具调用，`status` 事件里的 args 就是结构化答案
    //      （必须仍指向第一轮的主体）；没调工具时只断"正文可用"，不去猜它怎么写。
    const a = await readAll(await ask("贵州茅台的股票代码是什么？"));
    const b = await readAll(await ask("它属于哪个产品类型？"));
    const evNames = (x) => x.events.map((e) => e.ev);
    const turnDone = (x) => evNames(x).includes("done") && !evNames(x).includes("error");

    ok(
      "多轮：两轮各自走完（done 收尾、无 error、正文非空）",
      a.status === 200 && b.status === 200 && turnDone(a) && turnDone(b) && a.text.length > 0 && b.text.length > 0,
      `a=${a.status}/${turnDone(a)}/${a.text.length} b=${b.status}/${turnDone(b)}/${b.text.length}`,
    );

    const detail = await jsonOf(
      await fetch(`${BASE}/api/chat/sessions/${sid2}`),
      "GET /api/chat/sessions/:id（多轮历史）",
    );
    const msgs = detail.messages ?? [];
    const roles = msgs.map((m) => m.role);
    const u1 = roles.indexOf("user");
    const u2 = roles.indexOf("user", u1 + 1);
    const roundOneOutput = msgs.slice(u1 + 1, u2); // 第一轮的产出（assistant / tool 混排）
    const roundTwoAnswer = msgs.slice(u2 + 1);
    // 实测形态（09-27）：`user,assistant,tool,assistant,user,assistant` ——发起工具调用的那条
    // assistant 正文为空、内容在 tool 行里。所以判"落库了吗"不能按"每条都有正文"，
    // 只能按结构：第一轮有产出、第二轮有最终正文回答。
    ok(
      "多轮：第一轮产出已落库、第二轮提问在其后且有正文回答（指代消解的输入契约）",
      u1 >= 0 &&
        u2 > u1 &&
        roundOneOutput.length > 0 &&
        roundOneOutput.every((m) => m.role !== "user") &&
        roundTwoAnswer.some((m) => m.role === "assistant" && String(m.content ?? "").length > 0),
      `seq=${roles.join(",")} lens=${msgs.map((m) => String(m.content ?? "").length).join("/")}`,
    );

    const toolArgs = b.events
      .filter((e) => e.ev === "status")
      .map((e) => `${e.data.name ?? "?"} ${JSON.stringify(e.data.args ?? {})}`);
    if (toolArgs.length > 0) {
      ok(
        "多轮🔧：第二轮的工具入参仍指向第一轮主体（600519/茅台）",
        /600519|茅台/.test(toolArgs.join(" ")),
        toolArgs.join(" | ").slice(0, 160),
      );
    } else {
      ok(
        "多轮（本轮无工具调用）：第二轮直接给出可用正文",
        b.text.trim().length >= 10,
        `len=${b.text.trim().length} ${b.text.slice(0, 60)}`,
      );
    }

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
