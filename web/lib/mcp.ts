// MCP client（PLAN M7 ②，P6 二轮补强）
//
// 设计要点（与 PLAN 定稿一致）：
// - 白名单制：只连接 mcp.json（env MCP_CONFIG 可覆盖）中声明的 server，**不自动安装**任何东西
// - MVP 以 **stdio** 传输为主（JSON-RPC 2.0，换行分隔帧）；HTTP（streamable）保留配置支持
// - 生命周期容错：连接/handshake/调用失败一律**降级为该源工具不可用**，绝不阻塞对话主流程
// - 工具以 `mcp_<server>_<tool>` 命名注入 Tool Gateway（对 LLM 透明，命名符合 function name 约束）

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import type { LlmToolDef } from "./llm";

export type McpServerStatus = {
  name: string;
  transport: string;
  state: "connected" | "degraded" | "disabled" | "idle";
  tools: number;
  reason?: string;
  configured: boolean;
};

export type McpToolBinding = {
  llmName: string;
  server: string;
  tool: string;
  description: string;
};

type RawTool = {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
};

type ServerCfg = {
  name: string;
  enabled?: boolean;
  /** MVP：stdio 为主（HTTP/streamable 已支持配置）；sse 为旧协议，不支持 */
  transport?: "stdio" | "http" | "sse";
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
  url?: string;
  headers?: Record<string, string>;
  timeoutMs?: number;
  /** 可选：只暴露指定工具（默认全部） */
  enabledTools?: string[];
};

const DEFAULT_TIMEOUT = Number(process.env.MCP_TIMEOUT_MS ?? 20000);
/** 失败后的重试冷却，避免 spawn 风暴 */
const RETRY_COOLDOWN_MS = Number(process.env.MCP_RETRY_COOLDOWN_MS ?? 60000);

export function mcpConfigPath(): string {
  const p = process.env.MCP_CONFIG?.trim();
  if (!p) return path.join(process.cwd(), "mcp.json");
  return path.isAbsolute(p) ? p : path.join(process.cwd(), p);
}

/** 支持 ${ENV_VAR} 占位（避免把密钥写进 mcp.json 提交到仓库） */
function expandEnv(value: string): string {
  return value.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (_, key: string) => process.env[key] ?? "");
}

function expandRecord(rec: Record<string, string> | undefined): Record<string, string> | undefined {
  if (!rec) return undefined;
  return Object.fromEntries(Object.entries(rec).map(([k, v]) => [k, expandEnv(String(v))]));
}

export function loadServerConfigs(): ServerCfg[] {
  try {
    const raw = fs.readFileSync(mcpConfigPath(), "utf8");
    const parsed = JSON.parse(raw) as { servers?: unknown };
    const list = Array.isArray(parsed.servers) ? parsed.servers : [];
    return list
      .filter((s): s is ServerCfg => Boolean(s) && typeof (s as ServerCfg).name === "string")
      .map((s) => ({
        ...s,
        name: s.name.trim(),
        args: (s.args ?? []).map(expandEnv),
        env: expandRecord(s.env),
        headers: expandRecord(s.headers),
      }));
  } catch {
    return []; // 无配置/解析失败 = 无第三方 server，属正常状态
  }
}

/** 把 MCP 工具名规范化为 LLM 可用的 function name */
export function toLlmToolName(server: string, tool: string): string {
  const clean = (s: string) => s.replace(/[^A-Za-z0-9_]/g, "_");
  const base = `mcp_${clean(server)}_${clean(tool)}`;
  // 代码审查修复：截断到 60 字符可能让两个不同工具撞名（executeAgentTool 会
  // 分派到错误的工具）→ 截断时附加短哈希保证唯一
  if (base.length <= 60) return base;
  let h = 0;
  for (const ch of base) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `${base.slice(0, 52)}_${h.toString(36).slice(0, 7)}`;
}

// ---------------- stdio 传输（JSON-RPC 2.0，换行分隔） ----------------

