// P6：Tool Gateway 单测——命名空间分派、内置工具名不变（P4 红线）、技能注入、MCP 汇入

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { AGENT_TOOLS } from "./tools";
import { buildSystemPrompt, executeAgentTool, getAgentTools, gatewayStatus } from "./gateway";
import { stopAllMcp } from "./mcp";

const savedEnv = { ...process.env };
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "gateway-test-"));
const localServer = path.resolve(__dirname, "..", "scripts", "mcp-local-util.mjs");

beforeAll(() => {
  const cfgFile = path.join(tmpDir, "mcp.json");
  fs.writeFileSync(
    cfgFile,
    JSON.stringify({
      servers: [
        {
          name: "gw-test",
          transport: "stdio",
          command: process.execPath,
          args: [localServer],
          timeoutMs: 15000,
        },
      ],
    }),
    "utf8",
  );
  process.env.MCP_CONFIG = cfgFile;
  // 技能目录指向仓库内真实技能（验证首批技能可被加载与命中）
  process.env.SKILLS_DIR = path.resolve(__dirname, "..", "skills");
});

afterAll(() => {
  stopAllMcp();
  fs.rmSync(tmpDir, { recursive: true, force: true });
  process.env = { ...savedEnv };
});

describe("内置工具兼容性（P4 回归红线）", () => {
  it("L1+L2 工具名保持不变，且新增 get_fund_report", () => {
    const names = AGENT_TOOLS.map((t) => t.function.name);
    expect(names).toEqual([
      "search_products",
      "get_quote",
      "get_kline",
      "get_hotspots",
      "get_fund_holdings",
      "get_phase_analysis",
      "get_fund_report",
      "deep_research",
      "get_research_report",
    ]);
  });

  it("网关返回的工具集 = 内置 + MCP，内置名字未被加前缀", async () => {
    const tools = await getAgentTools();
    const names = tools.map((t) => t.function.name);
    expect(names.slice(0, AGENT_TOOLS.length)).toEqual(AGENT_TOOLS.map((t) => t.function.name));
    expect(names).toContain("mcp_gw_test_local_now");
    expect(names.some((n) => n.startsWith("builtin:"))).toBe(false);
  });
});

describe("命名空间分派", () => {
  it("未知工具返回结构化失败（不抛异常）", async () => {
    const r = await executeAgentTool("not_a_tool", {});
    expect(r.ok).toBe(false);
    expect(r.summary).toContain("未知工具");
  });

  it("mcp_ 前缀 → 走 MCP 客户端", async () => {
    const r = await executeAgentTool("mcp_gw_test_local_now", {});
    expect(r.ok).toBe(true);
    expect(r.summary).toContain("北京时间");
  });

  it("内置工具执行失败也返回结构化结果（降级不抛错）", async () => {
    const r = await executeAgentTool("get_quote", { type: "stock", code: "600519" });
    expect(typeof r.ok).toBe("boolean");
    expect(typeof r.summary).toBe("string");
  });
});

describe("技能注入", () => {
  it("元信息常驻，正文仅命中时注入", () => {
    const miss = buildSystemPrompt("帮我算一下 1+1");
    expect(miss.activeSkills).toEqual([]);
    expect(miss.prompt).toContain("hotspot-daily：");
    expect(miss.prompt).not.toContain("热点日报生成"); // 正文标题，不应出现在未命中时

    const hit = buildSystemPrompt("今天市场热点有哪些？");
    expect(hit.activeSkills).toEqual(["hotspot-daily"]);
    expect(hit.prompt).toContain("热点日报生成");
  });

  it("基金类问题命中基金技能，技术面问题命中技术技能", () => {
    expect(buildSystemPrompt("110022 这只基金的季报怎么看").activeSkills).toContain(
      "fund-report-analysis",
    );
    expect(buildSystemPrompt("这票最近为什么涨").activeSkills).toContain("tech-indicators");
  });

  it("同时激活数上限生效（默认 3）", () => {
    const { activeSkills } = buildSystemPrompt("热点日报 + 均线 + 基金季报 一起看");
    expect(activeSkills.length).toBe(3);
  });
});

describe("状态面板", () => {
  it("三分命名空间齐全，且不回传技能正文", async () => {
    const status = await gatewayStatus();
    expect(status.namespaces.builtin.count).toBe(9);
    expect(status.namespaces.skill.skills).toEqual([
      "fund-report-analysis",
      "hotspot-daily",
      "tech-indicators",
    ]);
    expect(status.namespaces.mcp.servers[0].state).toBe("connected");
    expect(JSON.stringify(status)).not.toContain("硬性约束");
  });
});
