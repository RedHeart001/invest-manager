import Link from "next/link";

import HotspotFeed from "./HotspotFeed";
import { listDigests } from "@/lib/hotspots";

// 首页 = 市场热点 dashboard（PLAN M1）：卡片流 + SSE 实时推送 + 手动触发
export const dynamic = "force-dynamic";

export default async function Home() {
  // 代码审查修复：listDigests 抛错（DB 异常）会让整个 dashboard 白屏，
  // 违反"永不空白"约定 → 降级为空态 + 提示
  let date: string | null = null;
  let rows: Awaited<ReturnType<typeof listDigests>>["rows"] = [];
  let loadError: string | null = null;
  try {
    ({ date, rows } = await listDigests({ limit: 30 }));
  } catch (e) {
    loadError = e instanceof Error ? e.message : "热点数据加载失败";
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      {loadError && (
        <div className="mb-4 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          热点数据加载失败：{loadError}（页面其余功能不受影响）
        </div>
      )}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight">市场热点</h1>
        <Link href="/search" className="text-sm text-blue-600 hover:underline">
          去搜索产品 →
        </Link>
      </div>
      <p className="mt-1 text-sm text-zinc-500">
        工作日盘前 08:30 / 盘后 16:30 自动抓取财经新闻 → 结构化板块标签 →
        板块成分映射相关产品；相关产品点击进详情页
      </p>

      <div className="mt-6">
        <HotspotFeed initialDate={date} initialRows={rows} />
      </div>

      <p className="mt-10 text-xs text-zinc-400">
        热点由搜索/新闻源自动抓取并结构化，相关产品来自板块成分映射与板块名基金匹配；
        内容仅供参考，不构成投资建议。
      </p>
    </main>
  );
}
