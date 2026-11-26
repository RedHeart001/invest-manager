import { NextRequest, NextResponse } from "next/server";

import { PublishRejected, publishProducts, type ProductPayload } from "@/lib/sync";
import { checkRequestOrigin } from "@/lib/request-origin";
import { requireWriteToken } from "@/lib/guard";

/**
 * CR10-49：美股完整候选的幂等发布入口（DS 持久化任务专用）。
 *
 * 为什么单独一条内部路由而不是继续走 `POST /api/sync?type=us`：
 * - 候选由 DS 按 `snapshotId` 采好后才 POST 过来，Web 不再回源拉 923 页；
 * - 发布账本 `Product_snapshot_publication` 与 Product 替换同事务 ⇒ “Web 已提交但
 *   响应丢失”的重试只回执、不重复写库；
 * - 完整性/缩水/空载荷保护与普通同步共用 `publishProducts`，不另立一套。
 *
 * 这不是给浏览器用的：同样要求 WRITE_TOKEN（未设时本机默认放行）与同源检查。
 */
export const maxDuration = 300;

const SNAPSHOT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;
const MAX_PRODUCTS = 30_000;

type BadRequest = { error: string };

function asString(value: unknown, max: number): string | null {
  if (typeof value !== "string") return null;
  const s = value.trim();
  return s && s.length <= max ? s : null;
}

const INVALID = Symbol("invalid");

function asOptionalString(value: unknown, max: number): string | null | typeof INVALID {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string") return INVALID;
  const s = value.trim();
  return s.length <= max ? s : INVALID;
}

function validatePayload(body: unknown): { payload: ProductPayload[]; snapshotId: string } | BadRequest {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { error: "body must be a JSON object" };
  }
  const obj = body as Record<string, unknown>;
  const snapshotId = asString(obj.snapshotId, 80);
  if (!snapshotId || !SNAPSHOT_ID_RE.test(snapshotId)) {
    return { error: "invalid snapshotId" };
  }
  if (obj.acquisitionComplete !== true) {
    // 完整性不是“默认通过”：DS 必须显式声明这次候选是完整采集。
    return { error: "acquisitionComplete must be true" };
  }
  if (
    obj.intentionalSubset === true &&
    obj.productPolicySubset !== true
  ) {
    return { error: "non-product subset cannot bypass shrink guard" };
  }
  if (!Array.isArray(obj.products)) {
    return { error: "products must be an array" };
  }
  if (obj.products.length === 0) {
    return { error: "empty payload from data-service, existing data kept" };
  }
  if (obj.products.length > MAX_PRODUCTS) {
    return { error: `too many products (${obj.products.length} > ${MAX_PRODUCTS})` };
  }
  if (obj.count !== undefined && obj.count !== obj.products.length) {
    return { error: `count ${String(obj.count)} != products.length ${obj.products.length}` };
  }

  const products: ProductPayload[] = [];
  for (let i = 0; i < obj.products.length; i += 1) {
    const raw = obj.products[i];
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return { error: `products[${i}] must be an object` };
    }
    const p = raw as Record<string, unknown>;
    if (p.type !== "us") {
      return { error: `products[${i}].type must be "us"` };
    }
    const code = asString(p.code, 40);
    if (!code) return { error: `products[${i}].code is invalid` };
    const name = asString(p.name, 200);
    if (!name) return { error: `products[${i}].name is invalid` };
    const pinyin = asOptionalString(p.pinyin, 200);
    if (pinyin === INVALID) return { error: `products[${i}].pinyin is invalid` };
    const pinyinInitials = asOptionalString(p.pinyinInitials, 200);
    if (pinyinInitials === INVALID) {
      return { error: `products[${i}].pinyinInitials is invalid` };
    }
    const exchange = asOptionalString(p.exchange, 40);
    if (exchange === INVALID) return { error: `products[${i}].exchange is invalid` };
    let tags: string[] | null | undefined;
    if (p.tags === undefined) {
      tags = undefined;
    } else if (p.tags === null) {
      tags = null;
    } else if (Array.isArray(p.tags)) {
      if (p.tags.length > 100) return { error: `products[${i}].tags is too long` };
      const cleaned: string[] = [];
      for (const tag of p.tags) {
        const s = asString(tag, 100);
        if (!s) return { error: `products[${i}].tags contains an invalid tag` };
        cleaned.push(s);
      }
      tags = cleaned;
    } else {
      return { error: `products[${i}].tags must be an array` };
    }
    products.push({ type: "us", code, name, pinyin, pinyinInitials, exchange, tags });
  }
  return { payload: products, snapshotId };
}

export async function POST(req: NextRequest) {
  const blocked = checkRequestOrigin(req);
  if (blocked) {
    return NextResponse.json({ error: blocked }, { status: 403 });
  }
  const unauthorized = requireWriteToken(req);
  if (unauthorized) {
    return NextResponse.json({ error: unauthorized }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  const validated = validatePayload(body);
  if ("error" in validated) {
    return NextResponse.json({ ok: false, ...validated }, { status: 400 });
  }

  const obj = body as Record<string, unknown>;
  const started = Date.now();
  try {
    const outcome = await publishProducts(
      "us",
      {
        count: validated.payload.length,
        products: validated.payload,
        source: typeof obj.source === "string" ? obj.source : undefined,
        degraded: typeof obj.degraded === "boolean" ? obj.degraded : undefined,
        note: typeof obj.note === "string" ? obj.note : undefined,
        intentionalSubset: typeof obj.intentionalSubset === "boolean" ? obj.intentionalSubset : undefined,
        acquisitionComplete: true,
        productPolicySubset:
          typeof obj.productPolicySubset === "boolean" ? obj.productPolicySubset : undefined,
        declaredCount: typeof obj.declaredCount === "number" ? obj.declaredCount : undefined,
        acquiredCount: typeof obj.acquiredCount === "number" ? obj.acquiredCount : undefined,
        snapshotId: validated.snapshotId,
      },
      { snapshotId: validated.snapshotId },
    );
    if (!outcome.ok) {
      // 可预期拒绝（缩水/空载荷/完整性）回 4xx：DS 不该重试同一份；
      // 意外故障回 5xx：DS 按 snapshotId 幂等重试。
      return NextResponse.json(
        { ok: false, error: outcome.error, rejected: outcome.rejected },
        { status: outcome.rejected ? 400 : 500 },
      );
    }
    return NextResponse.json({
      ok: true,
      type: "us",
      snapshotId: outcome.snapshotId,
      count: outcome.count,
      alreadyPublished: outcome.alreadyPublished === true,
      note: outcome.note,
      tookMs: Date.now() - started,
    });
  } catch (e) {
    // 异常细节可能含路径/SQL，只写服务端日志，回固定文案
    console.error(
      "[sync/us-snapshot] publish failed:",
      e instanceof PublishRejected ? e.message : e instanceof Error ? e.message : e,
    );
    return NextResponse.json({ ok: false, error: "us snapshot publish failed" }, { status: 500 });
  }
}
