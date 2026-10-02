// P3 验收测试（对齐 PLAN「验证方式 P3」+ 增补，双服务需已启动）
//  1. digest 落库与字段完整性（含降级标注 engine/newsSource/degraded/note）
//  2. SSE 实时推送链路（订阅 → ingest → 收到事件）
//  3. Dashboard SSR（卡片、相关产品链接、去分析入口、降级标注）
//  4. 调度状态（盘前/盘后任务 + 启动补跑结果）
//  5. R12 降级标注（新闻源与结构化引擎显式说明）
// 测试会写入标题以【测试】开头的合成 digest，完成后清理。

import { PrismaClient } from "@prisma/client";

import { INGEST_TOKEN } from "./ingest-token.mjs";

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
        // 容器环境 INGEST_TOKEN 为必填（compose 用 ${VAR:?} 强制），本地从 web/.env 取
        ...(INGEST_TOKEN ? { "x-ingest-token": INGEST_TOKEN } : {}),
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

    // 刀 2（#22(e)）：CR8-1 把三类成因拆开后，「② LLM/引擎退化」只在页头显示一次小字
    // （`产出说明：…`）。这条展示位此前**零断言**——10-01 之所以证明不了它，是因为当天
    // 批次全部 degraded=0，"不显示"是正确行为却也是无证据。这里刚好手上有合成行
    // （上面 ingest 的那条就是 degraded:true + note），于是可以正面证明"能显示"。
    {
      const bannerRes = await fetch(`${BASE}/`, { signal: AbortSignal.timeout(60000) });
      const bannerHtml = await bannerRes.text();
      ok(
        "刀2：有 degraded 行时页头出现「产出说明」（CR8-1 ② 的唯一出口）",
        bannerHtml.includes("产出说明"),
        `status=${bannerRes.status} 命中=${bannerHtml.includes("产出说明")}`,
      );
      ok(
        "刀2：产出说明里带上 note 原文（R16：降级要能被人看见，不是只给个布尔）",
        bannerHtml.includes("测试数据（test-p3 自动生成，完成后清理）"),
        "note 文案未出现在页头",
      );
    }

    const cleanup = await prisma.hotspotDigest.deleteMany({
      where: { title: { startsWith: "【测试】" } },
    });
    ok("测试数据清理", cleanup.count >= 1, `deleted=${cleanup.count}`);

    // 🔁 反向（成对，C34）：合成行删掉之后，横幅的出现与否**必须**与"最新批次里还有没有
    // degraded 行"严格一致——既证明它不是常驻假字，也证明它没有被逐卡复制回去。
    {
      const latest = await prisma.hotspotDigest.findFirst({
        orderBy: { date: "desc" },
        select: { date: true },
      });
      const degLeft = latest
        ? await prisma.hotspotDigest.count({ where: { date: latest.date, degraded: true } })
        : 0;
      const afterRes = await fetch(`${BASE}/`, { signal: AbortSignal.timeout(60000) });
      const afterHtml = await afterRes.text();
      ok(
        `🔁 刀2 反向：横幅出现 ⇔ 最新批次有 degraded 行（当前 degraded=${degLeft}）`,
        afterHtml.includes("产出说明") === (degLeft > 0),
        `banner=${afterHtml.includes("产出说明")} degradedLeft=${degLeft}`,
      );
      ok("🔁 刀2 反向：逐卡「降级产出」仍不再出现（清理后没被打回原形）",
         !afterHtml.includes("降级产出"));
    }
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
    // CR8-2（2026-09-30）：「深度解读」已改名「去分析 <标的>」（原名名不副实——它只是
    // 跳 related[0] 的 #research 锚点，不触发分析）。断言锁步改，否则改名会被读成回归。
    ok("去分析入口（CR8-2 改名后）", html.includes("去分析"));
    ok("自动任务时间说明", html.includes("08:30") && html.includes("16:30"));
    ok("免责声明", html.includes("不构成投资建议"));
    const hasCards = html.includes("相关产品") || html.includes("暂无热点数据");
    ok("卡片流或空态其一", hasCards);
    // 批次二（2026-10-01）：CR8-1 逐卡「降级产出」下线（三类成因曾被 OR 成一条并
    // 复制到每张卡）；CR8-3 来源链接改「相关文章」独立成行、标题由 ds 透传。
    ok("CR8-1：逐卡「降级产出」横幅不再出现", !html.includes("降级产出"));
    const page = await getJson(`${BASE}/api/hotspots?limit=30`);
    const prows = page.body.rows ?? [];
    const withUrls = prows.filter((r) => (r.sourceUrls ?? []).length > 0);
    ok(
      "CR8-3：有来源链接时渲染「相关文章」区（不预设环境）",
      withUrls.length === 0 || html.includes("相关文章"),
      `rows=${prows.length} withUrls=${withUrls.length}`,
    );
    ok(
      "CR8-3：读侧归一化生效（存量裸字符串行也拿到 {url,title}）",
      prows.every((r) =>
        (r.sourceUrls ?? []).every((s) => s && typeof s === "object" && "url" in s && "title" in s),
      ),
      JSON.stringify(prows[0]?.sourceUrls ?? []).slice(0, 90),
    );
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
