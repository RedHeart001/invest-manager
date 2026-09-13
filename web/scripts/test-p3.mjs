// P3 验收测试（对齐 PLAN「验证方式 P3」+ 增补，双服务需已启动）
//  1. digest 落库与字段完整性（含降级标注 engine/newsSource/degraded/note）
//  2. SSE 实时推送链路（订阅 → ingest → 收到事件）
//  3. Dashboard SSR（卡片、相关产品链接、深度解读占位、降级标注）
//  4. 调度状态（盘前/盘后任务 + 启动补跑结果）
//  5. R12 降级标注（新闻源与结构化引擎显式说明）
// 测试会写入标题以【测试】开头的合成 digest，完成后清理。

import { PrismaClient } from "@prisma/client";

const BASE = process.env.TEST_BASE ?? "http://localhost:3000";
const DATA = process.env.TEST_DATA ?? "http://localhost:8000";
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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getJson(url, timeoutMs = 60_000) {
  const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  const body = await res.json().catch(() => ({}));
  return { status: res.status, body };
}

function today() {
  return new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 10);
}

async function main() {
  console.log(`\n== P3 验收：BFF=${BASE} data-service=${DATA}\n`);

  // ---------- 1. digest 落库与字段 ----------
  console.log("[1] digest 落库与字段完整性");
  {
    const { status, body } = await getJson(`${BASE}/api/hotspots?limit=30`);
    ok("列表 API 200", status === 200, `status=${status}`);
    const rows = body.rows ?? [];
    ok("存在 digest 数据（今日或最近日期）", rows.length > 0, `n=${rows.length}`);
    if (rows.length > 0) {
      const r = rows[0];
      ok(
        "字段完整（title/summary/boardTags/related/degraded/engine/newsSource）",
        typeof r.title === "string" &&
          Array.isArray(r.boardTags) &&
          Array.isArray(r.related) &&
          typeof r.degraded === "boolean" &&
          "engine" in r &&
          "newsSource" in r,
      );
      ok("相关产品结构含 type/code/name", rows.some((x) => (x.related ?? []).length > 0 && x.related.every((p) => p.type && p.code && p.name)) || (r.related ?? []).length === 0);
    }
    const date = body.date;
    ok("日期为合法 ISO 日期", /^\d{4}-\d{2}-\d{2}$/.test(date ?? ""), String(date));
  }

  // ---------- 2. R12 降级标注 ----------
  console.log("[2] R12/R10 降级标注（新闻源 + 引擎 + note）");
  {
    const { body } = await getJson(`${BASE}/api/hotspots?limit=10`);
    const rows = body.rows ?? [];
    const degradedRows = rows.filter((r) => r.degraded);
    // 断言不预设环境（2026-09-13 code review）：Tavily/LLM 均已配置时管线不降级属正常，
    // 正确语义是"降级行必须带 note，非降级行必须带来源"——两者皆合格。
    ok(
      "R10 显式标注（降级带 note / 正常带来源）",
      rows.length === 0 ||
        degradedRows.every((r) => typeof r.note === "string" && r.note.length > 0) &&
          rows.filter((r) => !r.degraded).every((r) => Boolean(r.newsSource || r.engine)),
      `rows=${rows.length} degraded=${degradedRows.length}`,
    );
    if (rows.length > 0) {
      ok(
        "新闻源标注合法（R12：tavily/cls/eastmoney-news/none）",
        rows.every((r) => ["cls", "eastmoney-news", "none", "tavily", null].includes(r.newsSource ?? null)),
        rows.map((r) => r.newsSource).join(","),
      );
      ok(
        "结构化引擎标注合法（llm/keyword/null）",
        rows.every((r) => ["llm", "keyword", null].includes(r.engine ?? null)),
        rows.map((r) => r.engine).join(","),
      );
    }
  }

  // ---------- 3. SSE 实时推送 ----------
  console.log("[3] SSE 实时推送链路");
  {
    const ctrl = new AbortController();
    const res = await fetch(`${BASE}/api/hotspots/stream`, { signal: ctrl.signal });
    ok("SSE 端点 200 + text/event-stream", res.status === 200 && String(res.headers.get("content-type")).includes("text/event-stream"), `status=${res.status} ct=${res.headers.get("content-type")}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // 修复（2026-09-13）：原实现每轮新建 read() 并在 race 失败后丢弃 pending 结果
    // → 并发 read 竞争同一 stream，事件可能被丢弃（flaky）。改为始终保持唯一 pending read。
    const readUntil = async (predicate, timeoutMs = 30000) => {
      const deadline = Date.now() + timeoutMs;
      let pending = null;
      while (Date.now() < deadline) {
        if (!pending) pending = reader.read();
        const winner = await Promise.race([
          pending.then((r) => ({ r })),
          sleep(300).then(() => null),
        ]);
        if (winner) {
          pending = null;
          const { value, done } = winner.r;
          if (value) buffer += decoder.decode(value, { stream: true });
          if (done) return predicate(buffer);
        }
        if (predicate(buffer)) return true;
      }
      return false;
    };

    const gotHello = await readUntil((b) => b.includes("event: hello"));
    ok("收到 hello 事件", gotHello);

    const testTitle = `【测试】SSE 链路验证 ${Date.now()}`;
    const ingestRes = await fetch(`${BASE}/api/hotspots/ingest`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // 容器环境 INGEST_TOKEN 为必填（compose 用 ${VAR:?} 强制），本地无则跳过鉴权
        ...(process.env.INGEST_TOKEN ? { "x-ingest-token": process.env.INGEST_TOKEN } : {}),
      },
      body: JSON.stringify({
        date: today(),
        trigger: "test-p3",
        engine: "keyword",
        newsSource: "cls",
        degraded: true,
        note: "测试数据（test-p3 自动生成，完成后清理）",
        items: [
          {
            title: testTitle,
            summary: "SSE 链路验证用合成条目",
            boardTags: ["人工智能"],
            sourceUrls: [],
            relatedCodes: [{ type: "stock", code: "600519", name: "贵州茅台", board: "人工智能" }],
          },
        ],
      }),
    });
    const ingestBody = await ingestRes.json();
    ok("ingest 落库成功", ingestRes.status === 200 && ingestBody.inserted === 1, JSON.stringify(ingestBody).slice(0, 120));

    const gotDigest = await readUntil((b) => b.includes("event: digest") && b.includes(testTitle), 30000);
    ok("SSE 收到 digest 事件且含新卡片", gotDigest);
    ctrl.abort();

    const cleanup = await prisma.hotspotDigest.deleteMany({
      where: { title: { startsWith: "【测试】" } },
    });
    ok("测试数据清理", cleanup.count >= 1, `deleted=${cleanup.count}`);
  }

  // ---------- 4. Dashboard SSR ----------
  console.log("[4] Dashboard SSR（/）");
  {
    const res = await fetch(`${BASE}/`, { signal: AbortSignal.timeout(60000) });
    const html = await res.text();
    ok("HTTP 200", res.status === 200, `status=${res.status}`);
    ok("标题与说明", html.includes("市场热点") && html.includes("板块成分映射"));
    ok("SSE 连接状态占位", html.includes("实时推送") || html.includes("自动重连中"));
    ok("手动触发按钮", html.includes("立即抓取热点"));
    // P5 落地后占位已升级为正式"深度解读"入口（2026-09-13 更新过时断言）
    ok("深度解读入口（P5 已交付）", html.includes("深度解读"));
    ok("自动任务时间说明", html.includes("08:30") && html.includes("16:30"));
    ok("免责声明", html.includes("不构成投资建议"));
    const hasCards = html.includes("相关产品") || html.includes("暂无热点数据");
    ok("卡片流或空态其一", hasCards);
  }

  // ---------- 5. 调度状态（含启动补跑） ----------
  console.log("[5] 调度状态与启动补跑");
  {
    // M4：手动触发改为异步——POST 立即返回 accepted，轮询直至完成
    const runRes = await fetch(`${DATA}/hotspots/run?trigger=test-p3`, { method: "POST" });
    const runBody = await runRes.json();
    ok(
      "run 立即返回（accepted 或 already-running）",
      runRes.status === 200 &&
        (runBody.accepted === true ||
          (runBody.accepted === false && String(runBody.note ?? "").includes("already running"))),
      JSON.stringify(runBody).slice(0, 120),
    );
    const pollDeadline = Date.now() + 240_000;
    let pollBody = null;
    while (Date.now() < pollDeadline) {
      await sleep(3000);
      pollBody = await (await getJson(`${DATA}/hotspots/status`)).body;
      if (pollBody.running === false && (pollBody.runs ?? 0) > 0) break;
    }

    const { status, body } = await getJson(`${DATA}/hotspots/status`);
    ok("status 200", status === 200, `status=${status}`);
    ok("盘前/盘后两个任务", (body.jobs ?? []).length === 2, JSON.stringify(body.jobs ?? []).slice(0, 160));
    ok("时区 Asia/Shanghai", body.timezone === "Asia/Shanghai", String(body.timezone));
    ok("已有执行记录（启动补跑/manual）", (body.runs ?? 0) > 0, `runs=${body.runs}`);
    const lr = body.lastResult ?? {};
    ok(
      "最近一次执行含来源/引擎/降级信息",
      "newsSource" in lr && "engine" in lr && "degraded" in lr,
      JSON.stringify(lr).slice(0, 160),
    );
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
