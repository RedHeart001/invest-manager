// P6：MCP client 单测——真实 stdio 握手（本地 server）+ 失败降级 + 工具名规范化

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterAll, describe, expect, it } from "vitest";

import { callMcpTool, loadServerConfigs, mcpLlmTools, mcpStatus, stopAllMcp, toLlmToolName } from "./mcp";

const savedEnv = { ...process.env };
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "mcp-test-"));
const localServer = path.resolve(__dirname, "..", "scripts", "mcp-local-util.mjs");

function useConfig(servers: unknown[]) {
  const file = path.join(tmpDir, `mcp-${Math.random().toString(36).slice(2)}.json`);
  fs.writeFileSync(file, JSON.stringify({ servers }), "utf8");
  process.env.MCP_CONFIG = file;
}

afterAll(() => {
  stopAllMcp();
  fs.rmSync(tmpDir, { recursive: true, force: true });
  process.env = { ...savedEnv };
});

describe("工具名规范化", () => {
  it("mcp_<server>_<tool>，非法字符转下划线", () => {
    expect(toLlmToolName("tavily", "tavily-search")).toBe("mcp_tavily_tavily_search");
    expect(toLlmToolName("my.server", "a b/c")).toBe("mcp_my_server_a_b_c");
  });
});

describe("stdio 链路（本地 MCP server）", () => {
  it("握手成功 → 工具进入网关并可调用", async () => {
    useConfig([
      {
        name: "local-util-happy",
        transport: "stdio",
        command: process.execPath,
        args: [localServer],
        timeoutMs: 15000,
      },
    ]);

    const tools = await mcpLlmTools();
    expect(tools.map((t) => t.function.name)).toContain("mcp_local_util_happy_local_now");
    const def = tools.find((t) => t.function.name === "mcp_local_util_happy_local_now");
    expect(def?.function.description).toContain("[MCP:local-util-happy]");
    expect(def?.function.parameters).toMatchObject({ type: "object" });

    const res = await callMcpTool("mcp_local_util_happy_local_now", {});
    expect(res.ok).toBe(true);
    expect(res.summary).toContain("北京时间");

    const status = await mcpStatus();
    const entry = status.servers.find((s) => s.name === "local-util-happy");
    expect(entry?.state).toBe("connected");
    expect(entry?.tools).toBe(1);
  });

  it("并发请求共享同一连接过程（不重复 spawn）", async () => {
    useConfig([
      {
        name: "local-util-race",
        transport: "stdio",
        command: process.execPath,
        args: [localServer],
        timeoutMs: 15000,
      },
    ]);
    // 并发触发三次工具加载：并发竞态下若无 in-flight 去重会重复 spawn 子进程
    const [a, b, c] = await Promise.all([mcpLlmTools(), mcpLlmTools(), mcpLlmTools()]);
    const names = a.map((t) => t.function.name);
    expect(names).toEqual(["mcp_local_util_race_local_now"]);
    expect(b.map((t) => t.function.name)).toEqual(names);
    expect(c.map((t) => t.function.name)).toEqual(names);
    const status = await mcpStatus();
    expect(status.servers.find((s) => s.name === "local-util-race")?.state).toBe("connected");
  });

  it("调用未知 MCP 工具返回降级结果而非抛错", async () => {
    const res = await callMcpTool("mcp_local_util_happy_not_exist", {});
    expect(res.ok).toBe(false);
    expect(res.summary).toContain("未知 MCP 工具");
  });
});

describe("失败降级（不阻塞对话）", () => {
  it("server 启动失败 → state=degraded，无工具注入，不抛异常", async () => {
    useConfig([
      {
        name: "broken-server",
        transport: "stdio",
        command: process.execPath,
        args: [path.join(tmpDir, "not-exist-server.mjs")],
        timeoutMs: 5000,
      },
    ]);

    const tools = await mcpLlmTools(); // 不得抛错
    expect(tools.some((t) => t.function.name.includes("broken_server"))).toBe(false);

    const status = await mcpStatus();
    const entry = status.servers.find((s) => s.name === "broken-server");
    expect(entry?.state).toBe("degraded");
    expect(entry?.tools).toBe(0);
    expect(String(entry?.reason ?? "").length).toBeGreaterThan(0);
  });

  it("enabled=false 的 server 被跳过且标注 disabled", async () => {
    useConfig([
      {
        name: "disabled-server",
        transport: "stdio",
        command: process.execPath,
        args: [localServer],
        enabled: false,
      },
    ]);
    const tools = await mcpLlmTools();
    expect(tools.length).toBe(0);
    const status = await mcpStatus();
    expect(status.servers.find((s) => s.name === "disabled-server")?.state).toBe("disabled");
  });

  it("sse（旧传输）明确拒绝连接并降级", async () => {
    useConfig([{ name: "sse-server", transport: "sse", url: "http://127.0.0.1:9/mcp" }]);
    await mcpLlmTools();
    const status = await mcpStatus();
    const entry = status.servers.find((s) => s.name === "sse-server");
    expect(entry?.state).toBe("degraded");
    expect(String(entry?.reason ?? "")).toContain("sse");
  });
});

