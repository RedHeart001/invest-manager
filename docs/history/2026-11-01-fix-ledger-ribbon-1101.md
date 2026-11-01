# FIX-LEDGER.md 归档（2026-11-01）

> **这是什么**：[../FIX-LEDGER.md](../FIX-LEDGER.md) 的以下块整体搬迁（tiliang 触发，机械，必进）。
> **内容逐字保留、未做任何改写**；本文件只作历史对照，不在此维护状态。

---

#### 当日轮明细 · 11-01

> ✅ **11-01 02:0x 自然轮（CR9-26②／CR10-5 双双闭环的依据轮）**
> **① 触发与结果**＝`trigger=daily`（自然调度，非手动）、`lastAttemptDate=2026-11-01`、`lastAttemptOutcome=completed`、`lastRun=2026-11-01T02:02:32+08:00`、列表腿 `tookMsTotal=152135`（≈2.5 分钟）；六类**全部 completed**：stock 5576（新浪降级）／fund **28236**（主源）／bond 1066（主源）／crypto 250（主源）／hk **2809**（`source=sina-hk-spot`）／us 505（甲方案 50 页）。`legStaleness` 由 `missed-today` 转 **`fresh`**（`ageDays=0`）。
> **② hk 两面的读数**＝列表腿 `note` 含 `source=sina-hk-spot`·`count=2809`·「翻页 48 页后取尽」·44.5s；东财侧仍 `RemoteDisconnected`（all hosts failed，**不是** cooling down）⇒ 新浪腿**第二次被真实行使**（10-30 手动腿是同源同量，两次独立成立）。库内 `Product type='hk'` **2809 行**。
> **③ 刷新腿**＝`partial_failed`、`weakTypes=["fund"]`，但质量比 10-30 那次好得多：fund `24178/28236`、**仅 2 个失败批次**（10-30 是 232 个）；stock/hk/us/crypto 全量、bond 314/1066（`failedBatches=0`）。
> **④ 夜间保活的三条证据（这轮"进程不死"是可查的，不是口头保证）**＝防睡 `keepawake_holder_1031.py` 从 10-31 17:38 持续 `hold ret=0x80000001` 到 **02:44** 未断；watchdog `watchdog-1031.ps1`（PID 6164）**02:00 之后零 ALERT**（日志里那 2 次 ALERT 是 10-31 20:24／20:34 我自己做的故障演练）；两棵服务 PID（web 17580／ds 10548）整夜未变。
> **⑤ 一处如实记录的缺陷**＝watchdog 的检查触发判据是「`lastAttemptDate` 一变就跑」，结果 **02:00:27** 就触发了 `morning-check-1101.ps1`，而同步腿 **02:02:32** 才收尾 ⇒ `morning-check-1101.out` 里是**运行中的中间态**、不是最终结果。**判据缺陷**：应在 `lastAttemptOutcome` 落定后再触发。本轮判定改用实时 `/sync/status` 与 `sync-state.json`，未受该缺陷影响。
> **⑥ 判定与处置**＝走 **(b) 档**：东财未恢复、新浪腿再次行使、2809 只取尽。主人的字＝「两项都闭＋立覆盖面观察」⇒ **CR9-26② 与 CR10-5 双双翻 ✅**（见看板），**2809 vs 东财约 4700 的覆盖面差异外置为观察项**，不挡闭环。

> **11-01 自然轮读数（只增这一行；上面 10-30 各行原句不回改）**＝`trigger=daily`·`lastAttemptDate=2026-11-01`·`outcome=completed`·`tookMsTotal=152135`；
> 六类 `count`：stock 5576（新浪降级）／fund 28236（主源）／bond 1066（主源）／crypto 250（主源）／**hk 2809（`source=sina-hk-spot`，48 页取尽，44.5s）**／us 505（甲方案）；
> 刷新腿 `partial_failed`·`weakTypes=["fund"]`（fund 24178/28236、**2** 个失败批次；stock/hk/us/crypto 全量、bond 314/1066 failedBatches 0）；
> `legStaleness` **`fresh`**（`ageDays=0`）；库内 `Product`＝fund 28236／stock 5576／hk 2809／bond 1066／us 505／crypto 250。
> 夜间保活三证：防睡持续 `hold ret=0x80000001` 至 02:44 未断；watchdog 02:00 后零 ALERT；服务 PID 整夜未变（web 17580／ds 10548）。
> ⚠️ **已知判据缺陷（本轮实测）**＝watchdog 的检查触发用「`lastAttemptDate` 一变就跑」⇒ 02:00:27 触发、而同步腿 02:02:32 才收尾，`morning-check-1101.out` 记的是中间态；正解＝等 `lastAttemptOutcome` 落定再触发，**未改码，只登记**。

