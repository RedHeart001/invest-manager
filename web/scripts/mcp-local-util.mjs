#!/usr/bin/env node
// 本地 MCP server（stdio，JSON-RPC 2.0 换行分隔帧）
//
// 用途：① 让 Tool Gateway 的 stdio 传输在不依赖外网/第三方服务的情况下可端到端验证；
//       ② 提供一个对金融 Agent 真实有用的小工具（当前北京时间 + A股交易时段判断，
//          避免在非交易时段把行情数据误读为"实时")。
//
// 协议实现范围：initialize / notifications/initialized / tools/list / tools/call / ping

import readline from "node:readline";

const PROTOCOL = "2024-11-05";

const TOOLS = [
  {
    name: "local_now",
    description:
      "获取当前北京时间（Asia/Shanghai）并判断是否处于 A 股交易时段，用于给行情数据标注正确时点",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
];

function shanghaiNow() {
  const fmt = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    weekday: "short",
    hour12: false,
  });
  const parts = Object.fromEntries(fmt.formatToParts(new Date()).map((p) => [p.type, p.value]));
  const hhmm = `${parts.hour}:${parts.minute}`;
  const weekday = parts.weekday ?? "";
  const isWeekday = !weekday.includes("六") && !weekday.includes("日");
  const inSession = hhmm >= "09:30" && hhmm <= "15:00";
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${hhmm}:${parts.second}`,
    weekday,
    isTradingDay: isWeekday,
    isTradingSession: isWeekday && inSession,
    timezone: "Asia/Shanghai",
  };
}

function callTool(name) {
  if (name !== "local_now") return { isError: true, text: `未知工具：${name}` };
  const now = shanghaiNow();
  const state = now.isTradingSession ? "交易时段内" : now.isTradingDay ? "非交易时段" : "非交易日";
  return {
    isError: false,
    text: `北京时间 ${now.date} ${now.time}（${now.weekday}，${state}）。行情数据请以此时间点为基准标注。`,
  };
}

const send = (obj) => process.stdout.write(`${JSON.stringify(obj)}\n`);

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  const text = line.trim();
  if (!text) return;
  let msg;
  try {
    msg = JSON.parse(text);
  } catch {
    return;
  }
  const { id, method, params } = msg;
  const reply = (result) => id !== undefined && send({ jsonrpc: "2.0", id, result });
  const fail = (message) =>
    id !== undefined && send({ jsonrpc: "2.0", id, error: { code: -32603, message } });

  switch (method) {
    case "initialize":
      reply({
        protocolVersion: params?.protocolVersion ?? PROTOCOL,
        capabilities: { tools: {} },
        serverInfo: { name: "invest-manager-local-util", version: "0.1.0" },
      });
      break;
    case "notifications/initialized":
      break; // 通知无响应
    case "ping":
      reply({});
      break;
    case "tools/list":
      reply({ tools: TOOLS });
      break;
    case "tools/call": {
      const r = callTool(params?.name);
      reply({ content: [{ type: "text", text: r.text }], isError: r.isError });
      break;
    }
    default:
      fail(`method not found: ${method}`);
  }
});
