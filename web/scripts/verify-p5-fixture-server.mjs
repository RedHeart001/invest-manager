// P5 冷启动受控档的本地 DS / OpenAI 兼容 LLM 替身。
// 只能由 verify-isolated.mjs --p5-cold 启动；不采集行情、不生成真实研报。
import { appendFileSync } from "node:fs";
import { createServer } from "node:http";

const enabled = process.env.VERIFY_P5_COLD_FIXTURE === "1" && process.env.VERIFY_FIXTURE_SERVER === "1";
if (!enabled) throw new Error("受控替身缺少双显式开关，拒绝启动");
const dsPort = Number(process.env.VERIFY_DS_PORT);
const llmPort = Number(process.env.VERIFY_LLM_PORT);
const web = new URL(process.env.WEB_BASE_URL ?? "");
const auditPath = process.env.VERIFY_FIXTURE_AUDIT;
const fixtureKey = process.env.VERIFY_FIXTURE_KEY;
if (!auditPath || !fixtureKey || !dsPort || !llmPort || dsPort === llmPort) throw new Error("受控替身配置不完整");
if (web.protocol !== "http:" || web.hostname !== "127.0.0.1") throw new Error("受控回调只允许回环 Web");

const counts = { quote: 0, kline: 0, news: 0, researchStart: 0, ingestCallback: 0, llm: 0 };
function audit(kind, req, extra = {}) {
  appendFileSync(auditPath, `${JSON.stringify({ kind, method: req.method, path: req.url, ...extra })}\n`);
}
function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}
async function body(req) {
  let text = "";
  for await (const chunk of req) {
    text += chunk;
    if (text.length > 100_000) throw new Error("fixture request too large");
  }
  return JSON.parse(text || "{}");
}
function today() {
  return new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 10);
}
async function ingest(req, input) {
  const payload = {
    type: String(input.type ?? "stock"),
    code: String(input.code ?? ""),
    date: today(),
    report: {
      ok: true,
      rating: "中性",
      summary: "这是 P5 空表冷启动受控档的合成研报，只验证任务、回调与页面契约，不构成投资建议。",
      analysts: [],
      debate: { bull: [], bear: [] },
      risk: ["受控 fixture，未采集真实数据"],
      meta: { llmCalls: 0, engine: "isolated-fixture", sources: ["isolated-fixture"], asOf: today(), degraded: true, note: "受控合成研报" },
    },
  };
  const res = await fetch(`${web.origin}/api/research/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-ingest-token": process.env.INGEST_TOKEN ?? "" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(15_000),
  });
  counts.ingestCallback += 1;
  audit("ingest-callback", req, { code: payload.code, status: res.status });
  if (!res.ok) throw new Error(`合成回调被拒：HTTP ${res.status}`);
}

const ds = createServer((req, res) => {
  void (async () => {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    if (req.method === "GET" && url.pathname === "/health") return json(res, 200, { status: "ok", fixture: true });
    if (req.method === "GET" && url.pathname === "/quote") {
      counts.quote += 1;
      audit("quote", req);
      return json(res, 200, { type: url.searchParams.get("type"), code: url.searchParams.get("code"), name: "受控标的", price: 1, changePct: 0, currency: "CNY", timestamp: `${today()}T00:00:00+08:00`, source: "isolated-fixture" });
    }
    if (req.method === "GET" && url.pathname === "/kline") {
      counts.kline += 1;
      audit("kline", req);
      return json(res, 200, { type: url.searchParams.get("type"), code: url.searchParams.get("code"), interval: "1d", valueOnly: false, candles: [], source: "isolated-fixture", note: "P5 受控空行情" });
    }
    if (req.method === "GET" && url.pathname === "/news") {
      counts.news += 1;
      audit("news", req);
      return json(res, 200, { code: url.searchParams.get("code"), items: [], degraded: true, note: "P5 受控空新闻", source: "isolated-fixture" });
    }
    if (req.method === "POST" && url.pathname === "/research/start") {
      const input = await body(req);
      if (!input.code || !input.type) return json(res, 400, { detail: "type/code is required" });
      counts.researchStart += 1;
      audit("research-start", req, { type: input.type, code: input.code });
      // 等 BFF 先创建 running 行，再回调；避免与 upsert 竞争。
      setTimeout(() => {
        ingest(req, input).catch((error) => console.error(`[p5-fixture] ${error instanceof Error ? error.message : error}`));
      }, 100);
      return json(res, 200, { taskId: `fixture-${counts.researchStart}` });
    }
    audit("unknown-ds", req);
    return json(res, 404, { detail: "not implemented by isolated fixture" });
  })().catch((error) => {
    console.error(`[p5-fixture] DS error: ${error instanceof Error ? error.stack : error}`);
    if (!res.headersSent) json(res, 500, { detail: "isolated fixture error" });
    else res.end();
  });
});

const llm = createServer((req, res) => {
  void (async () => {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    if (req.method !== "POST" || url.pathname !== "/chat/completions") {
      audit("unknown-llm", req);
      return json(res, 404, { error: { message: "not implemented by isolated fixture" } });
    }
    if (req.headers.authorization !== `Bearer ${fixtureKey}`) return json(res, 401, { error: { message: "invalid isolated fixture key" } });
    const input = await body(req);
    if (input.model !== "isolated-fixture" || input.stream !== true) return json(res, 400, { error: { message: "unexpected isolated LLM request" } });
    counts.llm += 1;
    audit("llm", req, { messages: Array.isArray(input.messages) ? input.messages.length : 0 });
    res.writeHead(200, { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache" });
    res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: "受控冷启动对话响应，不调用真实模型。" } }] })}\n\n`);
    res.end("data: [DONE]\n\n");
  })().catch((error) => {
    console.error(`[p5-fixture] LLM error: ${error instanceof Error ? error.stack : error}`);
    if (!res.headersSent) json(res, 500, { error: { message: "isolated fixture error" } });
    else res.end();
  });
});

function listen(server, port, name) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      console.log(`[p5-fixture] ${name} listening on 127.0.0.1:${port}`);
      resolve();
    });
  });
}
await listen(ds, dsPort, "DS");
await listen(llm, llmPort, "LLM");
