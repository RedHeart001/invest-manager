// SSE 通用基础设施（P3 补强：连接管理 / 心跳 / 断线重连，P4 流式对话复用）
// 进程内发布订阅：ingest 落库后广播，Dashboard 实时收到新卡片
//
// 2026-09-13 修复（与 P6 MCP 注册表同类问题）：clients 必须挂在 globalThis——
// 模块级变量在 Next dev 的按需编译 / HMR 时会随模块作用域重建，
// 导致"连接注册在旧 Map、广播查新 Map"→ SSE 事件偶发丢失（test-p3 曾间歇失败）。

type SendFn = (chunk: string) => void;

type Client = { id: string; send: SendFn; connectedAt: number };
type ClientStore = Map<string, Client>;

const CLIENTS_KEY = Symbol.for("invest-manager.sse.clients");
const g = globalThis as unknown as Record<symbol, ClientStore | undefined>;
const clients: ClientStore = (g[CLIENTS_KEY] ??= new Map<string, Client>());

export function registerClient(id: string, send: SendFn): void {
  clients.set(id, { id, send, connectedAt: Date.now() });
}

export function unregisterClient(id: string): void {
  clients.delete(id);
}

export function clientCount(): number {
  return clients.size;
}

/** 广播事件（SSE 格式：event + data 两行 + 空行分隔） */
export function broadcast(event: string, data: unknown): number {
  const chunk = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  let sent = 0;
  for (const [id, c] of clients) {
    try {
      c.send(chunk);
      sent += 1;
    } catch {
      clients.delete(id);
    }
  }
  return sent;
}