class StdioClient {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private buffer = "";
  private seq = 1;
  private pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void; timer: NodeJS.Timeout }>();
  private closed = false;

  constructor(private cfg: ServerCfg) {}

  get alive(): boolean {
    return Boolean(this.proc) && !this.closed;
  }

  async connect(): Promise<void> {
    if (this.alive) return;
    const command = this.cfg.command;
    if (!command) throw new Error("stdio server 缺少 command");
    const child = spawn(command, this.cfg.args ?? [], {
      cwd: this.cfg.cwd,
      env: { ...process.env, ...(this.cfg.env ?? {}) },
      // Windows 下 npx/npm 等是 .cmd 包装脚本，需要经 shell 解析；
      // 已是明确可执行文件（.exe/.cmd/.bat）时直连，避免 shell 重新解析参数
      shell: process.platform === "win32" && !/\.(exe|cmd|bat)$/i.test(command),
      stdio: ["pipe", "pipe", "pipe"],
    }) as ChildProcessWithoutNullStreams;

    this.proc = child;
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => this.onData(chunk));
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      console.warn(`[mcp:${this.cfg.name}] stderr: ${chunk.slice(0, 200)}`);
    });
    child.on("error", (e) => this.failAll(e instanceof Error ? e : new Error(String(e))));
    child.on("exit", (code) => {
      this.closed = true;
      this.failAll(new Error(`进程退出（code=${code}）`));
    });

    // CR4（2026-09-15 review）：握手失败会泄漏已 spawn 的子进程（每次冷却重试再
    // spawn 一个，长期累积孤儿进程）。initialize 失败时 kill 子进程再抛。
    try {
      await this.request("initialize", {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: { name: "invest-manager", version: "0.6.0" },
      });
      this.notify("notifications/initialized", {});
    } catch (e) {
      this.stop();
      throw e;
    }
  }

  private onData(chunk: string): void {
    this.buffer += chunk;
    let idx: number;
    while ((idx = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, idx).trim();
      this.buffer = this.buffer.slice(idx + 1);
      if (!line) continue;
      let msg: { id?: number; result?: unknown; error?: { message?: string } };
      try {
        msg = JSON.parse(line);
      } catch {
        continue; // 非 JSON 行（日志等）
      }
      if (typeof msg.id !== "number") continue;
      const entry = this.pending.get(msg.id);
      if (!entry) continue;
      this.pending.delete(msg.id);
      clearTimeout(entry.timer);
      if (msg.error) entry.reject(new Error(msg.error.message ?? "MCP error"));
      else entry.resolve(msg.result);
    }
  }

  private failAll(e: Error): void {
    for (const [, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(e);
    }
    this.pending.clear();
  }

  private send(payload: Record<string, unknown>): void {
    if (!this.proc || this.closed) throw new Error("连接已关闭");
    this.proc.stdin.write(`${JSON.stringify(payload)}\n`);
  }

  private notify(method: string, params: Record<string, unknown>): void {
    try {
      this.send({ jsonrpc: "2.0", method, params });
    } catch {
      /* 通知失败不影响主流程 */
    }
  }

  request(method: string, params: Record<string, unknown>): Promise<unknown> {
    const id = this.seq++;
    const timeout = this.cfg.timeoutMs ?? DEFAULT_TIMEOUT;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`超时（${timeout}ms）：${method}`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.send({ jsonrpc: "2.0", id, method, params });
      } catch (e) {
        this.pending.delete(id);
        clearTimeout(timer);
        reject(e instanceof Error ? e : new Error(String(e)));
      }
    });
  }

  async listTools(): Promise<RawTool[]> {
    const res = (await this.request("tools/list", {})) as { tools?: RawTool[] };
    return res?.tools ?? [];
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<unknown> {
    return this.request("tools/call", { name, arguments: args });
  }

  stop(): void {
    this.closed = true;
    try {
      this.proc?.kill();
    } catch {
      /* ignore */
    }
    this.proc = null;
    this.failAll(new Error("连接已关闭"));
  }
}

// ---------------- HTTP（streamable）传输 ----------------

class HttpClient {
  private sessionId: string | null = null;

  constructor(private cfg: ServerCfg) {}

