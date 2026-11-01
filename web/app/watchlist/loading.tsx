import Link from "next/link";

import { Skeleton } from "@/app/components/Skeleton";

// R5（加载必须有反馈）＋ R18（2026-11-01 自选清单页）：路由级骨架屏。
// 与 `search/loading.tsx` 同形态——标题＋说明先落地，条目区用骨架占位，
// 免得"点了自选之后半秒空白"被当成功能坏了。
//
// 骨架行数取 4：自选通常是个位数，占位过多反而在加载完成时跳得厉害。
export default function Loading() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-bold tracking-tight">自选</h1>
      <p className="mt-1 text-sm text-zinc-500">
        逐个加入自选的标的清单；行情为实时取数，取不到时显示 --
      </p>

      <div className="mt-6 space-y-4">
        {[0, 1].map((g) => (
          <div key={g} className="rounded-xl border border-zinc-200 bg-white">
            <div className="border-b border-zinc-100 px-4 py-3">
              <Skeleton className="h-4 w-16" />
            </div>
            <ul className="divide-y divide-zinc-100">
              {Array.from({ length: 4 }).map((_, i) => (
                <li key={i} className="flex items-center justify-between gap-4 px-4 py-3">
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex items-center gap-2">
                      <Skeleton className="h-4 w-28" />
                      <Skeleton className="h-3 w-14" />
                    </div>
                  </div>
                  <Skeleton className="h-4 w-16" />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </main>
  );
}
