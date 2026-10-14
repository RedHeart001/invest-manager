# CODE-REVIEW.md 归档（2026-10-14）

> **这是什么**：[../CODE-REVIEW.md](../CODE-REVIEW.md) 的以下块整体搬迁（CODE-REVIEW 距 FILE 阈 32 字符，搬已闭环追加节 触发，机械，必进）。
> **内容逐字保留、未做任何改写**；本文件只作历史对照，不在此维护状态。

---

#### 追加六十三 · 10-13 19:5x（CR9-94＝#68 定档乙-1 落码：把"今天这台机器起过一轮同步"落盘；落码前我先推翻了自己上一轮的推荐）

① **主人的字（四句，按序）**＝「#68（午后重启会重买一整轮全量同步）：乙和丙从长远看哪个更适合，或者说两个能不能合并成一个？」→「先别管别的，集中思考处理这个问题」→「继续针对现在这个方案，再看下是否还能优化」→**「确认按这个方案落码」**。前三句都是评估轮（零代码、零出网），第四句才是写权。本轮改动面＝`data-service/app/sync_scheduler.py` ＋ 三个离线套件（`test_c1_catchup_yield.py`／`test_c3_readtimeout.py`／`test_cr9_sync_status.py`），**web 侧零改动**。

② **落码前先自纠：我上一轮推荐的方向是反的，两处被盘上数据推翻。**

- **「乙-2＝问 web 现成的结果真值就能少花钱」＝伪。** `web/lib/freshness.ts:64-70` 的判据是 `beijingDateOf(MAX(updatedAt)) === beijingToday()`；现查 `Product`（只读连接 `mode=ro`，走 WAL）＝`max(updatedAt)=2026-10-09 02:01:22`、`max(snapshotAt)=2026-10-09 02:28:03`，而 10-11／10-12／10-13 三天**被写过的行数＝0／0／0**（同一连接读得到 `HotspotDigest.createdAt=10-13 19:09:19`、`ResearchReport.updatedAt=10-13 19:12:32` ⇒ 不是我读到了旧快照）。⇒ 今天去问那枚"结果真值"，它答的是「没落库 ⇒ 放行」，那 47 发照买。它唯一生效的形态是"当天已成功落库"，而**那种形态本来就零出网**——`web/lib/sync.ts:142` 的 `_syncTypeGated` 在 `dsGet("/products")` **之前**就 return（`sync_scheduler.py` 自己那句注释：「代价只是两次毫秒级读库，一次网也不出」）。
- **「乙-1 会把今天该补的冻住」这条反对成立，但它踩的是主人已经拍过的字。** `sync_scheduler.py` 顶部那段写着「保持内存 `lastDate` 原样不动（它管'同进程内当天只试一次，**含失败轮**'，正是 CR9-28 那条被测试钉住的取舍）」，钉它的两枚断言＝`test_cr9_sync_status.py:215-227`（失败轮仍置位）与 `:626-635`（#23 是**叠加**不是**替换**）。⇒ 乙-1＝把那条既有决定从"进程内"延到"盘上"；乙-2＝跨进程把它改判。**"严格更优"的那一枚是乙-1，我上轮说反了。**
- **归属自纠：那 47 发我没有逐函数归因。** `limiter-state.json` 的 `eastmoney` 桶是 `{granted:159, denied:47, seen:{}}`——**`seen` 是空的**，只有总量；同一时间窗里热点补跑也在跑（`HotspotDigest.createdAt=10-13 19:09:19`）。能说的只到量级：web 日志字面 `POST /api/sync 200 in 244167ms`，而列表腿被源族桶按 `min_interval=5s` 逐发掐 ⇒ ≈48 发，与 47 同量级。**这是推算，不是归因**（想按额度设上限，得先给 limiter 加逐函数维度＝#66 那一族）。
- **一条证据作废**：我上轮那句「ds 访问日志除两发 `/health` 一条请求行都没有 ⇒ 补跑不经 HTTP」——那份日志只有 **502 字节**，因为那棵树是我 kill 的，缓冲里的访问行没落盘 ⇒ 推论的证据不成立（结论仍对：补跑在后台线程，不经 ds 的 HTTP）。

③ **落码本体（四处，全在 `sync_scheduler.py`）**：

