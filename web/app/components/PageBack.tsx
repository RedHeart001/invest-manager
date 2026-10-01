"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  FROM_LABEL,
  hrefForFrom,
  parseFrom,
  readStoredFrom,
  storeFrom,
  type FromKey,
} from "@/lib/provenance";

/**
 * CR8-6：详情页的页内回指入口——CR8-5 删掉面包屑之后，它是唯一的返回途径。
 *
 * 语义＝"回到我来的那一页"（主人 2026-10-01 定）。首选 `router.back()`：它天然回到
 * 那个入口，并且带回落后的搜索现场（`lib/search-cache.ts` ＋ `next.config.ts` 的
 * `staleTimes` 承载的滚动/分页态）——直接 push 一个重建的 `/search?q=…` 反而会丢掉
 * `type`/`sort`/`page`。只有**没有可回退历史**时（直接敲 URL／新标签打开）才用 `from`
 * 推导确定目标。文案同样跟随来路（「← 返回搜索」），这样"点了会不会跳去搜索页"
 * 在按钮上就先说清了。
 */
export default function PageBack() {
  const router = useRouter();
  const params = useSearchParams();
  const [from, setFrom] = useState<FromKey | null>(() => parseFrom(params.get("from")));

  useEffect(() => {
    if (from) {
      storeFrom(from);
      return;
    }
    setFrom(readStoredFrom());
  }, [from]);

  function onBack() {
    if (window.history.length > 1) {
      router.back();
      return;
    }
    router.push(from ? hrefForFrom(from, params.get("q")) : "/");
  }

  return (
    <button
      type="button"
      onClick={onBack}
      className="-ml-2 rounded px-2 py-1 text-sm text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
    >
      {from ? `← 返回${FROM_LABEL[from]}` : "← 返回"}
    </button>
  );
}
