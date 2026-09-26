// P6：Tool Gateway 单测——命名空间分派、内置工具名不变（P4 红线）、技能注入、MCP 汇入

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { AGENT_TOOLS, guardToolArgs } from "./tools";
import { QUOTE_TYPES } from "./validate";
import { buildSystemPrompt, executeAgentTool, getAgentTools, gatewayStatus } from "./gateway";
import { stopAllMcp } from "./mcp";

const savedEnv = { ...process.env };
// CR9-14：本文件的工具用例原会真打实时链路（get_quote → ds → 东财）。实测两次实证其
// 不可复现：ds 饥饿态下 184/185（撞 vitest 默认 5s），服务恢复后 185/185 且同一用例仅
// 1029ms——同一份代码只换外部源健康度就翻转，"vitest 全绿"因此失去判别力。
// 现按本仓库既有约定（见 data-service.test.ts）stub globalThis.fetch，精确复现两种失败形态。
// 真实降级链的覆盖不在此处：ds 离线套件（test_g6_hk / test_p2_m8 / test_tencent_minute）
// 与 web 集成套件（scripts/test-p4.mjs、test-p6.mjs）。
const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
});
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

  // CR9-10 把 PRODUCT_TYPE_ENUM 归一成 QUOTE_TYPES 的别名——**发给 LLM 的 schema 值不能因此变动**
  // （P4 兼容红线：工具名不变之外，寻址面也不能变）。这条把 enum 的实际取值钉死。
  it("发给 LLM 的 type enum 取值逐项不变（六类通用 / 研报两工具只 stock+us）", () => {
    for (const t of AGENT_TOOLS) {
      const props = (
        t.function.parameters as { properties?: Record<string, { enum?: readonly string[] }> }
      ).properties;
      const typeProp = props?.type;
      if (!typeProp?.enum) continue;
      if (t.function.name === "deep_research" || t.function.name === "get_research_report") {
        expect([...typeProp.enum]).toEqual(["stock", "us"]);
      } else {
        expect([...typeProp.enum]).toEqual([...QUOTE_TYPES]);
      }
    }
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
    // 形态①：连不上（ds 未起 / 网络不可达）→ dsGet 抛 DataServiceError，executeTool 兜住
    globalThis.fetch = (() => Promise.reject(new TypeError("fetch failed"))) as unknown as typeof fetch;
    const r1 = await executeAgentTool("get_quote", { type: "stock", code: "600519" });
    expect(r1.ok).toBe(false);
    expect(r1.summary).toContain("unreachable");

    // 形态②：ds 在跑但该标的取数失败（502 + detail）→ 失败理由原样交给 LLM，不许变空白
    globalThis.fetch = () =>
      Promise.resolve({
        ok: false,
        status: 502,
        json: () => Promise.resolve({ detail: "all sources failed: akshare: cooling down; tencent: quote empty" }),
      } as unknown as Response);
    const r2 = await executeAgentTool("get_quote", { type: "stock", code: "600519" });
    expect(r2.ok).toBe(false);
    expect(r2.summary).toContain("all sources failed");
  });

  it("CR9-10：非法 type/code 在出网前被拒（闸门生效且零次 socket 请求）", async () => {
    let calls = 0;
    globalThis.fetch = (() => {
      calls += 1;
      return Promise.resolve({
        ok: false,
        status: 502,
        json: () => Promise.resolve({ detail: "spy" }),
      } as unknown as Response);
    }) as unknown as typeof fetch;

    // 探针自检：计数器先证明"能记录到合法调用"，否则下面的 0 次不成立（CR9-14 教训）
    await executeAgentTool("get_quote", { type: "stock", code: "600519" });
    expect(calls).toBe(1);

    for (const bad of [
      { type: "股票x", code: "600519" }, // type 不在白名单
      { type: "stock", code: "../etc/passwd" }, // code 含斜杠
      { type: "stock", code: "" }, // code 缺失
    ]) {
      const r = await executeAgentTool("get_quote", bad);
      expect(r.ok).toBe(false);
      expect(r.summary).toContain("入参不合法");
    }
    // 只带 code 的基金工具此前完全无判，同受闸门约束
    const r3 = await executeAgentTool("get_fund_holdings", { code: "贵州茅台" });
    expect(r3.ok).toBe(false);
    expect(r3.summary).toContain("invalid code");
    expect(calls).toBe(1); // 四条非法入参一次都没出网
  });

  // 需求面红线（PLAN 验证方式 P4/P5）：闸门只许拒绝，不许把合法调用挤出轨道。
  // 初版实现在此处真留过一个回归——缺省 type 被回填成 "stock"，于是
  // `deep_research(code="AAPL")`（P5 验收②：详情页/工具对 AAPL 走同一链路）
  // 会被判成 A股标的，美股研报直接失效。
  it("数字型 code（LLM function calling 的常见形态）仍放行，且按字符串出网", async () => {
    let seenUrl = "";
    globalThis.fetch = ((input: unknown) => {
      seenUrl = String(input);
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ name: "贵州茅台", price: 1237, currency: "CNY" }),
      } as unknown as Response);
    }) as unknown as typeof fetch;
    const r = await executeAgentTool("get_quote", { type: "stock", code: 600519 });
    expect(r.ok).toBe(true);
    expect(seenUrl).toContain("code=600519");
    expect(seenUrl).not.toContain("600519%20");
  });

  it("闸门不回填缺省的 type，也不改写非 code 字段", () => {
    const g = guardToolArgs("deep_research", { code: "AAPL" });
    expect("err" in g).toBe(false);
    if ("args" in g) expect(g.args.type).toBeUndefined(); // 交给工具自己的 A股/美股形态判断
    const g2 = guardToolArgs("get_kline", { code: " 600519 ", days: 7 });
    if ("args" in g2) {
      expect(g2.args.code).toBe("600519"); // 只做 trim/String 化
      expect(g2.args.days).toBe(7);
      expect("type" in g2.args).toBe(false);
    } else {
      expect("不应被拒：" + g2.err).toBe("ok");
    }
    const g3 = guardToolArgs("get_fund_holdings", { code: 110022 });
    if ("args" in g3) expect(g3.args.code).toBe("110022");
    else expect("数字 code 不应被拒：" + g3.err).toBe("ok");
  });
});