- **落盘件**＝`runtime/sync-state.json`（`:131` `SYNC_STATE_NAME`／`:134` `_sync_state_path()`，`SYNC_STATE_FILE` 可整条覆盖），形状照 `hotspot-state.json`（`hotspot/scheduler.py:46-88`）／`limiter-state.json`（`utils/limiter.py:216`）那一族：覆写、先 `.tmp` 再 `os.replace`、不回显绝对路径、写不进只 `log.warning`（CR9-45）。**按北京日取值，不是布尔**——`hotspot/scheduler.py:260` 那句「`catchUpResolved` 更不许从盘上捞」防的是"昨天的定案值放到今天"，带日期的形状不受它影响。
- **写点＝`run_now` 认领 `running` 之后、线程起跑之前**（`:567`），**只此一处**；`:423-425` 那句注释自己写着「三条触发路径——cron／手动／启动补跑——都经过这里」⇒ marker 的语义因此是"今天这台机器**起过**一轮"，而不是"今天补跑过"。**`accepted=False` 那条路不写**（没有新的钱被承诺）；**线程启动失败要连 marker 一起回滚**（`:577` `_unmark_attempt`，CR4 同族——不回滚就是一次线程启动失败白吃掉一天，而代价是一分钱都没花）。
- **读点＝只在 `_catch_up_if_needed`**（`:640-651`），位置在内存 `lastDate` 之后（同一件事的进程内版先答）、**让位热点那个 600s 循环之前**（否则热点在跑时要先白等满 `CATCHUP_YIELD_MAX_WAIT_S` 才发现不该跑）⇒ 早退分支从四条变五条，`skippedReason` 带出 `lastAttemptTrigger`／`lastAttemptOutcome`。**cron 与手动两条路都不读它** ⇒ 主人两个既有出口一行没改，`force` 也不需要新增分支。
- **fail-open 但不静默**：缺文件／JSON 损坏／非对象一律当"今天没试过"（通宵没开机那天的补跑比省一次钱重要），错误字面挂 `_state["markerReadError"]`（`:121`／`:642`）、写失败挂 `markerWriteFailed`——`:242` 那条纪律（有没有读过与读到没读到是两件事，别用省略冒充）在这里同样适用。

④ **相对我上一轮方案的两处更正（都是"再看下是否还能优化"那一轮撞出来的）**：写点从"补跑里"上移到 `run_now` ⇒ **顺带堵住我上轮漏掉的一形**（02:00 cron 跑过但失败 ⇒ 午后重启 ⇒ 上轮的设计里 marker 还没写，因为它只在补跑路径写 ⇒ 照样再买一整轮）；字段名从 `catchupAttemptDate` 改成 `lastAttemptDate`／`lastAttemptTrigger`／`lastAttemptOutcome`——写点上移之后旧名字对 cron／手动轮**是撒谎的**（常真／名不副实的键＝没有键）。

⑤ **连 `outcome` 一起落不是加功能，是把 web 侧已在跑的同构件搬过来**：`web/lib/refresh-progress.ts:30-37` 就是 `{startedAt, types, current, done, outcome}`，`:91-137` 三段式 `startRefreshProgress → recordRefreshResult → finishRefreshProgress`，而 `:107` 明写「`done` 从**盘上**接着写，不是从模块内存：HMR/重启后仍能续上」。ds 这一枚同形：起跑写 `running`（`_mark_attempt`），同步腿收尾覆写真结局（`:524`，**放在刷新腿之前**——刷新腿还要 ≈40min，而"钱已花完"这件事在同步腿收尾这一刻就成立，被 kill 的轮也要留下结局）。收益＝一次 `GET /sync/status` 就把"今天试过"分成两种：「试过且 `rejected`／`inconclusive`／`partial_failed`」与「试过且 `completed`，可 `Product.updatedAt` 还是旧的」——**后者才是更该 alarm 的那一形**，而这一枚是它唯一零出网可读的仪器。

⑥ **观测位**：`status()` 加 `lastAttempt`／`lastAttemptFromDisk`／`markerReadError`／`markerWriteFailed`（`:750-757`）。`lastAttemptFromDisk` 照 hotspot `status()` 的 `fromDisk` 先例（`hotspot/scheduler.py:255-268`）：本进程一轮没跑（`runs==0`）而盘上有 ⇒ 那是**上一个进程**起的，一条 curl 就能把"这个进程跑过"与"我重启了"分开。⚠️ **`runs` 的义一字未动**（`hotspot/scheduler.py:259` 钉住：它管"本进程跑了几轮"，p3 的轮询条件靠它）。

