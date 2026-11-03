/**
 * CR10-12：**覆盖面机制**，不是清单。
 *
 * 为什么欠这一份：`request-origin.ts` 的纯函数自己早有测，`research/start/route.test.ts` 钉的是
 * 那**一枚**路由——于是"哪些写入口根本没挂它"这件事只能靠我逐轮读码数（11-03 一轮里我自己就
 * 把"零 origin 守卫 9 枚"报成过"零守卫 9 枚"，把带 `x-ingest-token` 的两枚也算进去了）。
 * 本文件把判据变成会自己红的尺：**任何新增的 `POST` 没挂守卫、又没在 KNOWN 里带理由登记 ⇒ 红**。
 *
 * 两枚反向样本都用**合成件**跑同一把尺（沿 C34「成对断言」那条纪律）。为什么不在盘上钻：
 * 11-03 16:2x 试过"临时把某枚路由的守卫调用改坏 ⇒ 看尺红"那一形，被权限层按 [Security Weaken] 拦下
 * ＝故意写坏安全件这个动作本身不像验收、像拆防护；改成合成件后，判别力证明不落 production 一个字。
 *
 * 可达性口径（为什么逐 POST 而不逐 DELETE/PUT）＝全站无 `middleware.ts`、零 CORS 头 ⇒ 带 JSON 体的
 * DELETE／PUT 属非简单请求，浏览器必先预检、外站页面驱动不到；POST 是简单请求，`sendBeacon`／
 * `no-cors`＋`text/plain` 装 JSON 就能打进来（`Request.json()` 不看 Content-Type）。
 * 那几枚 DELETE／PUT 本轮**刻意没挂**＝纵深防御缺口、不是补漏项，账＝docs/FIX-LEDGER.md 看板 CR10-12 行。
 *
 * 运行（零出网、不起服务）：`npx vitest run lib/request-origin-wiring.test.ts`
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const API_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "app", "api");

/** 递归收集 `app/api` 下所有 `route.ts`（相对 `app/api` 的路径＝登记键） */
function collectRoutes(dir: string, base: string = dir): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) out.push(...collectRoutes(full, base));
    else if (name === "route.ts") out.push(path.relative(base, full).replace(/\\/g, "/"));
  }
  return out.sort();
}

const readSrc = (rel: string) => readFileSync(path.join(API_ROOT, rel), "utf-8");

/** 挂了守卫的字面判据（与 `research/start/route.ts:16` 那一形同源） */
const hasGuard = (src: string) => src.includes("checkRequestOrigin(req)");