describe("技能注入（keyword 档：显式固定，保持确定性断言）", () => {
  beforeEach(() => {
    process.env.SKILL_ROUTER = "keyword";
  });
  afterEach(() => {
    delete process.env.SKILL_ROUTER;
  });

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

describe("技能注入（llm 档，OPT-1 路线 C）", () => {
  beforeEach(() => {
    process.env.SKILL_ROUTER = "llm";
  });
  afterEach(() => {
    delete process.env.SKILL_ROUTER;
  });

  it("正文一律不注入，meta 引导调用 load_skill；实际加载移交 loader 在 done 事件汇报", () => {
    const miss = buildSystemPrompt("帮我算一下 1+1");
    expect(miss.activeSkills).toEqual([]);
    expect(miss.prompt).toContain("load_skill");
    expect(miss.prompt).toContain("hotspot-daily："); // 候选清单常驻
    expect(miss.prompt).not.toContain("热点日报生成"); // 正文标题不进 prompt

    const hit = buildSystemPrompt("今天市场热点有哪些？");
    expect(hit.prompt).not.toContain("热点日报生成");
    expect(hit.activeSkills).toEqual([]); // 不再有构建期命中概念
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
    expect(status.namespaces.skill.router).toBe("llm"); // 默认档（此时 SKILL_ROUTER 已被上文 afterEach 清除）
    expect(status.namespaces.mcp.servers[0].state).toBe("connected");
    expect(JSON.stringify(status)).not.toContain("硬性约束");
  });
});
