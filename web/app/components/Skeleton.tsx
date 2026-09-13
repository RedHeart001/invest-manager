// 骨架屏基础组件：统一加载态视觉，避免把"加载中"误判为"功能坏了"

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded bg-zinc-200/70 ${className}`} aria-hidden />
  );
}

/** 搜索结果列表骨架（行数与常见结果数接近，减少跳变） */
export function ResultListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <ul
      className="divide-y divide-zinc-100 overflow-hidden rounded-xl border border-zinc-200 bg-white"
      aria-busy="true"
      aria-label="搜索结果加载中"
    >
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className="flex items-center justify-between gap-4 px-4 py-3">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-14" />
              <Skeleton className="h-4 w-12 rounded" />
            </div>
            <Skeleton className="h-3 w-20" />
          </div>
          <div className="shrink-0 space-y-2 text-right">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-3 w-12" />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** 详情页骨架 */
export function ProductDetailSkeleton() {
  return (
    <main className="mx-auto max-w-4xl px-6 pt-4 pb-10" aria-busy="true" aria-label="详情加载中">
      <Skeleton className="h-4 w-20" />

      <div className="mt-4 flex items-baseline gap-3">
        <Skeleton className="h-7 w-32" />
        <Skeleton className="h-4 w-16" />
        <Skeleton className="h-5 w-14 rounded" />
      </div>
      <div className="mt-3 flex gap-2">
        <Skeleton className="h-4 w-12 rounded" />
        <Skeleton className="h-4 w-16 rounded" />
      </div>

      <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-5">
        <div className="flex items-baseline gap-4">
          <Skeleton className="h-9 w-28" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="ml-auto h-3 w-40" />
        </div>
      </div>

      <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-5">
        <div className="flex items-center gap-3">
          <Skeleton className="h-6 w-16" />
          <Skeleton className="h-6 w-16" />
          <Skeleton className="h-6 w-16" />
          <Skeleton className="ml-auto h-6 w-32" />
        </div>
        <Skeleton className="mt-5 h-56 w-full" />
      </div>
    </main>
  );
}
