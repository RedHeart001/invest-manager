import { NextRequest, NextResponse } from "next/server";

import { browseProducts, normalizeBrowse } from "@/lib/browse";
import { searchProducts } from "@/lib/search";

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get("q") ?? "";
  const typeParam = req.nextUrl.searchParams.get("type") ?? "all";
  const limitParam = Number(req.nextUrl.searchParams.get("limit") ?? "20");
  const limit = Number.isFinite(limitParam) ? Math.min(Math.max(limitParam, 1), 50) : 20;
  const sort = req.nextUrl.searchParams.get("sort"); // relevance(默认) | changePct | name
  const order = req.nextUrl.searchParams.get("order") === "asc" ? "asc" : "desc";
  const started = Date.now();

  // 浏览模式（R14）：无关键词 + 选中分类 → 展示该类全部产品，支持涨幅/名称/代码排序
  if (!q.trim()) {
    const norm = normalizeBrowse({
      sort: req.nextUrl.searchParams.get("browse-sort"),
      order: req.nextUrl.searchParams.get("order"),
      page: req.nextUrl.searchParams.get("page"),
      pageSize: req.nextUrl.searchParams.get("pageSize"),
    });
    try {
      const data = await browseProducts({
        type: typeParam,
        sort: norm.sort,
        order: norm.order,
        page: norm.page,
        pageSize: norm.pageSize,
      });
      return NextResponse.json({ browse: true, type: typeParam, ...data });
    } catch (e) {
      return NextResponse.json(
        { error: e instanceof Error ? e.message : "browse failed" },
        { status: 500 },
      );
    }
  }

  try {
    let results = await searchProducts({
      q,
      type: typeParam === "all" ? undefined : typeParam,
      limit,
    });
    // 查询模式可选排序：涨幅 / 名称（默认保持贴合度）
    if (sort === "changePct") {
      results = [...results].sort((a, b) =>
        order === "asc"
          ? (a.changePct ?? Infinity) - (b.changePct ?? Infinity)
          : (b.changePct ?? -Infinity) - (a.changePct ?? -Infinity),
      );
    } else if (sort === "name") {
      results = [...results].sort((a, b) => a.name.localeCompare(b.name, "zh"));
    }
    return NextResponse.json({
      q,
      type: typeParam,
      count: results.length,
      tookMs: Date.now() - started,
      results,
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "search failed" },
      { status: 500 },
    );
  }
}
