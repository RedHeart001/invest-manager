import { describe, expect, it } from "vitest";

// CR-08：写接口 Origin/Referer 校验（防浏览器跨站简单表单触发）
import { checkRequestOrigin } from "./request-origin";

/** 构造最小可用的 NextRequest 替身（只需 headers 与 nextUrl.origin） */
function req(opts: { origin?: string; referer?: string; self?: string; host?: string }) {
  const headers = new Headers();
  if (opts.origin) headers.set("origin", opts.origin);
  if (opts.referer) headers.set("referer", opts.referer);
  if (opts.host) headers.set("host", opts.host);
  return {
    headers,
    nextUrl: { origin: opts.self ?? "http://localhost:3000" },
  } as unknown as Parameters<typeof checkRequestOrigin>[0];
}

describe("checkRequestOrigin（CR-08）", () => {
  it("同源 Origin → 放行", () => {
    expect(checkRequestOrigin(req({ origin: "http://localhost:3000" }))).toBeNull();
  });

  it("跨站 Origin → 拒绝", () => {
    const r = checkRequestOrigin(req({ origin: "http://evil.example.com" }));
    expect(r).toMatch(/cross-site/);
  });

  it("无 Origin/Referer（curl/测试/同源 fetch）→ 放行", () => {
    expect(checkRequestOrigin(req({}))).toBeNull();
  });

  it("Origin 缺失但有同源 Referer → 放行", () => {
    expect(
      checkRequestOrigin(req({ referer: "http://localhost:3000/search" })),
    ).toBeNull();
  });

  it("Origin 缺失但跨站 Referer → 拒绝", () => {
    const r = checkRequestOrigin(req({ referer: "http://evil.example.com/page" }));
    expect(r).toMatch(/cross-site/);
  });

  it("Origin 优先于 Referer（Origin 跨站即拒，即使 Referer 同源）", () => {
    const r = checkRequestOrigin(
      req({ origin: "http://evil.example.com", referer: "http://localhost:3000/x" }),
    );
    expect(r).toMatch(/cross-site/);
  });

  it("端口不同视为不同站 → 拒绝", () => {
    const r = checkRequestOrigin(req({ origin: "http://localhost:4000" }));
    expect(r).toMatch(/cross-site/);
  });

  it("合法 URL 但非法 Origin 值（不可解析）→ 放行（不误伤）", () => {
    expect(checkRequestOrigin(req({ origin: "not-a-url" }))).toBeNull();
  });
});
