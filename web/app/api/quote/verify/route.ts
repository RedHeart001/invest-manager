import { NextRequest, NextResponse } from "next/server";

// CR7-3/B1（2026-09-24 拍板方案 ①）：双源交叉验证的 BFF 入口。
// 详情页「双源核对」按钮按需触发——不做默认调用，避免每次浏览都放大
// 外部请求量（ds /quote/verified 端点本身就是按需设计，见 chain.py docstring）。
// 约束（账本批次 B）：① 非法 code/type 在进 ds 之前 400（C5 同口径）；
// ② 备源不可用/验证失败按 R16 如实透传 note，不静默只显主源价。
import { CODE_SET, QUOTE_TYPES } from "@/lib/validate";

const DATA_SERVICE_URL =
  process.env.DATA_SERVICE_URL ?? "http://localhost:8000";

export async function GET(req: NextRequest) {
  const type = req.nextUrl.searchParams.get("type") ?? "stock";
  const code = req.nextUrl.searchParams.get("code");

  if (!QUOTE_TYPES.includes(type as (typeof QUOTE_TYPES)[number])) {
    return NextResponse.json({ error: `unsupported type: ${type}` }, { status: 400 });
  }
  if (!code || !CODE_SET.test(code)) {
    return NextResponse.json({ error: "invalid code" }, { status: 400 });
  }

  try {
    const res = await fetch(
      `${DATA_SERVICE_URL}/quote/verified?type=${encodeURIComponent(type)}&code=${encodeURIComponent(code)}`,
      { cache: "no-store", signal: AbortSignal.timeout(30_000) },
    );
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      const status = res.status === 400 || res.status === 501 ? res.status : 502;
      return NextResponse.json(
        { error: detail.detail ?? `data-service returned ${res.status}` },
        { status },
      );
    }
    return NextResponse.json(await res.json());
  } catch (e) {
    const msg =
      (e as { name?: string } | null)?.name === "TimeoutError"
        ? "data-service timeout（双源核对超时）"
        : "data-service unreachable，请确认已启动（uvicorn app.main:app --port 8000）";
    return NextResponse.json({ error: msg }, { status: 503 });
  }
}