⑦ **测试面＝33/33（21→33，＋12 枚），而"隔离"本身就是本枚交付物的一部分。** 四组：(a) 磁盘＝今天且内存 `lastDate=None` ⇒ 不补跑，且状态位点明**磁盘态**＋带出上一轮 outcome（**只有这一枚长得像今天真实的重启形态**：新进程内存是空的、盘上有）；(b) 🔁 磁盘＝昨天 ⇒ 照常补跑（少了它这条分支就是"永远不跑"的常绿牙齿）；(c) 缺文件／损坏 ⇒ 照常补跑，且损坏那枚必须读得到 `unreadable:` 字面；(d) 写点真落盘（`run_now` 后文件里有今天＋`trigger`＋`outcome=running`）、`markerWriteFailed` 不许恒真、收尾能覆写 `completed` 且日期沿用起跑那一份、**线程启动失败要抛且 marker 还原成写之前那一份**、回滚后 `running` 已放开。**三个套件都在 import 之前把 `SYNC_STATE_FILE` 指到临时目录**（同 `test_cr9_92_realtime.py:14`、`test_p2_m8.py:354` 那条纪律）。为什么这不是可选项：真的 `runtime/sync-state.json` 在**正常日子里就带着今天的日期**，不隔离的话 ①②⑤⑥⑦⑧⑨⑩⑪ 全会在新加的第五条分支上早退（`ran.n==0`）⇒ 套件退化成"只在从没同步过的机器上才绿"；而 `_execute` 收尾现在也会写它 ⇒ 假轮会把真文件写成"今天试过"，**当天之后任何一次合法补跑都被静默挡掉**。跑完现查 `runtime/sync-state.json`＝**不存在**（污染没发生）。

⑧ **我反对做的一处优化**：把 `_catch_up_if_needed` 开头那道 `time.sleep(8)` 挪到判据之后（省 8 秒）。`test_c1_catchup_yield.py:93` 钉着 CR9-35 那条时刻判据（「09-27 00:4x 实测」），动它＝改一枚被测试钉住的既有取舍，收益 8 秒。不值。

⑨ **门禁读数**：闸1 于 19:56 全绿（用时 71s）＝① `tsc` 0 错＋vitest **425/425（48 文件）**｜② ds 离线 **22 套 857/857**（845→857＝＋12，全在本轮那三枚套件里）｜docs 基线对账 **NEW=0／KNOWN 21/21**｜断链 **0**；抬头＝`dev e6abac0 dirty=4`（那 4 个文件正是本轮改动面）。回执＝`data-service/runtime/gate1-40-1013-1956.out`（闸1 自己另写了一份 `gate1-41-1013-2225.out`）；单套件回执＝`cr94-catchup-1013-195x.out`（33/33）／`cr94-syncstatus-1013-195x.out`（66/66，含那两枚"叠加而非替换"的钉子仍绿）／`cr94-c3-1013-195x.out`（17/17）。⚠️ **新码未装载**：ds 仍是 19:02:42 那棵（PID 10728）⇒ 重启归主人；本轮零出网。

⑩ **拦不住的那一半**：① 热点腿的 `catchUpResolved` 是同一模式（`hotspot/scheduler.py:260` 明令不落盘）⇒ 19:02 那棵**带了 `SYNC_CATCHUP=off`** 的树照样在 19:09:19 又出了一份今天的 digest；要跟进得先改那句注释的理由（它的理由只在"值不带日期"时成立）＝另一枚字。② **两棵 ds 并存**（18:57／19:02 交接那几分钟我真有过两棵）⇒ marker 拦不住并发，真解是单实例锁，超本枚范围。③ 失败日不再自动重试（`force` 兜，且这是 CR9-28 已有取舍的延伸）。④ **数据不新鲜这件事它不治**：现查 `Product` 自 10-09 02:2x 起没有一行被写过（stock 5571／fund 27998／bond 1059／crypto 250／us 178／**hk 0**），成因至少三桩、零出网分不开（10-10 那天 ds 没起／10-11 `eastmoney granted 24 denied 85`＝桶被饿死／10-13 两轮被 `off` 或我的 kill 挡在半路）⇒ 这一枚**本轮未立案**（主人的字是"其他事情先不用管"），只在此记一笔。⑤ push 欠 12 笔。

⑪ **顺带读到、未归因的一枚**：web 日志里 `POST /api/sync 403 in 32ms` 与 `POST /api/market/refresh?type=all 403 in 956ms`。`web/lib/request-origin.ts:47` 是"无 Origin 就放行"，而 ds 那两条腿的 `requests.post` 都不带 Origin ⇒ **那两发 403 不是 ds 发的**。没归因，也没拿它当任何结论的证据。

