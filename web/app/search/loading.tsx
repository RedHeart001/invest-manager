import Breadcrumbs from "@/app/components/Breadcrumbs";
import { ResultListSkeleton, Skeleton } from "@/app/components/Skeleton";

export default function Loading() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <Breadcrumbs items={[{ label: "首页", href: "/" }, { label: "搜索" }]} />
      <h1 className="mt-4 text-2xl font-bold tracking-tight">智能搜索</h1>
      <p className="mt-1 text-sm text-zinc-500">
        支持名称、代码、拼音、首字母、标签；结果按贴合度排序
      </p>

      <div className="mt-6 space-y-3">
        <Skeleton className="h-11 w-full rounded-lg" />
        <div className="flex gap-2">
          <Skeleton className="h-7 w-14 rounded-full" />
          <Skeleton className="h-7 w-14 rounded-full" />
          <Skeleton className="h-7 w-14 rounded-full" />
          <Skeleton className="h-7 w-14 rounded-full" />
          <Skeleton className="h-7 w-16 rounded-full" />
        </div>
        <div className="pt-2">
          <ResultListSkeleton rows={5} />
        </div>
      </div>
    </main>
  );
}
