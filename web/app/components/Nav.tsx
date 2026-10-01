"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { parseFrom, readStoredFrom, storeFrom, type FromKey } from "@/lib/provenance";

// 顶部一级导航。一级路由按前缀点亮；`/product/**` **不再**并入「搜索」——
// 产品页有四个入口、分属三个一级（见 `lib/provenance.ts` 的说明），前缀派生的"父级"
// 只能对其中一个说实话。产品页点亮哪一项由**来路**（`?from=`）决定，
// 没有来路时退回本会话上一次的来路，两者都没有就不点亮。
const ITEMS: { key: FromKey; href: string; label: string }[] = [
  { key: "home", href: "/", label: "首页" },
  { key: "search", href: "/search", label: "搜索" },
  { key: "chat", href: "/chat", label: "智能助手" },
];

export default function Nav() {
  const pathname = usePathname();
  const params = useSearchParams();
  const onProduct = pathname.startsWith("/product");
  const urlFrom = onProduct ? parseFrom(params.get("from")) : null;
  const [storedFrom, setStoredFrom] = useState<FromKey | null>(null);

  useEffect(() => {
    if (!onProduct) return;
    if (urlFrom) {
      storeFrom(urlFrom);
      setStoredFrom(urlFrom);
      return;
    }
    setStoredFrom(readStoredFrom());
  }, [onProduct, urlFrom]);

  const activeKey = onProduct ? urlFrom ?? storedFrom : null;

  const isActive = (item: (typeof ITEMS)[number]) =>
    onProduct
      ? item.key === activeKey
      : item.href === "/"
        ? pathname === "/"
        : pathname.startsWith(item.href);

  return (
    <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-3">
      <Link href="/" className="font-semibold tracking-tight">
        Invest Manager
      </Link>
      <div className="flex items-center gap-5">
        {ITEMS.map((item) => {
          const active = isActive(item);
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
