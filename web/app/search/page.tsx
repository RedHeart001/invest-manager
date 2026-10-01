import { Suspense } from "react";

import SearchClient from "./search-client";

export default function SearchPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      {/* CR8-5：删面包屑——中间那级「搜索」是硬编码的谎报，一级入口本就由顶部导航承担。
          与 search/loading.tsx 成对改，否则导航期间面包屑会闪一下。 */}
      <h1 className="text-2xl font-bold tracking-tight">智能搜索</h1>
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
