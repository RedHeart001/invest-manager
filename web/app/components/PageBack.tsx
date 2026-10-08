"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  parseFrom,
  planBack,
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
 * `type`/`sort`/`page`。
 *
 * #56 甲（10-08）：「只有没有可回退历史」这一条此前用 `window.history.length > 1` 判，
 * 而文案按 `from` 判 ⇒ 两支取的键不同，粘贴裸 URL 时会出现"承诺回首页、实际回上一条
 * 历史"、看上去就是"点了没反应"。现在文案与行为都由 `planBack` 的同一个布尔给出：
 * URL 带白名单内的 `?from=` ＝应用内进入＝那条历史必然存在＝才 `back()`；否则一律
 * push 推导目标（`sessionStorage` 的来路只用来选目标，不上文案）。
 */
export default function PageBack() {
  const router = useRouter();
  const params = useSearchParams();
  const rawFrom = params.get("from");
  const urlFrom = parseFrom(rawFrom);
  const [stored, setStored] = useState<FromKey | null>(null);

  useEffect(() => {
    if (urlFrom) {
      storeFrom(urlFrom);
      return;
    }
    setStored(readStoredFrom());
  }, [urlFrom]);

  const plan = planBack(rawFrom, params.get("q"), stored);

  function onBack() {
    if (plan.useHistoryBack) {
      router.back();
      return;
    }
    router.push(plan.fallbackHref);
  }

  return (
    <button
      type="button"
      onClick={onBack}
      className="-ml-2 rounded px-2 py-1 text-sm text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
    >
      {plan.label}
    </button>
  );
}
