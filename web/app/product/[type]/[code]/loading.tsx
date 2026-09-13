import Breadcrumbs from "@/app/components/Breadcrumbs";
import { ProductDetailSkeleton } from "@/app/components/Skeleton";

// 路由级加载态：客户端跳转到详情页时立即显示，避免"点了没反应"的错觉
export default function Loading() {
  return (
    <>
      <div className="mx-auto max-w-4xl px-6 pt-8">
        <Breadcrumbs
          items={[{ label: "首页", href: "/" }, { label: "搜索", href: "/search" }, { label: "加载中…" }]}
        />
      </div>
      <ProductDetailSkeleton />
    </>
  );
}
