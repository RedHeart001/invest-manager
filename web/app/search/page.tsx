import { Suspense } from "react";

import Breadcrumbs from "@/app/components/Breadcrumbs";
import SearchClient from "./search-client";

export default function SearchPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <Breadcrumbs items={[{ label: "首页", href: "/" }, { label: "搜索" }]} />
      <h1 className="mt-4 text-2xl font-bold tracking-tight">智能搜索</h1>
      <p className="mt-1 text-sm text-zinc-500">
        支持名称、代码、拼音、首字母、标签；选中分类可浏览全部产品，支持按涨幅 / 名称排序
      </p>
      <div className="mt-6">
        <Suspense fallback={<p className="text-sm text-zinc-400">加载中…</p>}>
          <SearchClient />
        </Suspense>
      </div>
      <p className="mt-10 text-xs text-zinc-400">
        行情数据来自免费源，可能有延迟，仅供参考，不构成投资建议。
      </p>
    </main>
  );
}
