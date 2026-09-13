import Link from "next/link";

export type Crumb = { label: string; href?: string };

// 面包屑：一级功能 → 当前子页面（最后一项不可点击）
export default function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav
      aria-label="面包屑"
      className="flex flex-wrap items-center gap-1.5 text-sm text-zinc-500"
    >
      {items.map((c, i) => (
        <span key={`${c.label}-${i}`} className="flex items-center gap-1.5">
          {i > 0 && (
            <span className="text-zinc-300" aria-hidden>
              /
            </span>
          )}
          {c.href && i < items.length - 1 ? (
            <Link href={c.href} className="hover:text-zinc-900 hover:underline">
              {c.label}
            </Link>
          ) : (
            <span className="truncate text-zinc-900">{c.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
