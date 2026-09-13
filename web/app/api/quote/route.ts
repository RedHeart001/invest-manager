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
    const res = await fetch(
      `${DATA_SERVICE_URL}/quote?type=${encodeURIComponent(type)}&code=${encodeURIComponent(code)}`,
      { cache: "no-store" },
    );
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: detail.detail ?? `data-service returned ${res.status}` },
        { status: 502 },
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
