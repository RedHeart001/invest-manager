"use client";

// R18（2026-11-01 自选清单页）：清单里逐条移除。
//
// 为什么单独一枚组件而不是直接复用 `WatchButton`：那个是"加入/移除"二态开关，它的初始
// 状态靠再发一次 `GET /api/watchlist` 探测——清单页**已经**知道这一条在自选里，
// 让每一行再打一次全表查询既是多余的出网，也会让首屏闪一下"加自选"。
// 这里只保留单向的"移除"。
//
// R5：有可见 pending；R16：失败如实显示原因，不静默吞掉（吞掉的后果是"点了没反应"，
// 而用户无法区分"删掉了"和"没删掉"）。
// 成功后 `router.refresh()` 让 Server Component 重取——不在这里局部 splice 状态，
// 否则屏幕上那一行没了、库里的行还在的错位没有任何东西能纠正。

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

export default function WatchRemoveButton({ type, code }: { type: string; code: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const remove = async () => {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const res = await fetch(`/api/watchlist?type=${type}&code=${code}`, { method: "DELETE" });
      if (!res.ok) {
        const b = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(b.error ?? `HTTP ${res.status}`);
      }
      startTransition(() => router.refresh());
    } catch (e) {
      setError(e instanceof Error ? e.message : "移除失败");
    } finally {
      setPending(false);
    }
  };

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={() => void remove()}
        disabled={pending}
        aria-label={`从自选移除 ${code}`}
        className="rounded-lg border border-zinc-300 px-2.5 py-1 text-xs text-zinc-600 transition hover:bg-zinc-50 disabled:opacity-50"
      >
        {pending ? "移除中…" : "移除"}
      </button>
      {error && <span className="text-xs text-red-500">{error}</span>}
    </span>
  );
}
