import { NextRequest, NextResponse } from "next/server";

import { QUOTE_TIMEOUT_MS, unreachableMessage } from "@/lib/data-service";
import { CODE_SET, QUOTE_TYPES } from "@/lib/validate";

const DATA_SERVICE_URL =
  process.env.DATA_SERVICE_URL ?? "http://localhost:8000";

// BFF 代理行情查询：浏览器 → /api/quote → data-service /quote
export async function GET(req: NextRequest) {
  const type = req.nextUrl.searchParams.get("type") ?? "stock";
  const code = req.nextUrl.searchParams.get("code");
  // CR7-6/C5（2026-09-25）：code/type 白名单前移（同 /api/kline，防任意串耗东财额度）
  if (!QUOTE_TYPES.includes(type as (typeof QUOTE_TYPES)[number])) {
    return NextResponse.json({ error: `unsupported type: ${type}` }, { status: 400 });
  }
  if (!code || !CODE_SET.test(code)) {
    return NextResponse.json({ error: "invalid code" }, { status: 400 });
  }

  try {
    // CR4（2026-09-15 review）：全站其余 ds 调用都走 dsGet（内置超时），
    // 此路由此前裸 fetch 无 signal → data-service 挂起时悬挂到 OS TCP 超时。
    //
    // #63（2026-10-12）：预算从 15s 抬到 30s＝全站既有口径（`QUOTE_TIMEOUT_MS`，
    // 与 `dsGet` 默认、`app/api/quote/verify/route.ts` 一致）。理由＝ds 侧一条
    // stock `get_quote` 的最坏路径是「`_em_request` 的 `acquire()` 默认 20s
    // （`data-service/app/utils/limiter.py:136`）＋多 host 两轮 × 每发 15s
    // （`data-service/app/providers/akshare_provider.py:303-309`）」，15s 与它差
    // 一个量级 ⇒ 慢响应被掐断，又被 catch 回成「服务没启动」（违 R16）。
    // 10-11 夜 R13 实测字面＝`code=600519 503 in 15792ms`，ds 侧同发 12 次全 200。
    const res = await fetch(
      `${DATA_SERVICE_URL}/quote?type=${encodeURIComponent(type)}&code=${encodeURIComponent(code)}`,
      { cache: "no-store", signal: AbortSignal.timeout(QUOTE_TIMEOUT_MS) },
    );
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      // CR5-P2（2026-09-17 review）：此前把 data-service 的一切非 2xx 压成 502，
      // 使 400（非法 type）/501（不支持）与"上游挂"无法区分。按其余路由口径透传。
      const status = res.status === 400 || res.status === 501 ? res.status : 502;
      return NextResponse.json(
        { error: detail.detail ?? `data-service returned ${res.status}` },
        { status },
      );
    }
    return NextResponse.json(await res.json());
  } catch (e) {
    // #63（2026-10-12）：此前是裸 `catch {}` + 固定文案，把超时也报成「服务没启动」。
    // 改用 `data-service.ts` 既有的两分法（超时 vs 连不上），R16：失败原因如实。
    return NextResponse.json(
      { error: unreachableMessage(e, QUOTE_TIMEOUT_MS) },
      { status: 503 },
    );
  }
}
