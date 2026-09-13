"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// 顶部一级导航：按当前路径高亮（子页面归属其所属的一级功能）
const ITEMS: { href: string; label: string; isActive: (p: string) => boolean }[] = [
  { href: "/", label: "首页", isActive: (p) => p === "/" },
  {
    href: "/search",
    label: "搜索",
    // 搜索结果进入的产品详情页也属于「搜索」这一功能
    isActive: (p) => p.startsWith("/search") || p.startsWith("/product"),
  },
  {
    href: "/chat",
    label: "智能助手",
    isActive: (p) => p.startsWith("/chat"),
  },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-3">
      <Link href="/" className="font-semibold tracking-tight">
        Invest Manager
      </Link>
      <div className="flex items-center gap-5">
        {ITEMS.map((item) => {
          const active = item.isActive(pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`-mb-px border-b-2 pb-1 text-sm transition ${
                active
                  ? "border-zinc-900 font-medium text-zinc-900"
                  : "border-transparent text-zinc-500 hover:text-zinc-900"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
