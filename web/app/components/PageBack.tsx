"use client";

import { useRouter, usePathname, useSearchParams } from "next/navigation";

import {
  canBackToOrigin,
  parseFrom,
  planBack,
  routeKey,
} from "@/lib/provenance";

/**
 * CR8-6：详情页的页内回指入口——CR8-5 删掉面包屑之后，它是唯一的返回途径。
 *
 * 语义＝"回到我来的那一页"（主人 2026-10-01 定）。首选 `router.back()`：它回到**你来时那一条 URL**，
 * 于是 `q`/`type` 原位、60 秒内结果直接命中 `lib/search-cache.ts` 不再发请求。
 * ⚠️ 这里原来写的是"带回 `staleTimes` 承载的滚动/分页态"——10-09 读码收窄：查询模式只往 URL 写
 * `q` 与 `type`（`search-client.tsx:188`，只有浏览模式写 sort/page），所以那两样从来不在
 * `back()` 的保证范围内，别把这句当验收条件。
 *
 * #56 甲（10-08）：文案与行为一度取的是两个键（`from` vs `history.length`）⇒ 粘贴裸 URL
 * 时"承诺回首页、实际回上一条历史"＝看上去点了没反应。
 * 主人 10-09 第二轮手测又把"只要 URL 带 `from` 就 `back()`"这一条判错了：同一标签里粘贴
 * `?from=home` 会 back 到上一条历史（往往是搜索页），而裸 URL 的目标还在继承会话残留。
 * 现在两形一起断：目标只由 URL 自己决定（无 `from` ⇒ 首页），`back()` 只在**本文档路由轨迹**
 * 证明"确实从另一页推进来"时才用（`Nav` 观察，整页加载即归零），否则一律 push 那个目标。
 */
export default function PageBack() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const rawFrom = params.get("from");
  const urlFrom = parseFrom(rawFrom);
  const plan = planBack(rawFrom, params.get("q"));

  function onBack() {
    // 文案承诺了某个来路，且轨迹证实这一页确实是应用内推进来的 ⇒ 才回那条历史。
    if (urlFrom && canBackToOrigin(routeKey(pathname, params))) {
      router.back();
      return;
    }
    router.push(plan.href);
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
