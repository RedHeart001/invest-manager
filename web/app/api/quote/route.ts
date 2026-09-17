import { NextRequest, NextResponse } from "next/server";

const DATA_SERVICE_URL =
  process.env.DATA_SERVICE_URL ?? "http://localhost:8000";

// BFF 代理行情查询：浏览器 → /api/quote → data-service /quote
export async function GET(req: NextRequest) {
  const type = req.nextUrl.searchParams.get("type") ?? "stock";
  const code = req.nextUrl.searchParams.get("code");
  if (!code) {
    return NextResponse.json({ error: "code is required" }, { status: 400 });
  }

  try {
    // CR4（2026-09-15 review）：全站其余 ds 调用都走 dsGet（内置 15s 超时），
    // 此路由此前裸 fetch 无 signal → data-service 挂起时悬挂到 OS TCP 超时。补 15s。
    const res = await fetch(
      `${DATA_SERVICE_URL}/quote?type=${encodeURIComponent(type)}&code=${encodeURIComponent(code)}`,
      { cache: "no-store", signal: AbortSignal.timeout(15_000) },
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
  } catch {
    return NextResponse.json(
      { error: "data-service unreachable，请确认已启动（uvicorn app.main:app --port 8000）" },
      { status: 503 },
    );
  }
}
