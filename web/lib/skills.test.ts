// P6：Skills 加载器单测（frontmatter 解析 / 触发词命中 / token 与激活数上限）

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  createSkillLoader,
  loadSkills,
  maxActiveSkills,
  maxBodyChars,
  parseFrontmatter,
  selectSkills,
  skillRouterMode,
  skillsBodyPrompt,
  skillsMetaPrompt,
} from "./skills";

const savedEnv = { ...process.env };

function mkSkill(root: string, dir: string, content: string) {
  fs.mkdirSync(path.join(root, dir), { recursive: true });
  fs.writeFileSync(path.join(root, dir, "SKILL.md"), content, "utf8");
}

let tmp: string;

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "skills-test-"));
  process.env.SKILLS_DIR = tmp;
  delete process.env.SKILL_MAX_BODY_CHARS;
  delete process.env.SKILL_MAX_ACTIVE;
});

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
  process.env = { ...savedEnv };
});

describe("parseFrontmatter", () => {
  it("解析 key: value 与 YAML 列表", () => {
    const { meta, body } = parseFrontmatter(
      ["---", "name: demo", "description: 演示技能", "triggers:", "  - 甲", "  - 乙", "---", "# 正文"].join("\n"),
    );
    expect(meta.name).toBe("demo");
    expect(meta.description).toBe("演示技能");
    expect(meta.triggers).toEqual(["甲", "乙"]);
    expect(body).toBe("# 正文");
  });

  it("支持行内逗号数组与引号剥离", () => {
    const { meta } = parseFrontmatter('---\nname: "d2"\ntriggers: [甲, "乙"]\n---\nX');
    expect(meta.name).toBe("d2");
    expect(meta.triggers).toEqual(["甲", "乙"]);
  });

  it("无 frontmatter 时正文原样返回", () => {
    const { meta, body } = parseFrontmatter("纯正文");
    expect(meta).toEqual({});
    expect(body).toBe("纯正文");
  });
});

describe("loadSkills / selectSkills", () => {
  beforeEach(() => {
    mkSkill(tmp, "alpha", "---\nname: alpha\ndescription: 甲技能\ntriggers:\n  - 热点\n  - 日报\n---\nALPHA BODY");
    mkSkill(tmp, "beta", "---\nname: beta\ndescription: 乙技能\ntriggers:\n  - 均线\n---\nBETA BODY");
    // 无 SKILL.md 的目录应被跳过
    fs.mkdirSync(path.join(tmp, "broken"), { recursive: true });
  });

  it("扫描目录只取含 SKILL.md 的技能，并按 name 排序", () => {
    const names = loadSkills().map((s) => s.name);
    expect(names).toEqual(["alpha", "beta"]);
  });

  it("触发词命中（大小写不敏感）", () => {
    expect(selectSkills("今天热点怎么样").map((s) => s.name)).toEqual(["alpha"]);
    expect(selectSkills("EXP 没有命中词")).toEqual([]);
    expect(selectSkills("").length).toBe(0);
  });

  it("元信息段只含 name 与 description，不含正文", () => {
    const meta = skillsMetaPrompt();
    expect(meta).toContain("alpha：甲技能");
    expect(meta).not.toContain("ALPHA BODY");
  });

  it("命中时注入正文，未命中不占上下文", () => {
    expect(skillsBodyPrompt("看看日报")).toContain("ALPHA BODY");
    expect(skillsBodyPrompt("看看日报")).not.toContain("BETA BODY");
    expect(skillsBodyPrompt("无关问题")).toBe("");
  });
});

describe("上限保护", () => {
  it("正文超出字符上限时截断并标注", () => {
    process.env.SKILL_MAX_BODY_CHARS = "20";
    mkSkill(tmp, "long", `---\nname: long\ndescription: 长正文\ntriggers:\n  - 长文\n---\n${"字".repeat(100)}`);
    expect(maxBodyChars()).toBe(20);
    const prompt = skillsBodyPrompt("长文");
    expect(prompt).toContain("技能正文超长已截断");
    expect(prompt.length).toBeLessThan(200);
  });

  it("同时激活数超上限时截断（默认 3）", () => {
    expect(maxActiveSkills()).toBe(3);
    for (let i = 1; i <= 5; i++) {
      mkSkill(tmp, `s${i}`, `---\nname: s${i}\ndescription: 技能${i}\ntriggers:\n  - 通用词\n---\nBODY${i}`);
    }
    expect(selectSkills("通用词").length).toBe(3);

    process.env.SKILL_MAX_ACTIVE = "1";
    expect(maxActiveSkills()).toBe(1);
    expect(selectSkills("通用词").length).toBe(1);
  });
});

