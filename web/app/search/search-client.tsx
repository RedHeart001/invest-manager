"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ResultListSkeleton } from "@/app/components/Skeleton";
import { getCachedSearch, getLastSearch, setCachedSearch } from "@/lib/search-cache";
import type { SearchResult } from "@/lib/search";

const TABS = [
  { key: "all", label: "全部" },
  { key: "stock", label: "股票" },
  { key: "fund", label: "基金" },
  { key: "bond", label: "债券" },
  { key: "crypto", label: "虚拟币" },
] as const;

type Result = SearchResult;

const TYPE_LABEL: Record<string, string> = {
  stock: "股票",
  fund: "基金",
  bond: "债券",
  crypto: "虚拟币",
  hk: "港股",
  us: "美股",
};

// 排序选项：值 = sort:order；relevance 仅查询模式可选
const SORT_OPTIONS = [
  { value: "changePct:desc", label: "涨幅从高到低", browse: true, query: true },
  { value: "changePct:asc", label: "涨幅从低到高", browse: true, query: true },
  { value: "name:asc", label: "按名称", browse: true, query: true },
  { value: "code:asc", label: "按代码", browse: true, query: false },
  { value: "relevance", label: "按贴合度", browse: false, query: true },
] as const;

const PAGE_SIZE = 20;