  private async rpc(method: string, params: Record<string, unknown>): Promise<unknown> {
    if (!this.cfg.url) throw new Error("http server 缺少 url");
    const res = await fetch(this.cfg.url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
        ...(this.sessionId ? { "Mcp-Session-Id": this.sessionId } : {}),
        ...(this.cfg.headers ?? {}),
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method, params }),
      signal: AbortSignal.timeout(this.cfg.timeoutMs ?? DEFAULT_TIMEOUT),
      cache: "no-store",
    });
    const sid = res.headers.get("mcp-session-id");
    if (sid) this.sessionId = sid;
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    // streamable-http 可能返回 SSE（data: {...}）或纯 JSON
    const line = text.split("\n").find((l) => l.startsWith("data:")) ?? text;
    const payload = JSON.parse(line.replace(/^data:\s*/, "")) as {
      result?: unknown;
      error?: { message?: string };
    };
    if (payload.error) throw new Error(payload.error.message ?? "MCP error");
    return payload.result;
  }

  async connect(): Promise<void> {
    await this.rpc("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "invest-manager", version: "0.6.0" },
    });
  }

  async listTools(): Promise<RawTool[]> {
    const res = (await this.rpc("tools/list", {})) as { tools?: RawTool[] };
    return res?.tools ?? [];
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<unknown> {
    return this.rpc("tools/call", { name, arguments: args });
  }

  stop(): void {
    /* 无长连接需要释放 */
  }
}

type AnyClient = StdioClient | HttpClient;

type ServerRuntime = {
  cfg: ServerCfg;
  client: AnyClient | null;
  /** 连接中的 in-flight Promise：并发请求共享同一连接过程，避免重复 spawn */
  connecting: Promise<AnyClient | null> | null;
  state: McpServerStatus["state"];
  reason?: string;
  lastAttempt: number;
  tools: RawTool[];
  /**
   * CR-12（本轮 code review）：停止代际。`stopAllMcp` 自增该值；进行中的
   * `ensureConnected` 完成时若发现代际已变，则丢弃结果并关掉刚建立的连接——
   * 否则"停止"后仍会把 client 写回并置 connected（复活已停止的 server）。
   */
  generation: number;
};

/**
 * 运行时注册表挂在 globalThis 上（Symbol.for 跨模块共享）：
 * Next.js dev 的热重载（HMR）会重建模块作用域，若存于模块级变量，
 * 每次 HMR 都会丢失连接状态并重复 spawn stdio 子进程 → 孤儿进程泄漏。
 * globalThis 上的注册表在 HMR 后仍然存活，连接与缓存得以复用。
 */
const RUNTIMES_KEY = Symbol.for("invest-manager.mcp.runtimes");
const runtimes: Map<string, ServerRuntime> =
  ((globalThis as Record<symbol, unknown>)[RUNTIMES_KEY] as Map<string, ServerRuntime> | undefined) ??
  (((globalThis as Record<symbol, unknown>)[RUNTIMES_KEY] = new Map<string, ServerRuntime>()) as Map<
    string,
    ServerRuntime
  >);

/** 进程退出时清理全部 stdio 子进程（同一进程只注册一次，防 HMR 重复挂载） */
const EXIT_HOOK_KEY = Symbol.for("invest-manager.mcp.exitHook");
if (!(globalThis as Record<symbol, unknown>)[EXIT_HOOK_KEY]) {
  (globalThis as Record<symbol, unknown>)[EXIT_HOOK_KEY] = true;
  process.once("exit", () => {
    for (const [, rt] of runtimes) {
      try {
        rt.client?.stop();
      } catch {
        /* 退出阶段尽力而为 */
      }
    }
  });
}

function runtimeFor(cfg: ServerCfg): ServerRuntime {
  const hit = runtimes.get(cfg.name);
  if (hit) {
    hit.cfg = cfg;
    if (cfg.enabled === false) {
      // CR4（P3）：禁用时不仅改状态，还要停掉已运行的子进程（此前继续空跑）
      if (hit.state !== "disabled") {
        hit.state = "disabled";
        hit.reason = "配置中 enabled=false";
      }
      if (hit.client) {
        try {
          hit.client.stop();
        } catch {
          /* 忽略停止失败 */
        }
        hit.client = null;
        hit.tools = [];
      }
    } else if (hit.state === "disabled") {
      // CR4（P3）：配置改回 enabled=true 时解除 disabled（此前永久停在 disabled，
      // 需重启 web 才生效）——回到 idle，由 ensureConnected 按需重连。
      hit.state = "idle";
      hit.reason = undefined;
    }
    return hit;
  }
  const fresh: ServerRuntime = {
    cfg,
    client: null,
    connecting: null,
    state: cfg.enabled === false ? "disabled" : "idle",
    reason: cfg.enabled === false ? "配置中 enabled=false" : undefined,
    lastAttempt: 0,
    tools: [],
    generation: 0,
  };
  runtimes.set(cfg.name, fresh);
  return fresh;
}