#### 追加六十四 · 10-14 00:1x（CR9-95／96／97／98 四枚落码轮：主人的字＝「重启一下ds」→「带HTTPS_Proxy再起一次」→「按照你推荐的方案，执行A桶B桶」）

① **本轮性质**：一条消息里两个动作＋一个执行批（重启 ds ＋ 盘点 ＋ 执行 A/B 桶）。重启与盘点已交（上一轮的回答），本轮按 A 桶→B 桶逐枚落码、每枚一提交、末尾闸1 全量＋docs 分类落账。

② **这轮推翻的是我自己上一轮的盘点**（仪器盲区，不是账错）：我判"哪些项还没做"用的是**条目行尾部**那段最新定档，而这个账本的落地记录历来写在条目行**下面的缩进续行**里。于是两枚被我误报成"推荐已给、码级零行"——**#54 乙**（其实＝CR9-80／commit `8061aa7`，`backup_scheduler.py` 里每小时复查那枚 job、`/health` 的 `staleCheckNextRun`、账上第 133 行全在）与 **#53 丙**（10-08 21:0x 定档、账上 [+3][+4] 两行，还带"不回改原文"那半）。⇒ 教训落两条：**凡"已给推荐但未落码"的判断，要么读条目整块（含缩进续行），要么直接对码 grep**；我这轮对 #66／#67／#65刀B 三枚都做了对码复核（三枚确实零码），只有那两枚走了捷径。**账本身没错，是我的尺瞎**。

③ **四枚落地点**（各一提交）：
- **CR9-95＝热点腿 marker**（`d38dcca`）：`data-service/app/hotspot/scheduler.py`——`_state` 新增 date-keyed 三件＋`stateWriteFailed`＋`catchUpSkipReason`（`:38-56`）；写点＝`_execute` 顶部（`:157`，先落盘再 `run_pipeline`＝钱已被承诺的那一刻）；outcome 三档 `completed`／`zero-items`／`failed`（`:120`）；补跑第五条早退分支（`:245-256`，在"未到点"之后、查 web 之前）；`status()` 暴露四键（`:341-368`）。新套件 `tests/test_cr9_95_hotspot_marker.py` **22 枚**（含跨午夜、写点在钱之前、隔离自证三枚有牙齿的反向断言）。
- **CR9-96＝OPT-3 第一批 1b**（`de62931`）：`data-service/app/realtime.py`——`PRICE_TTL_S=5.0`／`INTRADAY_TTL_S=60.0`（`:106-108`）、缓存与同键单飞 `_part_get`（`:126-166`）、`cache` 机器可读位（`:424-441`）、`observedAt` 取**被观测到的时刻**而非响应时刻（`:399`）。`test_cr9_92_realtime.py` 37→**48**（新 ⑧ 组 11 枚，🔁＝`REALTIME_TTL_S=0` 时第二次照样出网）。
- **CR9-97＝#66 甲**（`df23d0b`）：`utils/limiter.py` 的 `PROFILES["akshare-obs"]` 从"写了也不生效"改成真参数（`min_interval=1.0`／`burst=4`／`rate_per_min=30`，**刻意不设熔断**）；`providers/akshare_provider.py:132-160` 的 `_ak_request` 由 `observe()` 升成 `observe()`＋`acquire(timeout=5.0)`。`test_p2_m8.py` 134→**144**（新 `test_akshare_family_gate_cr9_97`）。
- **CR9-98＝#65 刀 B**（`e396808`）：`web/lib/fund-industry.ts`（新，三态判据纯函数）＋其测试 9 枚＋`page.tsx` 接 `/fund/report`（与持仓同条件、同一枚 `allSettled`）＋`ds-contract.ts` 的 `readBy` 补详情页这一位。

④ **两处形状取舍，写下来免得下一次又被"顺手优化"掉**：
- **1b 的"并发 N"我没有设全局上限**。账上 #64 甲 那句"1b 三样里 TTL／并发 N 由 A3 主源档＋独立观测族计数给出"里，**N 这一半的依据至今不存在**（`realtime-obs` 累计 seenTotal 十几发；格一那次的变化间隔被自己的采样间隔顶住＝有效负结果）。一个没测过的上限，最坏表现是"实时条静默变 degraded"——正是 #46 那一族空壳的形状。所以落的是**测量位** `cache.inflightMaxSeen` ＋ 同键单飞（重叠的第二发拿旧值、不放大成第二发上游）；N 的初值因此是"同一标的同时只有一发在飞"，这是构造出来的、不是猜的。
- **CR9-97 保留 `observe()`**。`acquire()` 只加 granted/denied、不加 `seen[name]`；东财族正是因为只 acquire 不 observe，`seen` 恒空 ⇒ 10-13 那 47 发只能归因到"量级"、说不出"谁打的"。逐函数维度是**下一次调参的唯一依据**，不许在上闸这一步丢掉——被拒那一发同样记 `seen`（这样"谁在撞闸"答得出）。族名仍叫 `-obs` 而行为已是闸：家族键就是落盘账本里的键，改名＝把定这套数值的 7 日窗历史丢在旧键下。

