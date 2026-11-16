import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(HERE, "page.tsx"), "utf8");

describe("搜索页 SSR 渲染策略", () => {
  it("保持请求时渲染，避免布局 Nav 的 useSearchParams 预渲染 bailout", () => {
    expect(source).toContain('export const dynamic = "force-dynamic"');
    expect(readFileSync(path.join(HERE, "..", "layout.tsx"), "utf8")).toContain("useSearchParams");
  });
});
