import { ProductDetailSkeleton } from "@/app/components/Skeleton";

// 路由级加载态：客户端跳转到详情页时立即显示，避免"点了没反应"的错觉
// CR8-5：与详情页 page.tsx 成对删面包屑（只改 page 不改 loading，导航期间会闪一下）。
// 外层那个只为放面包屑而存在的 div 一并去掉——骨架自带 <main>，留着会变成双 main。
export default function Loading() {
  return <ProductDetailSkeleton />;
}