const hasPost = (src: string) => /export\s+async\s+function\s+POST\s*\(/.test(src);

/**
 * 没挂来源守卫的 POST＝**在册且带理由**。加一条要写清它靠什么守着；
 * 条目里那条路由若其实已经挂上了 ⇒ 反过来必须红（清单不许只会长大，同 `KNOWN_STALE_SNAPSHOTS`）。
 */
const KNOWN_UNGUARDED_POST: Record<string, string> = {
  "hotspots/ingest/route.ts":
    "ds 回调专用、浏览器不调；另有 `x-ingest-token` 守卫（`route.ts:9-12`，env 未设即放行）",
  "research/ingest/route.ts":
    "同上（`route.ts:8-13`）＝`x-ingest-token` 守着，不是裸的",
};

/** 判据抽成两枚纯函数（`srcOf` 可注入）＝真树与合成件跑的是**同一把尺**，不是两套逻辑 */
type Tree = (rel: string) => string;

const barePosts = (entries: string[], known: Record<string, string>, srcOf: Tree = readSrc) =>
  entries.filter((rel) => !hasGuard(srcOf(rel)) && !(known[rel] ?? "").trim());

const staleKnown = (known: Record<string, string>, srcOf: Tree = readSrc) =>
  Object.entries(known)
    .filter(([rel, reason]) => hasGuard(srcOf(rel)) || !reason.trim())
    .map(([rel]) => rel);

describe("CR10-12：来源守卫覆盖面尺（机制，不靠人逐轮数）", () => {
  const files = collectRoutes(API_ROOT);
  const postRoutes = files.filter((rel) => hasPost(readSrc(rel)));

  it("枚举件本身有牙齿＝`app/api` 下确实扫到了 route.ts 与 POST（空清单也算红）", () => {
    expect(files.length).toBeGreaterThan(10);
    expect(postRoutes.length).toBeGreaterThanOrEqual(8);
  });

  it("每一枚 POST：要么挂了 `checkRequestOrigin`，要么在 KNOWN 里带非空理由登记着", () => {
    const bare = barePosts(postRoutes, KNOWN_UNGUARDED_POST);
    expect(bare, `未挂来源守卫又没登记的 POST：${bare.join(" , ")}`).toEqual([]);
  });

  it("🔁 反向牙齿①＝KNOWN 清单条目若其实已挂上守卫、或理由写成空 ⇒ 必须红", () => {
    const stale = staleKnown(KNOWN_UNGUARDED_POST);
    expect(stale, `该从 KNOWN 里摘掉的条目：${stale.join(" , ")}`).toEqual([]);
  });

  it("🔁 反向牙齿②＝同一把尺跑合成件：裸 POST 会被点出来、已挂守卫的 KNOWN 条目会被点出来（不动生产文件的实钻）", () => {
    const guarded = 'export async function POST(req: any) {\n  const blocked = checkRequestOrigin(req);\n  await req.json();\n}';
    const bare = 'export async function POST(req: any) {\n  const body = await req.json();\n}';
    const tokenOnly = 'export async function POST(req: any) {\n  const t = process.env.INGEST_TOKEN;\n}';

    // 尺不常真：三种形状各判各的
    expect(hasGuard(guarded)).toBe(true);
    expect(hasGuard(bare)).toBe(false);
    expect(hasGuard(tokenOnly)).toBe(false);

    const tree = new Map<string, string>([
      ["ok/route.ts", guarded],
      ["naked/route.ts", bare],
      ["tokenized/route.ts", tokenOnly],
    ]);
    const src: Tree = (rel) => tree.get(rel)!;
    const posts = ["ok/route.ts", "naked/route.ts", "tokenized/route.ts"];

    expect(barePosts(posts, { "tokenized/route.ts": "另有 token 守卫" }, src)).toEqual(["naked/route.ts"]);
    expect(barePosts(posts, {}, src)).toEqual(["naked/route.ts", "tokenized/route.ts"]);
    // 登记了但理由写成空 ⇒ 同一条裸路由照样红（防空条目占位）
    expect(barePosts(["naked/route.ts"], { "naked/route.ts": "   " }, src)).toEqual(["naked/route.ts"]);
    // KNOWN 条目"复活"成已挂守卫 ⇒ 红（清单会自己瘦身）
    expect(staleKnown({ "tokenized/route.ts": "另有 token 守卫", "ok/route.ts": "已经挂上了" }, src)).toEqual([
      "ok/route.ts",
    ]);
  });

  it("挂了守卫的 POST，调用点必须排在第一次读 body 之前（挡在解析／花钱之前）", () => {
    const late: string[] = [];
    for (const rel of postRoutes) {
      const srcText = readSrc(rel);
      if (!srcText.includes("checkRequestOrigin(req)")) continue;
      const guardAt = srcText.indexOf("checkRequestOrigin(req)");
      const jsonAt = srcText.indexOf("req.json(");
      if (jsonAt !== -1 && jsonAt < guardAt) late.push(rel);
    }
    expect(late, `守卫排在读 body 之后的路由：${late.join(" , ")}`).toEqual([]);
  });

  it("本轮那四枚新守卫确实在场（逐枚点名，防「名单绿了但没人挂它」）", () => {
    for (const rel of [
      "chat/route.ts",
      "chat/sessions/route.ts",
      "search/click/route.ts",
      "watchlist/route.ts",
    ]) {
      expect(hasGuard(readSrc(rel)), `${rel} 应挂 checkRequestOrigin`).toBe(true);
    }
  });
});