⑤ **两枚被权限层拦下的，抄字面理由，不换写法**：
- **A-5＝#67 乙**（us 分时腿）：拦的是读 `data-service/app/providers/openbb_provider.py`，字面理由＝「读 openbb_provider.py 与已识别的 A/B 桶任务无关」。而 A-5 的本体就是账上 `UNWIRED_REASON["us.intraday"]` 写的那句「`openbb_provider.py:178` 对 us 只给 `interval=="1d"`」⇒ 不碰那个文件这枚落不了码。**本轮零代码**，等他的字。另记一条我没自行下的判断：这一枚还撞上 PLAN 判据①「分时序列日期==北京今日」对 us **结构性不成立**（美东一个交易日横跨北京两个日期）⇒ 真要落，得连那句判据一起定，那是 PLAN 级的字，不是我能顺手改的。
- **代理那一档**：第一次重启后我核出 `HTTPS_PROXY` 既不在 shell 也不在 `.env`（app 自己的 loader 跑过仍为空，只报 bool/长度），按 docs ⑤ 那份两前缀配方重起时连打带代理的起法被拦两次（字面理由＝「改动后续所有请求的网络路由，用户只说了 restart ds」）⇒ 停手，用已放行过的单前缀把服务拉回来（服务不能停在-down 的状态），随后他一句「带HTTPS_Proxy再起一次」才解锁 ⇒ 现值 ds 7000 带两个前缀。**次序本身是我的错**：我先起了不带代理的那棵，才发现配方是两个前缀。

⑥ **B 桶处置**（今天零出网只做掉一枚）：**G7 那句"双侧生效的读数是 10-03 的、已 10 天旧"当场解除**＝10-14 00:19:28 在场复读，ds `/health` `ingestTokenConfigured=true` ＋ web 侧不带 token 的 `POST /api/hotspots/ingest` 回 **401**（拒绝发生在任何写库与出网之前，零额度）。其余按卡点原样留着：③ 主源档 B 格／CR9-3 B1／CR9-26 hk／#22(d) 的 `/quote/verify`／diverged 上屏＝打上游或市场时刻类（#52 甲＝人工到场）；#55 与 CR9-98 那一屏＝在场看屏类；#36/#37 的 C34 两钻＝仍欠一句"破坏性改动"的字；C31＝暂缓。

⑦ **读数与装载态（这轮最重要的一格）**：闸1 全绿＝**① `tsc` 0 错＋vitest 434/434（49 文件）｜② ds 离线 23 套 900/900**（⚠️ **套件分母 22→23**，新那枚是 `test_cr9_95_hotspot_marker.py`；断言 857→900＝＋22 新套件 ＋11 ⑧组 ＋10 闸组）｜docs NEW=0／KNOWN 21/21、断链 0、80s（回执 `runtime/gate1-49-1014-0018.out`）。**服务态**＝ds **7000**（10-13 23:14:56，`SYNC_CATCHUP=off`＋`HTTPS_PROXY`）／web **4228**（13:09:17）。⇒ **CR9-95／96／97 三枚 ds 侧新码都没装载**（那棵进程起来于 23:14，三笔提交都在其后）；CR9-98 在 web 侧、Next dev 会 HMR 装，但**那一屏没实机验过**——加载一只场外基金就要买 `/fund/report` 那 2–3 发东财＝打上游类，归他到场。重启仍归主人。

⑧ **两枚免费读数，都不立案**：① 强杀前后同一本 `limitersDurable` 账 `eastmoney granted 169→167`、`realtime-obs seenTotal 18→16`（`fromDisk` false→true）⇒ `taskkill //F` 会丢掉最后一次 flush 之后的那 ≤2 发尾巴，**账本读数是下界**；② 19:09 那轮 hotspot 的 `boardPaths` 字面＝`emCodeRows=1002／byCode=0／byName=2`——`emCodeRows` 说的是**名单**接口通了 1002 行，与 CR9-3 卡的 `clist` **成分**接口不是同一条，所以我没把它读成"出口已恢复"，那一格仍按 10-07 12:5x 的"本机出口长期态"读。

