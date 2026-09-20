// CR6-P2-2 回归测试：listTools() 失败时必须 kill 已 spawn 的 stdio 子进程。
//
// 背景：connect() 握手失败已由 CR4 修好（catch 里 client.stop()），但 listTools()
// 抛错走的是同一外层 catch——修复前只清状态、不 stop，子进程泄漏；此后每次
// 冷却重试都会再 spawn 一个 → 孤儿进程累积。
//
// 策略：mock node:child_process.spawn 返回一个"能完成 initialize、但对 tools/list
// 回错误"的假子进程，断言 child.kill() 被调用。独立文件，避免影响 mcp.test.ts 的
// 真实 stdio 用例。

import { EventEmitter } from "node:events";

import { describe, expect, it, vi } from "vitest";

const kill = vi.fn();

class FakeChild extends EventEmitter {
  stdout = Object.assign(new EventEmitter(), { setEncoding: () => {} });
  stderr = Object.assign(new EventEmitter(), { setEncoding: () => {} });
  stdin = {
    write: (line: string) => {
      const msg = JSON.parse(line);
      if (msg.method === "initialize") {
        queueMicrotask(() =>
          this.stdout.emit(
            "data",
            `${JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { protocolVersion: "2024-11-05" } })}\n`,
          ),
        );
      } else if (msg.method === "tools/list") {
        // 握手成功、列举工具失败：正是 CR6-P2-2 要覆盖的路径
        queueMicrotask(() =>
          this.stdout.emit(
            "data",
            `${JSON.stringify({ jsonrpc: "2.0", id: msg.id, error: { message: "tools/list boom" } })}\n`,
          ),
        );
      }
      return true;
    },
  };
  kill = kill;
}

vi.mock("node:child_process", () => ({
  spawn: vi.fn(() => new FakeChild()),
}));

describe("ensureConnected 泄漏防护（CR6-P2-2）", () => {
  it("listTools() 失败 → 子进程被 kill，状态降级", async () => {
    kill.mockClear();
    const mcp = await import("./mcp");

    const dir = process.cwd();
    const cfgFile = `${dir}/.mcp-leak-test.json`;
    const fs = await import("node:fs");
    fs.writeFileSync(
      cfgFile,
      JSON.stringify({
        servers: [
          { name: "leaky", transport: "stdio", command: process.execPath, args: ["-e", ""] },
        ],
      }),
      "utf8",
    );
    process.env.MCP_CONFIG = cfgFile;

    try {
      const tools = await mcp.mcpLlmTools(); // 不得抛错
      expect(tools.length).toBe(0);

      const status = await mcp.mcpStatus();
      const entry = status.servers.find((s) => s.name === "leaky");
      expect(entry?.state).toBe("degraded");
      // 关键断言：子进程被 stop（→ kill）清理，不泄漏
      expect(kill).toHaveBeenCalled();
    } finally {
      mcp.stopAllMcp();
      fs.rmSync(cfgFile, { force: true });
    }
  });
});