describe("探测短超时（M7 已知优化点 2，10-03 落地）", () => {
  // 探测上限只约束"面板让调用方等多久"，**不取消连接、不据此判降级**——
  // 判成 degraded 会吃 `RETRY_COOLDOWN_MS`（60s）冷却，等于把一个慢但可用的 server
  // 踢到半分钟没人理，比面板多等几秒糟得多。两条用例一起把这句话钉住。
  const PROBE_S = "0.2";

  it("server 挂起 ⇒ 面板在探测上限内返回，状态仍是 idle（没被误判成 degraded）", async () => {
    useConfig([
      { name: "probe-hang", transport: "http", url: "http://127.0.0.1:59999/mcp", timeoutMs: 1200 },
    ]);
    const real = globalThis.fetch;
    process.env.MCP_PROBE_TIMEOUT_S = PROBE_S;
    // 永不 resolve 的 fetch：传输层自己的 1200ms 都到不了（这里没有 signal 可 abort）
    globalThis.fetch = (() => new Promise(() => undefined)) as unknown as typeof fetch;
    const started = Date.now();
    let status: Awaited<ReturnType<typeof mcpStatus>>;
    try {
      status = await mcpStatus({ connect: true });
    } finally {
      globalThis.fetch = real;
      delete process.env.MCP_PROBE_TIMEOUT_S;
    }
    const elapsed = Date.now() - started;
    const entry = status.servers.find((s) => s.name === "probe-hang");
    expect(elapsed).toBeLessThan(1000); // ⇒ 返回不是因为等满了传输层超时
    expect(entry?.state).toBe("idle");
    expect(String(entry?.reason)).toContain("探测未在 0.2s 内返回");
    expect(status.probeTimeoutS).toBe(0.2);
    stopAllMcp(); // 收掉那条永不 resolve 的 in-flight，别留给后续用例
  });

  it("🔁 对照：同一探测上限下，及时应答的 server 照常 connected（不是把一切都判成超时）", async () => {
    useConfig([
      { name: "probe-fast", transport: "http", url: "http://127.0.0.1:59998/mcp", timeoutMs: 1200 },
    ]);
    const real = globalThis.fetch;
    process.env.MCP_PROBE_TIMEOUT_S = PROBE_S;
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ jsonrpc: "2.0", id: 1, result: { tools: [] } }), {
        headers: { "Content-Type": "application/json" },
      })) as unknown as typeof fetch;
    try {
      const status = await mcpStatus({ connect: true });
      const entry = status.servers.find((s) => s.name === "probe-fast");
      expect(entry?.state).toBe("connected");
      expect(entry?.reason).toBeUndefined();
    } finally {
      globalThis.fetch = real;
      delete process.env.MCP_PROBE_TIMEOUT_S;
      stopAllMcp();
    }
  });

  it("🔁 未探测（connect=false）⇒ 不吃探测预算，probeTimeoutS 显式为 null", async () => {
    useConfig([
      { name: "probe-plain", transport: "http", url: "http://127.0.0.1:59997/mcp", timeoutMs: 1200 },
    ]);
    const real = globalThis.fetch;
    // 一旦被调用就是回归：connect=false 不该发起任何探测请求
    let calls = 0;
    globalThis.fetch = (() => {
      calls += 1;
      return Promise.reject(new Error("不该出网"));
    }) as unknown as typeof fetch;
    try {
      const status = await mcpStatus();
      expect(calls).toBe(0);
      expect(status.probeTimeoutS).toBeNull();
      expect(status.servers.find((s) => s.name === "probe-plain")?.state).toBe("idle");
    } finally {
      globalThis.fetch = real;
    }
  });
});

describe("配置解析", () => {
  it("无 mcp.json / 解析失败 → 视为无第三方 server（空数组）", () => {
    process.env.MCP_CONFIG = path.join(tmpDir, "missing.json");
    expect(loadServerConfigs()).toEqual([]);
  });

  it("支持 ${ENV} 占位展开", () => {
    process.env.TEST_MCP_KEY = "secret-123";
    useConfig([
      {
        name: "env-server",
        transport: "stdio",
        command: "node",
        args: ["--version", "${TEST_MCP_KEY}"],
        env: { TOKEN: "${TEST_MCP_KEY}" },
      },
    ]);
    const cfg = loadServerConfigs()[0];
    expect(cfg.args).toEqual(["--version", "secret-123"]);
    expect(cfg.env?.TOKEN).toBe("secret-123");
  });

  it("enabledTools 白名单过滤生效", async () => {
    useConfig([
      {
        name: "filtered-server",
        transport: "stdio",
        command: process.execPath,
        args: [localServer],
        enabledTools: ["nonexistent"],
      },
    ]);
    const tools = await mcpLlmTools();
    expect(tools.length).toBe(0);
  });
});
