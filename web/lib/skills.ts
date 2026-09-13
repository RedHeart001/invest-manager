// Skills 技能系统（PLAN M7 ①，P6 二轮补强）
//
// 设计要点（与 PLAN 定稿一致）：
// - 目录约定沿用 Anthropic Agent Skills 开放格式：skills/<name>/SKILL.md
// - 启动/请求时**仅注入元信息**（name + description）到 system prompt，控制上下文成本
// - 对话命中触发词时才按需注入该技能正文（正文 token 上限保护）
// - 技能是「prompt 指令包 + 工具编排」，**不引入新数据逻辑**（数据一律走 L1/L2 工具）
// - mtime 热加载：技能文件改动后无需重启服务即可生效

import fs from "node:fs";
import path from "node:path";

export type SkillMeta = {
  name: string;
  description: string;
  triggers: string[];
  tools: string[];
  dir: string;
  /** 正文长度（字符），用于状态面板与调试 */
  bodyChars: number;
  updatedAt: number;
};

export type Skill = SkillMeta & { body: string };

/** 技能正文注入上限（字符代理 token 预算），env 可覆盖 */
export function maxBodyChars(): number {
  const v = Number(process.env.SKILL_MAX_BODY_CHARS);
  return Number.isFinite(v) && v > 0 ? v : 2400;
}

/** 单轮同时激活技能数上限，env 可覆盖 */
export function maxActiveSkills(): number {
  const v = Number(process.env.SKILL_MAX_ACTIVE);
  return Number.isFinite(v) && v > 0 ? v : 3;
}

export function skillsDir(): string {
  const dir = process.env.SKILLS_DIR?.trim();
  if (!dir) return path.join(process.cwd(), "skills");
  return path.isAbsolute(dir) ? dir : path.join(process.cwd(), dir);
}

type CacheEntry = { mtimeMs: number; skill: Skill };

const cache = new Map<string, CacheEntry>();

/** 极简 frontmatter 解析（name/description/triggers/tools，comma 或 YAML list） */
export function parseFrontmatter(raw: string): { meta: Record<string, string | string[]>; body: string } {
  const text = raw.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n");
  const m = text.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!m) return { meta: {}, body: text.trim() };
  const meta: Record<string, string | string[]> = {};
  let pendingKey: string | null = null;
  for (const line of m[1].split("\n")) {
    if (!line.trim() || line.trim().startsWith("#")) continue;
    const listItem = line.match(/^\s*-\s+(.*)$/);
    if (listItem && pendingKey) {
      const prev = meta[pendingKey];
      const arr = Array.isArray(prev) ? prev : prev ? [prev] : [];
      arr.push(unquote(listItem[1]));
      meta[pendingKey] = arr;
      continue;
    }
    const kv = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
    if (!kv) continue;
    const key = kv[1];
    const value = kv[2].trim();
    if (value === "") {
      pendingKey = key;
      meta[key] = [];
    } else {
      pendingKey = key;
      meta[key] = value.startsWith("[")
        ? value
            .replace(/^\[|\]$/g, "")
            .split(",")
            .map((s) => unquote(s.trim()))
            .filter(Boolean)
        : unquote(value);
    }
  }
  return { meta, body: text.slice(m[0].length).trim() };
}

function unquote(s: string): string {
  const t = s.trim();
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    return t.slice(1, -1).trim();
  }
  return t;
}

function toList(v: string | string[] | undefined): string[] {
  if (!v) return [];
  if (Array.isArray(v)) return v.filter(Boolean);
  return v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function readSkill(file: string, dirName: string): Skill | null {
  let stat: fs.Stats;
  try {
    stat = fs.statSync(file);
  } catch {
    cache.delete(file);
    return null;
  }
  const hit = cache.get(file);
  if (hit && hit.mtimeMs === stat.mtimeMs) return hit.skill;

  let raw = "";
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch {
    return null;
  }
  const { meta, body } = parseFrontmatter(raw);
  const name = String(meta.name ?? dirName).trim() || dirName;
  const skill: Skill = {
    name,
    description: String(meta.description ?? "").trim(),
    triggers: toList(meta.triggers),
    tools: toList(meta.tools),
    dir: path.dirname(file),
    bodyChars: body.length,
    updatedAt: stat.mtimeMs,
    body,
  };
  cache.set(file, { mtimeMs: stat.mtimeMs, skill });
  return skill;
}

/** 扫描技能目录（mtime 命中即复用缓存；缺目录返回空数组，不抛错） */
export function loadSkills(): Skill[] {
  const root = skillsDir();
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(root, { withFileTypes: true });
  } catch {
    return [];
  }
  const skills: Skill[] = [];
  for (const e of entries) {
    if (!e.isDirectory()) continue;
    const file = path.join(root, e.name, "SKILL.md");
    if (!fs.existsSync(file)) continue;
    const s = readSkill(file, e.name);
    if (s) skills.push(s);
  }
  return skills.sort((a, b) => a.name.localeCompare(b.name));
}

/** 触发词命中（大小写不敏感的子串匹配；无语义模型，规则可控可测） */
export function selectSkills(message: string, all = loadSkills()): Skill[] {
  const text = message.toLowerCase();
  if (!text.trim()) return [];
  const matched = all.filter((s) => s.triggers.some((t) => t && text.includes(t.toLowerCase())));
  return matched.slice(0, maxActiveSkills());
}

/** system prompt 中的技能元信息段（仅 name + description，不含正文） */
export function skillsMetaPrompt(all = loadSkills()): string {
  if (all.length === 0) return "";
  const lines = all.map((s) => `- ${s.name}：${s.description}`).join("\n");
  return `\n可用技能（命中触发词时会自动加载其详细指引，无需向用户解释机制）：\n${lines}`;
}

/**
 * 命中技能的正文段。正文按上限截断，并显式标注截断（避免 LLM 误以为数据缺失）。
 * 返回空字符串表示本轮无技能激活。
 */
export function skillsBodyPrompt(
  message: string,
  all = loadSkills(),
  preselected?: Skill[],
): string {
  // B1：允许调用方传入已选择的结果（buildSystemPrompt 已选过一次），
  // 避免对同一条消息重复做触发词匹配
  const hits = preselected ?? selectSkills(message, all);
  if (hits.length === 0) return "";
  const cap = maxBodyChars();
  const blocks = hits.map((s) => {
    const body = s.body.length > cap ? `${s.body.slice(0, cap)}\n…（技能正文超长已截断）` : s.body;
    return `【技能：${s.name}】\n${body}`;
  });
  return `\n\n=== 已激活技能指引 ===\n${blocks.join("\n\n")}`;
}

/** 状态面板用：技能清单（不回传正文，避免接口膨胀） */
export function skillsStatus() {
  return {
    dir: skillsDir(),
    maxBodyChars: maxBodyChars(),
    maxActive: maxActiveSkills(),
    skills: loadSkills().map(({ name, description, triggers, tools, bodyChars, updatedAt }) => ({
      name,
      description,
      triggers,
      tools,
      bodyChars,
      updatedAt: new Date(updatedAt).toISOString(),
    })),
  };
}