export default function SearchClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const [type, setType] = useState<string>(searchParams.get("type") ?? "all");
  // 代码审查修复：从 URL 还原排序与页码（browse 模式会 router.replace 出这些参数，
  // 分享链接 / 刷新进入时此前硬编码回 changePct:desc / 第 1 页）
  const [sortSel, setSortSel] = useState<string>(searchParams.get("sort") ?? "changePct:desc");
  const [page, setPage] = useState<number>(Number(searchParams.get("page") ?? "1") || 1);

  const [results, setResults] = useState<Result[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  // 浏览模式元信息（R14）
  const [browseTotal, setBrowseTotal] = useState(0);
  const [browsePages, setBrowsePages] = useState(1);

  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const restoredRef = useRef(false);

  const query = q.trim();
  const browseMode = query === "";

  // 挂载后（避开 hydration）：URL 无查询参数时恢复上次搜索现场，
  // 使"返回上一级"不会丢失搜索条件与结果
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    if (!searchParams.get("q")) {
      const last = getLastSearch();
      if (last) {
        setQ(last.q);
        setType(last.type);
      }
    }
  }, [searchParams]);

  // 切换分类/排序时回到第 1 页
  useEffect(() => {
    setPage(1);
  }, [type, sortSel]);

  useEffect(() => {
    // ---------- 浏览模式（R14）：无关键词 + 分类 → 全量产品列表 ----------
    if (browseMode) {
      const [sort, order] = sortSel.split(":");
      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;
      setLoading(true);
      setError(null);
      setSearched(true);
      fetch(
        `/api/search?type=${type}&browse-sort=${sort}&order=${order}&page=${page}&pageSize=${PAGE_SIZE}`,
        { signal: controller.signal },
      )
        .then(async (res) => {
          const body = await res.json();
          if (!res.ok) throw new Error(body.error ?? res.statusText);
          setResults((body.items ?? []) as Result[]);
          setBrowseTotal(body.total ?? 0);
          setBrowsePages(body.pages ?? 1);
          router.replace(
            `/search?type=${type}&sort=${sortSel}&page=${page}`,
          );
        })
        .catch((e: Error) => {
          if (e.name !== "AbortError") setError(e.message);
        })
        .finally(() => {
          // 代码审查修复：仅当仍是最新请求时才收尾 loading，
          // 否则旧请求的 finally 会关掉新请求的骨架屏
          if (abortRef.current === controller) setLoading(false);
        });
      return () => controller.abort();
    }

    // ---------- 查询模式（P1 逻辑 + 可选排序） ----------
    if (!query) {
      setResults([]);
      setSearched(false);
      setError(null);
      return;
    }

    // 命中缓存：立即还原上次结果（返回上一级时不再空屏）
    const cached = getCachedSearch(query, type);
    if (cached) {
      setResults(cached.results);
      setSearched(true);
      setError(null);
      if (cached.fresh) {
        setLoading(false);
        return;
      }
    } else {
      setLoading(true);
    }

    const timer = setTimeout(
      () => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setError(null);
        const sortParam =
          sortSel === "changePct:desc"
            ? "&sort=changePct&order=desc"
            : sortSel === "changePct:asc"
              ? "&sort=changePct&order=asc"
              : sortSel === "name:asc"
                ? "&sort=name"
                : "";
        fetch(
          `/api/search?q=${encodeURIComponent(query)}&type=${type}&limit=30${sortParam}`,
          { signal: controller.signal },
        )
          .then(async (res) => {
            const body = await res.json();
            if (!res.ok) throw new Error(body.error ?? res.statusText);
            const next = (body.results ?? []) as Result[];
            setResults(next);
            setSearched(true);
            setCachedSearch(query, type, next);
            // 同步 URL，便于分享/刷新/返回时保留查询
            router.replace(`/search?q=${encodeURIComponent(query)}&type=${type}`);
          })
          .catch((e: Error) => {
            if (e.name !== "AbortError") setError(e.message);
          })
          .finally(() => {
          // 代码审查修复：仅当仍是最新请求时才收尾 loading，
          // 否则旧请求的 finally 会关掉新请求的骨架屏
          if (abortRef.current === controller) setLoading(false);
        });
      },
      cached ? 0 : 250,
    );
    return () => {
      clearTimeout(timer);
      // CR4（P3）：清理时同步 abort 在途请求——此前只 clearTimeout，已发出的旧
      // fetch 要等下一个 timer 触发才被 abort，窗口内旧响应会瞬态 setResults。
      abortRef.current?.abort();
    };
  }, [q, type, sortSel, page, browseMode, query, router]);

  function openProduct(r: Result) {
    const key = `${r.type}:${r.code}`;
    if (pendingKey) return; // 防重复点击
    setPendingKey(key);
    fetch("/api/search/click", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query || `browse:${type}`, type: r.type, code: r.code }),
      keepalive: true,
    }).catch(() => {});
    router.push(`/product/${r.type}/${r.code}`);
    // 兜底：导航异常时 2s 后恢复可点击
    setTimeout(() => setPendingKey(null), 2000);
  }

  const sortOptions = SORT_OPTIONS.filter((o) =>
    browseMode ? o.browse : o.query,
  );

  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="搜索名称 / 代码 / 拼音 / 首字母，如：贵州茅台、600519、gzmt、新能源；留空并选择分类可浏览全部产品"
        className="w-full rounded-lg border border-zinc-300 bg-white px-4 py-3 text-sm outline-none focus:border-zinc-500"
      />

      <div className="mt-3 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setType(t.key)}
            className={`rounded-full px-3 py-1 text-sm transition ${
              type === t.key
                ? "bg-zinc-900 text-white"
                : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-4 flex items-center justify-between">
        <p className="text-xs text-zinc-400" data-testid="result-meta">
          {browseMode
            ? searched && !loading
              ? `共 ${browseTotal} 条`
              : ""
            : searched && !loading
              ? `${results.length} 条结果`
              : ""}
        </p>
        <label className="flex items-center gap-2 text-xs text-zinc-500">
          排序
          <select
            value={sortSel}
            onChange={(e) => setSortSel(e.target.value)}
            className="rounded border border-zinc-200 bg-white px-2 py-1 text-xs"
          >
            {sortOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-3">
        {loading && <ResultListSkeleton rows={6} />}
        {error && <p className="text-sm text-red-500">{error}</p>}

        {!loading && !error && searched && results.length === 0 && (
          <p className="text-sm text-zinc-400">
            {browseMode ? (
              "该分类暂无产品数据（可能未同步或数据源不可达）。"
            ) : (
              <>
                没有匹配结果。数据是否已同步？可先执行
                <code className="mx-1 rounded bg-zinc-100 px-1.5 py-0.5">
                  curl -X POST http://localhost:3000/api/sync
                </code>
              </>
            )}
          </p>
        )}

        {!loading && results.length > 0 && (
        <ul className="divide-y divide-zinc-100 overflow-hidden rounded-xl border border-zinc-200 bg-white">
          {results.map((r) => (
            <li key={`${r.type}:${r.code}`}>
              <button
                onClick={() => openProduct(r)}
                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left hover:bg-zinc-50"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium">{r.name}</span>
                    <span className="shrink-0 text-xs text-zinc-400">{r.code}</span>
                    <span className="shrink-0 rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-500">
                      {TYPE_LABEL[r.type] ?? r.type}
                      {r.exchange ? ` · ${r.exchange}` : ""}
                    </span>
                  </div>
                  {r.tags.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {r.tags.slice(0, 3).map((t) => (
                        <span
                          key={t}
                          className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-600"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  {pendingKey === `${r.type}:${r.code}` ? (
                    <span className="text-xs text-blue-500">打开中…</span>
                  ) : r.price != null ? (
                    <>
                      <div className="tabular-nums">
                        {r.price.toFixed(r.type === "fund" ? 4 : 2)}
                      </div>
                      {r.changePct != null && (
                        <div
                          className={`text-xs tabular-nums ${
                            r.changePct >= 0 ? "text-red-600" : "text-green-600"
                          }`}
                        >
                          {r.changePct >= 0 ? "+" : ""}
                          {r.changePct.toFixed(2)}%
                        </div>
                      )}
                    </>
                  ) : (
                    <span className="text-xs text-zinc-300">--</span>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
        )}

        {/* 浏览模式分页（R14） */}
        {browseMode && !loading && browsePages > 1 && (
          <div className="mt-4 flex items-center justify-center gap-4 text-sm">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded border border-zinc-300 px-3 py-1 text-xs disabled:opacity-40 hover:bg-zinc-50"
            >
              上一页
            </button>
            <span className="text-xs text-zinc-500">
              第 {page} / {browsePages} 页 · 共 {browseTotal} 条
            </span>
            <button
              onClick={() => setPage((p) => Math.min(browsePages, p + 1))}
              disabled={page >= browsePages}
              className="rounded border border-zinc-300 px-3 py-1 text-xs disabled:opacity-40 hover:bg-zinc-50"
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