async function ensureConnected(rt: ServerRuntime): Promise<AnyClient | null> {
  // CR4（2026-09-15 review）：之前首行只判 `if (rt.client)`，不检查活性——
  // StdioClient 子进程意外退出后 rt.client 仍指向死连接、状态仍显示 connected，
  // 所有 mcp_* 工具永久"连接已关闭"。活着的判断：HttpClient 恒视为 alive；
  // StdioClient 看 alive getter（!closed && proc 存在）。
  if (rt.client) {
    if (rt.client instanceof HttpClient || rt.client["alive"]) return rt.client;
    // 进程已死：清理死引用，走下方重连流程
    try {
      rt.client.stop();
    } catch {
      /* 已死进程 stop 可失败，忽略 */
    }
    rt.client = null;
    rt.tools = [];
  }
  // 并发请求共享同一连接过程，避免并发 spawn 多个 stdio 子进程
  if (rt.connecting) return rt.connecting;
  if (rt.state === "disabled") return null;
  const now = Date.now();
  if (rt.state === "degraded" && now - rt.lastAttempt < RETRY_COOLDOWN_MS) return null;
  rt.lastAttempt = now;

  // 用持有者对象避免 async 函数体内自引用的 TDZ（TS 控制流分析不接受）
  const holder: { p: Promise<AnyClient | null> | null } = { p: null };
  const attempt = (async (): Promise<AnyClient | null> => {
    const transport = rt.cfg.transport ?? "stdio";
    // CR-12（本轮 code review）：捕获启动时的代际；连接完成若代际已变
    // （期间 stopAllMcp 被调用），则丢弃结果并关掉连接，防止"复活已停止的 server"。
    const gen = rt.generation;
    // CR6-P2-2：client 提升到 try 外，便于 catch 中清理——listTools() 失败时
    // 子进程已 spawn 却未被 kill（与 CR4 修的 connect() 握手段同类漏网），
    // 每次冷却重试都会再 spawn 一个 → 孤儿进程累积。
    let client: AnyClient | null = null;
    try {
      if (transport === "sse") throw new Error("sse（旧传输）不在 MVP 支持范围，请用 stdio 或 http");
      client = transport === "stdio" ? new StdioClient(rt.cfg) : new HttpClient(rt.cfg);
      await client.connect();
      const tools = await client.listTools();
      if (gen !== rt.generation) {
        // 连接过程中被"停止"：不写回状态，关闭刚建立的连接
        try {
          client.stop();
        } catch {
          /* 停止失败忽略 */
        }
        return null;
      }
      rt.tools = tools;
      rt.client = client;
      rt.state = "connected";
      rt.reason = undefined;
      return client;
    } catch (e) {
      // 清理状态前先停掉已 spawn 的连接（HttpClient 无子进程，stop 为幂等空操作）
      try {
        client?.stop();
      } catch {
        /* 清理失败不应覆盖原始错误 */
      }
      // 代际已变说明这是被废弃的连接尝试：不改状态，避免覆盖停止语义
      if (gen === rt.generation) {
        rt.client = null;
        rt.state = "degraded";
        rt.reason = e instanceof Error ? e.message : "连接失败";
        console.warn(`[mcp:${rt.cfg.name}] 降级（不阻塞对话）：${rt.reason}`);
      }
      return null;
    } finally {
      // 仅当 in-flight 仍是本次连接时才清空——避免 stopAllMcp 已清空后
      // 本次收尾又覆盖掉"后续新连接"的 connecting 引用。
      if (rt.connecting === holder.p) rt.connecting = null;
    }
  })();
  holder.p = attempt;
  rt.connecting = attempt;
  return attempt;
}

/** MCP 工具 → LLM 工具定义（未连接的 server 不注入任何工具） */
export async function mcpLlmTools(): Promise<LlmToolDef[]> {
  const cfgs = loadServerConfigs();
  const defs: LlmToolDef[] = [];
  for (const cfg of cfgs) {
    const rt = runtimeFor(cfg);
    if (rt.state === "disabled") continue;
    const client = await ensureConnected(rt);
    if (!client) continue;
    const allow = cfg.enabledTools;
    for (const t of rt.tools) {
      if (allow && allow.length > 0 && !allow.includes(t.name)) continue;
      defs.push({
        type: "function",
        function: {
          name: toLlmToolName(cfg.name, t.name),
          description: `[MCP:${cfg.name}] ${t.description ?? t.name}`,
          parameters: (t.inputSchema as Record<string, unknown>) ?? {
            type: "object",
            properties: {},
          },
        },
      });
    }
  }
  return defs;
}

