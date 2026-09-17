// 搜索结果缓存：返回上一级时秒还原结果（主流搜索体验）
// 优先内存（同一次会话内最快），并落 sessionStorage 以跨整页刷新保留。

import type { SearchResult } from "./search";
import { Lru } from "./lru";

type CacheEntry = { results: SearchResult[]; ts: number };

// CR4（P3）：内存缓存加容量上限（原 Map 无界，长期浏览累积）
const memory = new Lru<string, CacheEntry>(50);
const PREFIX = "im:search:";
const FRESH_MS = 60_000; // 视为"新鲜"的时长：新鲜则不发请求，过期则后台刷新

function key(q: string, type: string): string {
  return `${type}|${q.trim().toLowerCase()}`;
}

function storageKey(q: string, type: string): string {
  return `${PREFIX}${key(q, type)}`;
}

export function getCachedSearch(
  q: string,
  type: string,
): { results: SearchResult[]; fresh: boolean } | null {
  const k = key(q, type);
  let entry = memory.get(k);

  if (!entry && typeof window !== "undefined") {
    try {
      const raw = window.sessionStorage.getItem(storageKey(q, type));
      if (raw) {
        entry = JSON.parse(raw) as CacheEntry;
        memory.set(k, entry);
      }
    } catch {
      // sessionStorage 不可用（隐私模式等）时只用内存缓存
    }
  }

  if (!entry || !Array.isArray(entry.results)) return null;
  return { results: entry.results, fresh: Date.now() - entry.ts < FRESH_MS };
}

export function setCachedSearch(
  q: string,
  type: string,
  results: SearchResult[],
): void {
  const entry: CacheEntry = { results, ts: Date.now() };
  memory.set(key(q, type), entry);
  saveLastSearch(q, type);
  if (typeof window !== "undefined") {
    try {
      window.sessionStorage.setItem(storageKey(q, type), JSON.stringify(entry));
    } catch {
      // 超出配额等异常忽略
    }
  }
}

// —— 最近一次搜索条件：URL 无参数时（如返回上一级）恢复现场 ——

const LAST_KEY = "im:search:last";

export function saveLastSearch(q: string, type: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(LAST_KEY, JSON.stringify({ q, type }));
  } catch {
    // 忽略
  }
}

export function getLastSearch(): { q: string; type: string } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(LAST_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as { q?: string; type?: string };
    if (!v.q) return null;
    return { q: v.q, type: v.type ?? "all" };
  } catch {
    return null;
  }
}
