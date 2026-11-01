import Link from "next/link";

import WatchRemoveButton from "./WatchRemoveButton";
import { priceWithCurrency } from "@/lib/currency";
import { fetchQuotesByType } from "@/lib/quote-enrich";
import { prisma } from "@/lib/prisma";
import { groupWatchlist, quotesAllMissing } from "@/lib/watchlist";

// R18（2026-11-01，主人改口要做）：自选清单页。
//
// 此前 `Watchlist` 表能存不能看——详情页有「加自选」按钮（G5），搜索排序也在读这张表，
// 但 `web/app` 下没有任何页面把它列出来 ⇒ 用户加完之后无处核对"我到底加了哪些"。
//
// **为什么是 Server Component（不是风格选择）**：C32 要求"前端在途请求必须可取消、
// 过期响应不得写入状态"。服务端渲染完才下发，天然没有在途请求，C32 的全部约束直接不适用。
// 若做成客户端组件（为了"实时刷新价格"），就得自己实现 AbortController ＋ 请求序号守卫，
// 成本翻倍还要过 C32 的验收——而自选清单**不需要实时性**，打开时取一次就够。
//
// 取数形态沿用 `lib/browse.ts` 的既有做法：直接调 `lib/data-service.ts#fetchQuotes`
// （经 `quote-enrich.ts` 按类型分组批量），**不为此新增一条 BFF 路由**。理由：BFF 路由
// 存在的意义是给浏览器提供接口，而本页在服务端；多开一条没有浏览器调用方的路由，
// 只会多一份要守 C33 白名单、C33 之外还要守 C32 的面。

// 与首页同口径：动态渲染（自选与行情都可能随时变），且不许在构建期把 DB 读成静态页。
export const dynamic = "force-dynamic";

function fmtPrice(price: number | null, type: string): string {
  if (price == null || !Number.isFinite(price)) return "--";
  // 场外基金净值 4 位、其余 2 位——与 `search-client.tsx` 的展示口径一致。
  return price.toFixed(type === "fund" ? 4 : 2);
}

export default async function WatchlistPage() {
  // 库异常不许白屏（与首页同一条约定）：降级成一句说明，页面骨架仍在。
  let rows: { type: string; code: string; name: string }[] = [];
  let loadError: string | null = null;
  try {
    // createdAt desc ⇒ 组内新加的在前（`groupWatchlist` 保持输入的相对顺序）
    rows = await prisma.watchlist.findMany({
      orderBy: { createdAt: "desc" },
      select: { type: true, code: true, name: true },
    });
  } catch (e) {
    loadError = e instanceof Error ? e.message : "自选读取失败";
  }

  // 行情富集：失败不抛（`fetchQuotes` 内部按类型各自降级成空对象），
  // 拿不到价的条目价格列显示 `--`，页面其余部分照常。
  const quoteMap = loadError ? new Map() : await fetchQuotesByType(rows);
  const groups = groupWatchlist(rows, quoteMap);
  const allMissing = quotesAllMissing(rows, quoteMap);

  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight">自选</h1>
        <Link href="/search" className="text-sm text-blue-600 hover:underline">
          去搜索添加 →
        </Link>
      </div>
      <p className="mt-1 text-sm text-zinc-500">
        在任意产品详情页点「☆ 加自选」即可加入；自选会同时提高该标的在搜索结果中的排序。
      </p>

      {loadError && (
        <div className="mt-4 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          自选列表加载失败：{loadError}（页面其余功能不受影响）
        </div>
      )}

      {/* R16：整批行情一条都没回来时才说话。**不猜成因**——`fetchQuotes` 把"数据服务不可达"
          "超时""上游返回空"吞成同一个空对象，此处若断言是哪一种就是编造，所以并列写出让人自己对号。
          单只标的缺价不算降级（停牌、新股都是常态），那种情况价格列显示 `--`、下方不出任何说明。 */}
      {allMissing && (
        <div className="mt-4 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          行情暂时取不到（数据服务未启动、响应超时或上游无数据），下方价格列显示{" "}
          <code className="rounded bg-amber-100 px-1">--</code>；标的本身仍在自选里。
        </div>
      )}

      {!loadError && rows.length === 0 && (
        <div className="mt-6 rounded-xl border border-dashed border-zinc-300 px-6 py-10 text-center">
          <p className="text-sm text-zinc-500">还没有自选标的。</p>
          <p className="mt-2 text-xs text-zinc-400">
            在
            <Link href="/search" className="mx-1 text-blue-600 hover:underline">
              搜索页
            </Link>
            找到产品、进入详情页后点「☆ 加自选」。
          </p>
        </div>
      )}

      <div className="mt-6 space-y-4">
        {groups.map((g) => (
          <section key={g.type} className="rounded-xl border border-zinc-200 bg-white">
            <div className="flex items-baseline justify-between border-b border-zinc-100 px-4 py-2.5">
              <h2 className="text-sm font-medium text-zinc-700">{g.label}</h2>
              <span className="text-[11px] text-zinc-400">{g.items.length} 只</span>
            </div>
            <ul className="divide-y divide-zinc-100">
              {g.items.map((it) => {
                const key = `${it.type}:${it.code}`;
                return (
                  <li key={key} className="flex items-center justify-between gap-4 px-4 py-3">
                    <div className="min-w-0 flex-1">
                      {/* 来路驱动（`lib/provenance.ts`）：从自选进详情页要亮「自选」、
                          返回回本页。`from` 是外部输入，`parseFrom` 只认白名单内的值 ⇒
                          必须先把 `watchlist` 加进 `FROM_KEYS`，否则这里带的是一个哑参数。 */}
                      <Link
                        href={`/product/${it.type}/${it.code}?from=watchlist`}
                        className="truncate font-medium hover:underline"
                      >
                        {it.name}
                      </Link>
                      <div className="mt-0.5 flex items-center gap-2">
                        <span className="text-xs text-zinc-400">{it.code}</span>
                      </div>
                    </div>
                    <div className="shrink-0 text-right tabular-nums">
                      {/* CR7-4/B2c：非 CNY 品种带币种单位 */}
                      <div>{priceWithCurrency(fmtPrice(it.price, it.type), it.currency)}</div>
                      {it.changePct != null && (
                        <div
                          className={`text-xs ${
                            it.changePct >= 0 ? "text-red-600" : "text-green-600"
                          }`}
                        >
                          {it.changePct >= 0 ? "+" : ""}
                          {it.changePct.toFixed(2)}%
                        </div>
                      )}
                    </div>
                    <WatchRemoveButton type={it.type} code={it.code} />
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>

      <p className="mt-10 text-xs text-zinc-400">
        行情数据来自免费源，可能有延迟，仅供参考，不构成投资建议。
      </p>
    </main>
  );
}
