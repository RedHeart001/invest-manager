"use client";

// G5（批次 D）：自选产品按钮——详情页可加入/移除自选（Watchlist 加权来源）。
// 此前 Watchlist 表只被搜索排序读取，无写入入口（半成品）。
// R5：操作有可见 pending 态；失败如实提示。

import { useEffect, useState } from "react";

export default function WatchButton({
  type,
  code,
  name,
}: {
  type: string;
  code: string;
  name: string;
}) {
  const [watched, setWatched] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/watchlist")
      .then((r) => r.json())
      .then((b: { items?: { type: string; code: string }[] }) => {
        if (!alive) return;
        setWatched(Boolean(b.items?.some((x) => x.type === type && x.code === code)));
      })
      .catch(() => {
        if (alive) setWatched(false);
      });
    return () => {
      alive = false;
    };
  }, [type, code]);

  const toggle = async () => {
    if (pending || watched === null) return;
    setPending(true);
    setError(null);
    try {
      const res = watched
        ? await fetch(`/api/watchlist?type=${type}&code=${code}`, { method: "DELETE" })
        : await fetch("/api/watchlist", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type, code, name }),
          });
      if (!res.ok) {
        const b = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(b.error ?? `HTTP ${res.status}`);
      }
      setWatched(!watched);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setPending(false);
    }
  };

  return (
    <span className="inline-flex items-center gap-2">
      <button
        onClick={() => void toggle()}
        disabled={pending || watched === null}
        className={`rounded-lg border px-3 py-1 text-xs transition disabled:opacity-50 ${
          watched
            ? "border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100"
            : "border-zinc-300 text-zinc-600 hover:bg-zinc-50"
        }`}
        aria-pressed={watched ?? undefined}
      >
        {pending ? "处理中…" : watched ? "★ 已自选" : "☆ 加自选"}
      </button>
      {error && <span className="text-xs text-red-500">{error}</span>}
    </span>
  );
}