/** 调用 MCP 工具（失败一律返回降级结果，不抛异常）
 *
 * CR-13（本轮 code review）：工具名形如 `mcp_<server>_<tool>`（见 toLlmToolName），
 * 可据此**定位目标 server，只连它一个**——此前为匹配工具名会对配置里每个 server
 * 逐个 ensureConnected（可能 spawn 无关子进程），且目标 server 降级时一路 continue，
 * 最终把"工具存在但源不可用"误报成"未知 MCP 工具"。
 */
export async function callMcpTool(
  llmName: string,
  args: Record<string, unknown>,
): Promise<{ ok: boolean; summary: string; data?: unknown }> {
  const clean = (s: string) => s.replace(/[^A-Za-z0-9_]/g, "_");
  const cfgs = loadServerConfigs();
  // 按名字前缀定位候选 server（含长名截断哈希的情况：前缀匹配仍成立者优先）
  const candidates = cfgs.filter((c) => llmName.startsWith(`mcp_${clean(c.name)}_`));
  if (candidates.length === 0) {
    return { ok: false, summary: `未知 MCP 工具：${llmName}` };
  }

  let lastReason = "";
  for (const cfg of candidates) {
    const rt = runtimeFor(cfg);
    if (cfg.enabled === false || rt.state === "disabled") {
      lastReason = `该 MCP 源已禁用（${cfg.name}）`;
      continue;
    }
    const client = await ensureConnected(rt);
    if (!client) {
      lastReason = `该 MCP 源当前不可用（已降级）：${rt.reason ?? "连接失败"}`;
      continue;
    }
    const allow = cfg.enabledTools;
    for (const t of rt.tools) {
      if (allow && allow.length > 0 && !allow.includes(t.name)) continue;
      if (toLlmToolName(cfg.name, t.name) !== llmName) continue;
      try {
        const res = (await client.callTool(t.name, args)) as {
          content?: { type: string; text?: string }[];
          isError?: boolean;
        };
        const text = (res?.content ?? [])
          .map((c) => (c.type === "text" ? c.text ?? "" : ""))
          .join("\n")
          .trim();
        return {
          ok: !res?.isError,
          summary: text.slice(0, 600) || "（MCP 工具无文本输出）",
          data: { server: cfg.name, tool: t.name, isError: Boolean(res?.isError) },
        };
      } catch (e) {
        return {
          ok: false,
          summary: `MCP 调用失败（${cfg.name}/${t.name}）：${
            e instanceof Error ? e.message : "unknown"
          }`,
        };
      }
    }
    lastReason = `该 MCP 源不提供此工具（${cfg.name}）`;
  }
  return {
    ok: false,
    summary: lastReason || `未知 MCP 工具：${llmName}`,
  };
}

/**
 * 状态面板数据（含未连接 server 的降级原因）
 * connect=true 时先探测连接——状态面板要如实反映当前可用性（含降级原因），
 * 否则只会显示从未尝试过的 idle。
 */
export async function mcpStatus(
  opts: { connect?: boolean } = {},
): Promise<{ configPath: string; servers: McpServerStatus[] }> {
  const cfgs = loadServerConfigs();
  const servers: McpServerStatus[] = [];
  for (const cfg of cfgs) {
    const rt = runtimeFor(cfg);
    if (opts.connect && rt.state !== "disabled") {
      await ensureConnected(rt);
    }
    servers.push({
      name: cfg.name,
      transport: cfg.transport ?? "stdio",
      state: rt.state,
      tools: rt.tools.length,
      reason: rt.reason,
      configured: true,
    });
  }
  return { configPath: mcpConfigPath(), servers };
}

/** 测试/运维用：断开全部 stdio server */
export function stopAllMcp(): void {
  for (const [, rt] of runtimes) {
    // CR-12（本轮 code review）：自增代际——进行中的 ensureConnected 完成时
    // 会发现代际已变而丢弃结果并关连接（否则会把 client 写回、置 connected，
    // "复活"已停止的 server）。
    rt.generation += 1;
    rt.client?.stop();
    rt.client = null;
    rt.connecting = null;
    rt.state = "idle";
    rt.tools = [];
  }
}