describe("热加载", () => {
  it("技能文件改动后无需重启即可生效（mtime 失效缓存）", async () => {
    const file = path.join(tmp, "hot", "SKILL.md");
    mkSkill(tmp, "hot", "---\nname: hot\ndescription: 旧\ntriggers:\n  - 热\n---\nOLD");
    expect(loadSkills().find((s) => s.name === "hot")?.description).toBe("旧");

    await new Promise((r) => setTimeout(r, 20));
    fs.writeFileSync(file, "---\nname: hot\ndescription: 新\ntriggers:\n  - 热\n---\nNEW", "utf8");
    const after = loadSkills().find((s) => s.name === "hot");
    expect(after?.description).toBe("新");
    expect(skillsBodyPrompt("热")).toContain("NEW");
  });
});

describe("skillRouterMode（OPT-1 路线 C）", () => {
  it("默认 llm；keyword/hybrid 显式生效（大小写不敏感）；非法值回退默认", () => {
    delete process.env.SKILL_ROUTER;
    expect(skillRouterMode()).toBe("llm");
    process.env.SKILL_ROUTER = "keyword";
    expect(skillRouterMode()).toBe("keyword");
    process.env.SKILL_ROUTER = "HYBRID";
    expect(skillRouterMode()).toBe("hybrid");
    process.env.SKILL_ROUTER = "bogus";
    expect(skillRouterMode()).toBe("llm");
  });

  it("llm 档元信息引导调用 load_skill；keyword 档保持原文案", () => {
    mkSkill(tmp, "alpha", "---\nname: alpha\ndescription: 甲技能\ntriggers:\n  - 热点\n---\nBODY");
    process.env.SKILL_ROUTER = "llm";
    const llmMeta = skillsMetaPrompt(undefined, "llm");
    expect(llmMeta).toContain("load_skill");
    expect(llmMeta).not.toContain("BODY");
    process.env.SKILL_ROUTER = "keyword";
    expect(skillsMetaPrompt()).toContain("命中触发词时会自动加载");
  });
});

describe("createSkillLoader（OPT-1 路线 C）", () => {
  beforeEach(() => {
    mkSkill(tmp, "alpha", "---\nname: alpha\ndescription: 甲技能\ntriggers:\n  - 热点\n---\nALPHA BODY");
    mkSkill(tmp, "beta", "---\nname: beta\ndescription: 乙技能\ntriggers:\n  - 均线\n---\nBETA BODY");
  });

  it("空技能目录不注册工具（模型无从误调）", () => {
    expect(createSkillLoader([]).def).toBeNull();
  });

  it("def 携带工具名与候选 enum 白名单", () => {
    const { def } = createSkillLoader();
    expect(def?.function.name).toBe("load_skill");
    const params = def?.function.parameters as { properties: { name: { enum: string[] } } };
    expect(params.properties.name.enum).toEqual(["alpha", "beta"]);
  });

  it("加载返回正文并计入 loaded；未知名返回可用候选引导自愈", () => {
    const loader = createSkillLoader();
    const r = loader.run("alpha");
    expect(r.ok).toBe(true);
    expect((r.data as { body: string }).body).toBe("ALPHA BODY");
    expect(loader.loaded()).toEqual(["alpha"]);

    const bad = loader.run("nope");
    expect(bad.ok).toBe(false);
    expect(bad.summary).toContain("alpha / beta");
    expect(loader.loaded()).toEqual(["alpha"]);
  });

  it("超上限拒绝并保留已加载列表；重复加载幂等（不重复计数）", () => {
    process.env.SKILL_MAX_ACTIVE = "1";
    const loader = createSkillLoader();
    expect(loader.run("alpha").ok).toBe(true);
    const over = loader.run("beta");
    expect(over.ok).toBe(false);
    expect(over.summary).toContain("最多加载 1");
    expect(loader.loaded()).toEqual(["alpha"]);

    const dup = loader.run("alpha");
    expect(dup.ok).toBe(true);
    expect((dup.data as { body: string }).body).toBe("ALPHA BODY");
    expect(loader.loaded()).toEqual(["alpha"]);
  });

  it("正文超长时截断并标注 truncated", () => {
    process.env.SKILL_MAX_BODY_CHARS = "10";
    mkSkill(tmp, "long", `---\nname: long\ndescription: 长正文\n---\n${"字".repeat(50)}`);
    const loader = createSkillLoader();
    const r = loader.run("long");
    const data = r.data as { body: string; truncated: boolean };
    expect(data.truncated).toBe(true);
    expect(data.body).toContain("技能正文超长已截断");
  });
});