> **11-01 15:5x–16:1x 追加（R18 自选清单页落地；主人的字＝「很好，先做Watchlist，做完了之后进行全量测试，测试没问题了再更新docs目录下对应文件内容，然后commit」）**
> **① 口径**＝10-22 那次「`Watchlist` 已拍板＝**不做**」原句**一字不回改**；11-01 主人改口要做 ⇒ 按**需求变更**处置：需求本体落 `PLAN.md` **R18**（已加需求行），本文件另起这一行指向它。**不跳过 PLAN 直接写码**——否则账本与代码失同步。
> **② 缺口形状**＝`Watchlist` 表**能存不能看**：详情页有「加自选」（G5）、搜索排序在读它，但 `web/app` 下没有任何页面把它列出来。
> **③ 落地面**＝新增 `web/app/watchlist/{page,loading,WatchRemoveButton}.tsx`、`web/lib/watchlist.ts`（分组/降级判据，纯函数可单测）、`web/lib/type-label.ts`（类名表单一来源）；改 `lib/provenance.ts`（`FROM_KEYS` 增 `watchlist`＋`hrefForFrom` 改穷举 `Record`）、`app/components/Nav.tsx`（加一级入口）、`lib/quote-enrich.ts`（分批，见④）。
> **④ 顺带修掉一处静默截断（本轮现查）**＝ds `/quotes` 对 `codes` 硬上限 **100** 且**静默截断**（`data-service/app/main.py` 的 `code_list[:100]`）。`search.ts`／`browse.ts` 每页 ≤50 条越不过去，但清单页**按类型送全量** ⇒ 自选超 100 只时第 101 只起安静地没有价格。现按上限分批顺序发。**不碰 `DS_RESPONSE_FILES`**（改的是 web 侧调用方）⇒ 不点亮闸2 L3、零重采、零额度。
> **⑤ 两处"必然这么写"的取舍**（都不是风格选择）＝**(a)** 清单页用 **Server Component**：C32 要求"在途请求可取消、过期响应不写状态"，服务端渲染完才下发 ⇒ 天然无在途请求；若为实时刷新改客户端，就得自建 `AbortController`＋序号守卫，成本翻倍还要过 C32 验收。(b) **不新增 BFF `/api/quotes` 路由**：BFF 的意义是给浏览器提供接口，而本页在服务端、直接走 `lib/data-service.ts`（与 `browseProducts` 同形）；多开一条无浏览器调用方的路由只多一份要守 C33 的面。
> **⑥ 门禁读数（现跑）**＝`node scripts/gate.mjs` 全绿：`tsc` **0**｜vitest **482/482·52 文件**（原 473/51）｜ds 离线 **28 套 1084/1084**｜docs `NEW=0／KNOWN=3/3`｜断链 **0**；回执 `gate1-1138-1101-1610.out`。`node web/scripts/verify-all.mjs`＝**七套 ALL DONE**，`test-p1` **25/25**（原 23，+2 自选来路）、`test-p2` **63**（档 `62|63`，原 `54|55`，+8 清单页 SSR）。`PLANNED` 两格同步改（`test-p1` 23→25、`test-p2` 54|55→62|63）。
> **⑦ 反向验证（C34 同精神，四处钻，每处都精确红、钻后已复原）**＝**(a)** 把 `hrefForFrom` 的自选目标写错成 `/` ⇒ 只红「③d」一条、其余 14 条照绿。**(b)** 把表外类型丢掉 ⇒ 只红「②」一条。**(c)** 摘掉移除按钮 ⇒ 只红「R18：每一行带移除入口」一条。**(d) 这一钻钻出了真问题**：把 `fetchQuotesByType` 的 `for (const chunk of chunkCodes(codes))` 回退成 `for (const chunk of [codes])`，那 6 条纯函数断言**全绿**——因为坏的不是 `chunkCodes`，是**没人调它**。⇒ 补一组接线断言（判"**实际发出的 codes 组数**"），重钻后精确红「⑦」一条。
> **⑧ 未做/留白（如实）**＝① 浏览器屏上那一形未亲见——本轮判定取的是 SSR 产物（`test-p2` 第 [12] 段 7 条＝写→抓 `/watchlist`→断名称/代码/中文分组/移除入口→删→再抓→leftover=0），与 CR7-4 的 hk 详情页同一取证口径。② 清单页**没有**"实时刷新价格"——按 ⑤(a) 的取舍是刻意的，非缺陷。


