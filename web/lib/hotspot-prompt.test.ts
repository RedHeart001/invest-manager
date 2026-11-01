/**
 * R19（2026-11-02）：热点「去分析」→ /chat?prompt= 预填。
 * 接线断言用源码字面（沿 jsx-key-guard.test.ts 先例）：本仓无组件渲染测试设施，
 * 只测纯函数会出现"函数对但没人调它"的全绿假象（R18 第四钻教训），故两半都钉。
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { buildHotspotChatHref } from "./hotspot-prompt";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = (rel: string) => readFileSync(path.join(ROOT, rel), "utf-8");

describe("buildHotspotChatHref（纯函数）", () => {
  it("标题＋摘要：prompt 前缀固定、两段以换行相接，URL 编码可逆", () => {
    const href = buildHotspotChatHref({ title: "美联储降息", summary: "市场预期升温。" });
    expect(href.startsWith("/chat?prompt=")).toBe(true);
    const prompt = decodeURIComponent(href.slice("/chat?prompt=".length));
    expect(prompt).toBe("热点深入分析：美联储降息\n市场预期升温。");
  });

  it("摘要为空串：不留尾随换行", () => {
    const href = buildHotspotChatHref({ title: "只有标题", summary: "" });
    expect(decodeURIComponent(href.slice("/chat?prompt=".length))).toBe("热点深入分析：只有标题");
  });

  it("标题含 &、=、中文标点等 URL 敏感字符：编码后不破坏查询串", () => {
    const href = buildHotspotChatHref({ title: "A&B=C？", summary: "x/y+z" });
    const query = href.slice("/chat?prompt=".length);
    expect(query).not.toContain("&");
    expect(query).not.toContain("=");
    expect(decodeURIComponent(query)).toBe("热点深入分析：A&B=C？\nx/y+z");
  });
});

describe("R19 接线（源码字面断言）", () => {
  it("HotspotFeed 调 buildHotspotChatHref，且旧的 #research 跳转已消失", () => {
    const s = src("app/HotspotFeed.tsx");
    expect(s).toContain('import { buildHotspotChatHref } from "@/lib/hotspot-prompt"');
    expect(s).toContain("href={buildHotspotChatHref(r)}");
    expect(s).not.toContain("#research");
    // 按钮字面归主人：CR8-2 那次改名后的「去分析 <标的>」维持不变
    expect(s).toContain("去分析 {r.related[0].name}");
  });

  it("chat/page.tsx 读 searchParams.prompt 并传 initialInput", () => {
    const s = src("app/chat/page.tsx");
    expect(s).toContain("searchParams");
    expect(s).toContain("params.prompt");
    expect(s).toContain("<ChatUI initialInput={prompt || undefined} />");
  });

  it("ChatUI 用 initialInput 预填输入 state（只预填、不自动发送）", () => {
    const s = src("app/chat/ChatUI.tsx");
    expect(s).toContain("{ initialInput }: { initialInput?: string }");
    expect(s).toContain('useState(initialInput ?? "")');
  });
});
