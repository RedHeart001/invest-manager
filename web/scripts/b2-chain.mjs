// B2：P4 组合链验证——热点 + 相关基金/产品多工具调用（PLAN P4 验证方式）
const BASE = process.env.TEST_BASE ?? "http://localhost:3000";

let passed = 0;
let failed = 0;
const ok = (name, cond, detail = "") => {
  if (cond) {
    passed++;
    console.log(`  OK ${name}`);
  } else {
    failed++;
    failures.push(`${name}${detail ? ` — ${detail}` : ""}`);
    console.log(`  NG ${name}${detail ? ` — ${detail}` : ""}`);
  }
};
const failures = [];

const mk = await fetch(`${BASE}/api/chat/sessions`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ title: "【测试】组合链" }),
});
const sid = (await mk.json()).id;

const res = await fetch(`${BASE}/api/chat`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    sessionId: sid,
    message: "查一下最近的市场热点，然后帮我看看贵州茅台现在的行情怎么样",
  }),
});

const reader = res.body.getReader();
const decoder = new TextDecoder();
let buffer = "";
let pendingRead = null;
const events = [];
let deltaLen = 0;
const deadline = Date.now() + 180_000;

let pending = null;
const readChunk = async () => {
  if (!pending) pending = reader.read();
  const w = await Promise.race([
    pending.then((r) => ({ r })),
    new Promise((r) => setTimeout(() => r(null), 500)),
  ]);
  if (w) {
    pending = null;
    return w.r;
  }
  return null;
};

let terminated = false;
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
    } catch {}
    events.push({ ev, data });
    if (ev === "delta") deltaLen += String(data.content ?? "").length;
    if (ev === "done" || ev === "error") terminated = true;
  }
}

const byEv = (n) => events.filter((e) => e.ev === n);
const toolNames = byEv("status").map((e) => e.data.name);
ok("SSE 会话建立", byEv("meta").length > 0);
ok("发生多次工具调用（组合链）", toolNames.length >= 2, `tools=${toolNames.join(",")}`);
ok(
  "热点工具被调用",
  toolNames.includes("get_hotspots") || deltaLen > 50,
  `tools=${toolNames.join(",")}`,
);
ok(
  "行情工具被调用",
  toolNames.includes("get_quote") || toolNames.includes("get_kline"),
  `tools=${toolNames.join(",")}`,
);
ok("流式正文非空", deltaLen > 50, `deltaLen=${deltaLen}`);
ok("正常收尾", byEv("done").length > 0);
const text = byEv("delta")
  .map((e) => e.data.content ?? "")
  .join("");
ok("回答引用真实数据（数字/热点标题）", /\d{3,}|热点|行情/.test(text), text.slice(0, 150));

await fetch(`${BASE}/api/chat/sessions/${sid}`, { method: "DELETE" });
console.log(`\n== B2 结果：${passed} 通过 / ${failed} 失败 ==`);
if (failures.length) {
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
