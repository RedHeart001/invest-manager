# 代码审查发现记录（CODE-REVIEW）

> **职责**：记录**各轮审查发现了什么**。本文件只增不改——已发布的发现不因后续修复而删除或改写，
> 状态变化记在 [FIX-LEDGER.md](FIX-LEDGER.md)。
> 需求与设计见 [PLAN.md](PLAN.md)，约束见 [CONSTRAINTS.md](CONSTRAINTS.md)。
>
> **提新发现前先查**文末「附录 · 已核验排除的误报（跨轮累计）」，避免重复提已证伪项。

> **速览**：这里只记"各轮审查**发现了什么**"，修没修、怎么修、按什么顺序修都看 [FIX-LEDGER.md](FIX-LEDGER.md)。**当前轮次是 CR9**（2026-09-26 全项目审查，编号**已排到 CR9-47**（09-27 批次七排到 44；**09-28 死项清理轮占 45/46/47**，批次七那条前置实测债按占号规则顺延；前向引用不构成预留）；**合计/已修/余项的权威计数只在 FIX-LEDGER 速览一行维护，本行不复述**——09-26 的 CR9-23 教训：同一数字抄两处必然失同步，本行此前就落后了两批）；CR8 开放（6 项已拍板待实施，实测确认代码一行未动；**09-30 晚主人实跑首页时另发现 CR8-8 并当日修毕——但"首页乱"经 41 批次实测判定为非回归，无改动导致，详见该条归因段**）；**CR7 代码闭环 14+1、验收 1 项受阻转 CR9-26**。已闭环轮次（CR1–CR6）只留压缩结论+指针。编号黑话（CRn / CR-xx / G / V）先查下方「轮次对照表」。

---

## 轮次 ↔ 编号 ↔ commit 对照表

> 本项目历史上并行存在过四套编号，这是唯一对照表。**规范轮次为连续的 CR1…CR9。**

| 轮次 | 日期 | commit | 当时的文档称谓 | 编号前缀 | 状态 |
|---|---|---|---|---|---|
| **CR1** | 09-13 | `b22671f` / `f5656d7` ⏳ | "全项目代码审查（2026-09-13 定稿）" | C1–C17 + O 系列 | 已闭环 |
| **CR2** | 09-13 | `3bd73a1` | "第二轮审查（四路并行）" | C18–C23（12 项真实缺陷） | 已闭环 |
| **CR3** | 09-14 | `d6ac165` | **无任何文档记载**（已从 git 重建） | ？（8 项） | 已闭环；记录已重建 |
| **CR4** | 09-15/16 | `4905095` | "第四轮审查（CR4）" | C26–C33（P1×5 + P2×12 + P3×25） | 已闭环；C31 验证未做 |
| **CR5** | 09-17 | `4905095` | "第五轮审查（CR5）" | C34（P1×2 + P2×1 + 缺口×3 + P3×6） | 已闭环；3 项暂不处理 |
| **CR6** | 09-18~20 | `2efda87` | "第一轮·全项目"（**误名**） | `CR-01..22` + `G1–G7` + `V1–V3` | 已处置；遗留 G3/G6/G7 |
| **CR7** | 09-20 | `2efda87`（被审代码） | "第二轮·全项目"（**误名**） | `CR7-1..14` | 已闭环（逐项状态见 FIX-LEDGER 看板；余 3 项手测与门禁复现见 CR9-14） |
| **CR8** | 09-24 | `3b07643`（被审代码） | 界面语义审查（主人本地实跑点击驱动） | `CR8-1..8`（**09-30 晚主人再实跑时新增 CR8-8**） | 开放；6 项已拍板待实施（09-26 实测确认代码一行未动），CR8-7 转 OPT-2，**CR8-8 当日发现当日修（09-30）** |
| **CR9** | 09-26 | `02f0e95`（被审代码，工作树干净） | 全项目审查（CR7 闭环复核 + 两路并行审计 + 实时接口/DB 探针） | `CR9-1..47`（**09-27 批次七排到 44；09-28 死项清理轮占 45/46/47**） | 开放；**逐批执行中**——发现时点是"23 项全部未处置"，**批次〇–七后的实修/撤回/余项计数只在 [FIX-LEDGER.md](FIX-LEDGER.md) 维护，本行不复述**（09-26 CR9-23 同族教训） |

**为什么 CR6/CR7 会"误名"**：git 用的是连续"第 N 轮"（CR2–CR5），而 09-18 起文档重新从"第一轮"计数，测试文件却延续内部编号 `test_cr6_*.py`，PLAN 又并行维护 C/O/R 系列——四套编号各说各话。

**命名规则（今后固定）**：
1. 文档层把"第一轮/第二轮·全项目"改标为 CR6/CR7，**保留旧称别名**以免既有引用断链。
2. **不重命名** `test_cr6_*.py` 与既有 id（`CR-01..22`、`G1–G7`、`V1–V3`）——引用稳定性 > 名称纯度，只在对照表注明前缀归属。
3. 今后每轮固定 `CRn` + 编号前缀 `CRn-xx`，轮次与编号前缀数字对齐。
4. 表中带 ⏳ 的格子**必须先取证再填，不允许猜**。取证手段：`git show <commit> --stat`、`git show <commit> -m`、代码注释里的 `CRn-` 标记、测试文件名。

**CR3 的重建**：`d6ac165`（2026-09-14）"fix: 第三轮 code review——8 项缺陷全修（含 1 项回归 + 1 项不完整修复）"。该轮在 PLAN.md / Progress.md / code-review.md 中**均无记载**，已于 2026-09-20 整理时从 `git show d6ac165` 重建，见 [history/2026-09-14-cr3-第三轮重建.md](history/2026-09-14-cr3-第三轮重建.md)。注意其"1 项不完整修复"很可能就是后来 CR4/CR5 反复出现的"修复只做了一半"模式的源头（C11→CR4-4、CR4-6→CR5-3、CR7-1）。

---

## CR9 · 全项目审查（2026-09-26，当前轮）

> **审查对象**：工作树 `dev` @ `02f0e95`（`git status --porcelain` 为空，无未提交改动）。
> **审查方式**：三条腿取证——① **闭环复核**：CR7 的 14 项 + C6 逐条回代码取行号，不采信账本与注释；② **两路并行审计**（web 侧 / data-service 侧各一路，含 CR7 五个修复 commit 的 diff 复盘）；③ **实时探针**：双服务在跑（web :3000 / ds :8000），用 `curl` 打真实端点、用 python `sqlite3` 只读查 `dev.db`，并按账本门槛复跑 `tsc` / `vitest` / ds 12 个离线套件。每条发现都要能由一条命令或一段代码复现。
> **两条纪律**：① 不采信注释与文档的"已实现/已修复"，以运行行为为准；② **本轮跑了测试与真实接口**（区别于 CR7/CR8 的"未运行任何测试"），文中数字均为 09-26 实测值。
> **去重**：已逐条比对 CR6 排除 9 项、CR7 排除 8 项、整理期新增 1 项、CR6 可优化项 🔵 保留 5 项，以及 CR8-1…7 / OPT-2 / G7 / C31 的既有口径；本轮新条目全部避开。审计过程中**撤回 1 条**（`backup_db.py` 残留空壳清理不可达——实测 19/19 通过证明损坏源不会创建文件），见文末附录。
> **总判断**：23 项 = **P1×1 + P2×5 + P3×17**。与 CR8 的结论同构且更严重一层：**CR7 的代码层修复全部落地且质量可靠（14/14 + C6 逐条行号可查），错的是"闭环"这个词**——三项手测从未执行、门禁今天不可复现、以及两项修复自身带出新缺陷（CR9-2 由 A3 引入、CR9-6 由 B2c 半落地）。另有一类从未被任何一轮抓到的问题：**备源在服务时把语义或身份丢掉**（CR9-1/6/7），以及**限流计数单位与实际 HTTP 请求数差一个量级**（CR9-3），后者是长期熔断的真正根因，也直接改变 CR8 批次二 / OPT-2 的前提。归并为六个根因：① 降级即丢身份/语义（CR9-1/6/7）② "修复只做了一半"第 4 次复现（CR9-2/6/13）③ 计数与单位口径错位（CR9-3/9/22）④ 状态写给用户与 LLM 但口径是错的（CR9-4/5/11/12）⑤ 验收门禁不可复现（CR9-14/15）⑥ 状态/指针层漂移（CR9-23）。

### 处置总览

| 编号 | 严重度 | 一句话 | 关联需求/约束 | 证据 |
|---|---|---|---|---|
| **CR9-1** | **P1** | 腾讯备源按数字前缀映射标的，**场外基金被串成同码沪市品种**，错数据会被写进 `KlineDaily` | C26 / §C-4 / R16 / R11 | `tencent_provider.py:20-27`（`_symbol`）vs `:286`（注册含 fund）；缺 `sina_provider.py:18-23` 式守卫与 `akshare_provider.py:145-147` 权威判据；**实测**见详述 |
| **CR9-2** | P2 | CR7-5/A3 的"异常退出"分支把**服务端 error 事件全覆盖**成"连接中断" | R16 / R17（修复自身引入） | `ChatUI.tsx:302-304` vs `:350-362`；`api/chat/route.ts:260-279`（发 error 后不发 done） |
| **CR9-3** | P2 | 东财令牌**按 akshare 函数计次**，1 次 acquire 实发 ~10–20 个 HTTP 请求 | C29 / R15 / limiter 自记事实 | `limiter.py:118-121` + `pipeline.py:258/:500` + akshare `stock_board_concept_em.py:47/:440`（`fetch_paginated_data`）与 `:421-426`（传名称时重拉全表） |
| **CR9-4** | P2 | 02:00–08:30 之间启动服务 → **当天主数据同步整日不发生** | R15 / R10（CR7-7/C1 修复的残留） | `sync_scheduler.py:35`（`DEFAULT_SYNC_HOUR=2`）+ `:143-148` + `:154-176`（`while/else` 唯一出口是 break）+ `hotspot/scheduler.py:26`（8:30 前不补跑） |
| **CR9-5** | P2 | `POST /sync/run` 无 type 白名单：未知类型跑成 0 行却**记成功并置 `lastDate`**，抑制当天真实同步 | C1 族 / R15 / C12 | `main.py:268-275`（`type` 原样透传）+ `sync_scheduler.py:71-73`（遍历未知键得空）+ `:93-101`（无条件置 lastDate） |
| **CR9-6** | P2 | 币种只在"主源 + 现价"成立：**东财一冷却，港股就变回无单位数字**；指标卡/明细表/分类浏览从未接 | R8 / R12 / R16（CR7-4/B2c 半落地） | `tencent_provider.py:91-105` 无 `currency`；`browse.ts:103-117`；`page.tsx:169-174`、`:370-373`；**实测** `/quote?type=hk&code=00700` 返回 436.6 无 currency |
| **CR9-7** | P3 | 行情 `timestamp` 三源三形态**原样渲染**（14 位紧凑串直接上屏） | 界面可读性 / R16 | `akshare_provider.py:275-280`（ISO）、`tencent_provider.py:99`（`f[30]` 紧凑）、hk 分支带空格；`page.tsx:295`、`QuoteCard.tsx:92` 原样输出 |
| **CR9-8** | P3 | CR7-14-④ 的注释对齐**自身写错**：称 hk 用 `register_chain`、`get_provider("hk")` 抛 KeyError | 落笔纪律「不臆测」 | `providers/__init__.py:39-40` vs `hk_provider.py:326`（`register(["hk"], provider)`） |
| **CR9-9** | P3 | 快照刷新的限速集合 `EM_TYPES` 漏 hk（48 批无限速打东财 ulist） | C29 / R15 | `market-snapshot.ts:12`（`{"stock","bond"}`）+ `:127-129` + `hk_provider.py:148-159`；⚠️ 影响幅度**未实测** |
| **CR9-10** | P3 | `/api/events` 与工具执行路径未过 `lib/validate`（CR7-6 的单一来源有两条漏接线） | C33 / R15 | `api/events/route.ts:7-12`；`tools.ts:236/:265/:382`；lib 层有 type 门（`events.ts:101`）与 TTL 缓存，故耗额度影响有限 |
| **CR9-11** | P3 | `crossChecked` 语义是"已尝试比对"而非"已比对成功"，前端又用**文案子串**决定颜色 | R13 / R16 | `chain.py:84,114`；`VerifyQuoteButton.tsx:52-61`；**实测** 返回 `crossChecked:true` 同时 note 写"交叉验证源 akshare 不可用" |
| **CR9-12** | P3 | `normalizeRange` 校验形态不校验历法：`2026-02-31` 放行，窗口被静默改写 | A2-② 的同一契约 | `kline.ts:95-110` + `:71-73`（`dayStart` 对非法历法得 Invalid Date）；**实测** 两次请求均 200，返回区间从 03-03 起 |
| **CR9-13** | P3 | C6b 只覆盖"请求抛错"，**200 + 空 candles 不回落 3M**；且 1m 透传把 ds 的 note 丢了 | R15 / R16（C6b 计划原文含"返回空 candles"） | `ProductCharts.tsx:144-158`（仅 catch 分支）；`kline.ts:219-233`（1m 路径 `note: null`） |
| **CR9-14** | P3 | 验收门禁**今天不可复现**：vitest 181/182、ds 两套件在 GBK 控制台崩、账本记"8 套件"实为 12 个文件 | R9 / 落笔纪律「可复现」 | `gateway.test.ts:83-87`（真打实时链路，实测 5.53s > vitest 默认 5s，连跑 2 次同挂）；`test_cr7_research.py:42`/`test_p2_m8.py:29` 的 `check()` 名内含 🔁 |
| **CR9-15** | P3 | 回归防线里有一条**恒真断言**（末尾 `or True`），C34 意义上的假覆盖 | C34 | `tests/test_backup_db.py:64` |
| **CR9-16** | P3 | 分钟线取当日窗口用**本地时区** `date.today()` | §B 北京时间口径 / CR-06 | `akshare_provider.py:424-427`（同文件其余处已走 `beijing_*`） |
| **CR9-17** | P3 | 基金持仓的 `df["季度"]` 在 try 之外，上游改列名 → 裸 `KeyError` → 500 而非 200+degraded | R10 | `akshare_provider.py:605-611` |
| **CR9-18** | P3 | 令牌桶参数**按导入顺序首调用获胜**，akshare 侧显式调参静默失效 | C29 | `limiter.py:118-121` + `pipeline.py:58`（无参先注册）+ `akshare_provider.py:70-78`；当前默认值恰好相同故无症状（`:25-30`） |
| **CR9-19** | P3 | 死代码：`QuoteCard.tsx` 零 importer 且自带缺 `currency` 的私有 `Quote` 类型；`browse` 的 `stale` 字段零消费者 | 批次 D「不留声明了没做的模糊态」 | `grep -rn "QuoteCard" web/app web/lib web/scripts` = 0；`browse.ts:23/:112` |
| **CR9-20** | P3 | `/api/market/refresh` 仍 `maxDuration=800`——同一轮 C3 刚按实测把 `/api/sync` 抬到 1500 | C3/CR7-9 口径 | `market/refresh/route.ts` vs `api/sync/route.ts:12`；⚠️ 刷新总耗时**未实测** |
| **CR9-21** | P3 | `web/.env.example` 缺 `INGEST_TOKEN` / `ALLOWED_ORIGINS` ⇒ 开发态落库与来源校验 **fail-open** | G7 关联 | `api/hotspots/ingest/route.ts:10-12`（`if (expected && ...)`）+ `web/.env.example` 键位；compose 侧有 `:?` 保护（`docker-compose.yml:31`） |
| **CR9-22** | P3 | 同源族口径不齐：同一文件里一处用 helper 一处内联读 env；**非 2xx 继续等、异常反而放行** | C29 族 | `sync_scheduler.py:56` vs `:159`；`:161` vs `:165` |
| **CR9-23** | P3 | 状态/指针层漂移 6 处（PLAN R13/G3 仍标待实施、CODE-REVIEW 速览与对照表仍说 CR7 开放、FIX-LEDGER D4-④ 仍标待办、PROGRESS 基线停在 148/148、rules 入口仍写"当前开放轮次 CR7"、FIX-LEDGER:140 的"34 条定义在工作树"为假） | 文档单一来源纪律 | 见详述 P3 段末 |

### 详述 · P1

#### CR9-1（P1）· 腾讯备源把场外基金串成同码沪市品种，且错误数据会落库

- **现象（09-26 实测）**：东财/天天基金处于冷却时（**今天就是这种状态**，处处 `eastmoney cooling down`），
  ```
  GET :8000/kline?type=fund&code=110022&start=2026-06-01&end=2026-06-30
  → {"source":"tencent","note":"主源不可用，已降级至 tencent（akshare: fund nav history empty after filter: 110022）",
     "candles":[{"date":"2015-01-05","close":146.88}, … 37 根]}
  GET :8000/kline?type=fund&code=000001 → source=tencent，序列为 7.248/7.208（平安银行 sz000001）
  ```
  110022 是**易方达消费行业**（场外基金，净值约 2.78），146.88 是 `sh110022` 的转债/交易所序列；000001 华夏成长混合净值 1.295，返回的却是 `sz000001` 平安银行。**同一代码在两个市场指代两个不同品种。**
- **根因**：`tencent_provider.py:20-27` 的 `_symbol()` **只看数字前缀**（`0/3/12/15/16/18` → `sz`，`5/6/9/11` → `sh`），不知道传入的 `type_` 是 fund；而 `:286` 把它注册进了 `["stock","fund"]` 的备源链。同文件 `:33-45` 的 `_hk_symbol` 注释里写着"绝不能复用 `_symbol`"——**同一个陷阱在港股侧被识别并规避了，在基金侧没有**。正确判据在项目里是现成的：`akshare_provider.py:145-147 _is_exchange_traded_fund()`（场内 ETF/LOF 前缀集合），新浪备源正是用 `_etf_symbol`（`sina_provider.py:18-23`）返回 `None` → `ProviderNotSupported` 来拒绝场外代码。
- **影响链**：web `/api/kline` 拿到后会按 `(type,code,date)` `upsertCandles` 落 `KlineDaily`（`lib/kline.ts` 增量缓存路径）→ **持久污染**；随后详情页 K 线图、区间最高/最低（`page.tsx:173-174`）、R11 归因、R13 双源比对、研报回读（`adapter.py:121-128`）全部消费这批错数据，且 `chain.py:31-36` 会给它加"已降级"的可信 note。违 C26（跨类型唯一键必须含 type）、§C-4（腾讯是**场内**备源）、R16（不得把无据渲染成有据）。
- **当前库状态（只读核对）**：`KlineDaily` 中 `type='fund'` 的 639 条非场内前缀行仍是 4 位小数的真净值，`fund/110022` 128 行 close=2.781/2.82/2.828，`fund/000001` 无行——**尚未被污染**。触发条件已经具备，任何一次命中该路径的真实取数（含 test-p2）就会写入。
- **为什么测试没抓到**：`test_tencent_minute.py:161-180` 用 `012414` 演示主备链降级，而该代码恰好**没有**深市同号品种，串号不可见。000001–004499 是场外基金最密的号段，全部与深市股票撞号。
- **复现**：`curl "http://127.0.0.1:8000/kline?type=fund&code=110022&start=2026-06-01&end=2026-06-30"`（东财冷却期必现；主源正常时返回 `source` 含 `fund-nav`）。
- **建议**：`_symbol_for()` 对 `type_=="fund"` 除非 `_is_exchange_traded_fund(code)` 一律返回 `None`（→ `ProviderNotSupported` → 上层显式降级）；顺带核对腾讯日 K 是否遵守 `start/end`（实测 000001 请求 2026-06 窗口返回 2024 年起的序列）。按 C34 需配 🔁 反向验证（撤守卫 → 断言场外代码被拒）。**修好之前不建议跑 verify-all**（test-p2 步骤 [3]/[8b] 正是这条 URL）。

### 详述 · P2

#### CR9-2（P2）· A3 的"异常退出"分支把服务端错误全覆盖

`api/chat/route.ts:260-279` 在 catch 里发 `event: error` 后 `finally` 直接 `controller.close()`，**不再发 `done`**。客户端 `ChatUI.tsx:333` 因 `done` 而 `break`，此时 `gotDone=false, expired=false` → `classifyStreamExit` 判成 `abnormal` → `:360-361` 无条件 `setError("连接中断，回答可能不完整——可直接重新发送")`，把 `:302-304` 刚写入的**唯一可行动文案**（如"LLM 未配置：请在 web/.env 设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL…保存后重启 dev server 生效"）覆盖掉。即任何一次服务端显式报错，用户都会被告知"网络断了"，并被引导去做一件无意义的事（重发）。违 R16（失败原因如实呈现）/ R17。**建议**：`handleEvent` 里记 `sawErrorEvent=true`，收尾时若为真则不再覆盖。与 CR7-1 的"dataBased 恒真"同属修复只做了一半——A3 达成了"有出口"，但出口在最常见的分支上说错了话。

#### CR9-3（P2）· 令牌计数单位与真实 HTTP 请求数差一个量级

`_EM = get_limiter("eastmoney")`（`pipeline.py:58`）按"**逻辑请求**"计次（C29 的明文口径），一次 `acquire` 对应**一次 akshare 函数调用**。但 akshare 的函数不是单请求：`ak.stock_board_concept_name_em` 内部走 `fetch_paginated_data`（site-packages `akshare/stock/stock_board_concept_em.py:47`，~900 个板块 ÷ pz=100 ≈ 9 页）；`ak.stock_board_concept_cons_em(名称)` 更糟——`:421-426` 若 `symbol` 不是 `^BK\d+` 就**先重拉整张板块映射表**（再 ~9 请求），然后 `:440` 分页取成分。调用点 `pipeline.py:258`（`_board_names`）与 `:500`（`map_board_products`，最多 10 次）传的正是**名称**。⇒ 1 个令牌 ≈ 10–20 次真实东财请求，一次 pipeline ≈ 百次级。这与 `limiter.py:3-6` 自己记录的实测事实（"连续 2+ 请求立即触发惩罚，惩罚覆盖其全部域名"）直接矛盾，是 CR7-7 / C0 实测"stock 熔断连坐 hk"的**真正来源**，也是 CR8-1 ③（板块映射未命中噪声）的上游成因。**对既有规划的影响**：CR8-7/OPT-2 立项时算的"单次 pipeline 10 次 acquire、东财必调后更紧"**低估了一个量级**——瓶颈是扇出而不是 acquire 次数，批次二的令牌风险缓解方案（缩短 acquire 超时/重排顺序）打不死这个根。**建议**：把 名称→`BKxxxxx` 映射缓存下来并传 BK 代码（akshare 对 `^BK\d+` 会短路，省掉 ~9 请求），并按成分页计次；同时给 C29 补一条"逻辑请求 ≠ HTTP 请求"的量化事实。

#### CR9-4（P2）· 02:00–08:30 启动 → 当天同步整日不发生

`sync_scheduler._catch_up_if_needed`（`:154-176`）是 `while waited < 600: … else: return`——**唯一出口是 `break`（当日 digest 行数 > 0）**，等满 600s 就 `return` 且不置 `lastDate`，于是当天再没有第二次机会（`add_job` 只在 `DEFAULT_SYNC_HOUR=2`（`:35`）触发，需服务在跑）。而热点侧 `hotspot/scheduler.py:26` 的 `PRE_MARKET=8:30` 之前**不做补跑**（`:96` 直接 return）。两者相加：**任何在 02:00–08:30 之间的启动**，同步都会判定"已过调度时刻"、然后等一个根本不会跑的热点、等满 10 分钟、放弃。第二条独立触发路径：热点跑了但**当日 0 行产出**（`run_pipeline` 在 `items` 为空时根本不 POST，`pipeline.py:642`；或 `emit_ingest` 被 401 拒），count 恒 0 → 同样必放弃。另有口径反转：`:161` 非 2xx → 当作 0 行继续等，`:165` 请求异常 → `break` 放行。`test_c1_catchup_yield.py` 的 5 个用例覆盖了"热点在跑""已有产出""永不结束""已同步"，**恰好没覆盖**"热点 idle 且 count==0"这一条，且用例④名字（before schedule）与实际断言（`lastDate`）不符。**建议**：用热点侧完成态（`hotspot_scheduler._state["lastResult"]/lastRun`）区分"还没跑"与"跑完但没产出"，后者直接 fall through 去同步；补 2 个用例。

#### CR9-5（P2）· `POST /sync/run` 的 type 无白名单，未知类型记成功并抑制当天同步

`main.py:268-275` 把 `type` 原样放进 `payload`，`sync_scheduler.py:71-73` 遍历 `payload["results"]` 里的未知键得到空结果，`:93-101` **无条件**把 `lastDate` 置为今天并把本轮记为成功。后果：一次拼错的类型（如 `heek`/`HK`）会让补跑看门狗（`:146` 读 `lastDate`）与调度器认为"今天已同步"，**当天真实同步被静默抑制**，而 `/sync/status` 显示成功。CR7-10 已把该端点异步化，但没补 type 校验（CR7-6 的校验只做了 web 侧 BFF）。**建议**：进 `_execute` 前用 `get_list_provider(t)` 试解析，未知类型显式失败且**不置 lastDate**。

#### CR9-6（P2）· 币种只在"主源 + 现价"成立

CR7-4/B2c 的账本做法原文写的是"详情页现状区/**指标卡**、搜索结果、`toolGetQuote` summary"。实测：`page.tsx:281` 的现价接了 `priceWithCurrency`，但 `:169-174` 的今开/昨收/最高/最低与 `:370-373` 的 K 线明细表只调 `fmtPrice`；`browse.ts:103-117` 的 `BrowseItem` 根本没有 `currency` 字段（`browse.ts` 不在 d4c9703 的改动清单里），而 `search-client.tsx:317` 渲染的正是它 ⇒ `/search?type=hk` 的 20 个港股价格全无单位。更关键：**`tencent_provider.py:91-105` 的行情 dict 不返回 `currency`**，而 hk 的备源恰是 tencent ⇒
```
curl ":3000/api/quote?type=hk&code=00700" → {"price":436.6,"source":"tencent","note":"主源不可用，已降级至 tencent（…）"}  ← 无 currency
```
即东财一冷却（本机常态），详情页只剩"436.6"、`profile.ts:85` 的"计价：港币"也消失——正是 CR7-4 当初要消灭的现象，只是换了一条链路复现。**建议**：tencent 按 `type_` 补 `currency`（A股/场内基金/转债=CNY，hk=HKD，us=USD）；指标卡/明细表/浏览复用 `priceWithCurrency`；顺带把 `browse` 的 `stale`（`:112`，零消费者）显出来或删掉（CR9-19）。**验收须配断言**：备源路径（`source="tencent"`）下 currency 仍非空——现有 `currency.test.ts` 只测纯函数，所以这条缺口对测试不可见。

### 详述 · P3

| 编号 | 现象与证据 | 复现/判定 |
|---|---|---|
| CR9-7 | `akshare_provider.py:275-280` 出 ISO、`tencent_provider.py:99` 出 `f[30]`（A股为 14 位紧凑串、港股为 `YYYY-MM-DD HH:MM:SS`），`page.tsx:295` 原样拼接渲染 | `curl ":3000/api/quote?type=stock&code=600519"` → `"timestamp":"20260924161444"`，详情页显示成 14 位数字串。建议：provider 侧统一 ISO，web 侧统一格式化 |
| CR9-8 | `providers/__init__.py:39-40` 称 hk 经 `register_chain` 注册、`get_provider("hk")` 抛 KeyError；实际 `hk_provider.py:326` 用 `register(["hk"], …)` | 该注释是 CR7-14-④ 的"实证核对"产物，本身是新的漂移。只改注释，但要点破：**"标了实证"不等于已核对** |
| CR9-9 | `market-snapshot.ts:12` `EM_TYPES={"stock","bond"}`，`:127-129` 据此决定是否 `sleep(1500)`；hk 的批量行情走 `hk_provider.py:148-159` 东财 `ulist.np` | hk 约 4707 只 = 48 批，逐批无限速进同一令牌桶。**⚠️ 未实测失败批次率**，不建议按断言下结论；修法 = 把 hk 纳入限速集合（间隔按实测 12/分钟定），不是抽公共常量（CR6 保留项 7） |
| CR9-10 | `api/events/route.ts:7-12` 只判非空 code；`tools.ts:236/:265/:382` 把 LLM 给的 type/code 直送 ds | 与 CR7-6 的 `lib/validate.ts` 单一来源口径不一致。影响有限：`events.ts:101` 有 type 门（非 stock 不取数）+ 进程内 TTL 缓存；实测任意 code 0.32s/0.02s 返回。端点无 UI 消费者（只有 `scripts/test-p2.mjs:277`）→ **接线或显式裁剪，二选一** |
| CR9-11 | `chain.py:84` 只要"尝试过"就 `checked+=1`，`:114` `crossChecked = checked > 0`；`VerifyQuoteButton.tsx:52-61` 用 `note.includes("偏差")` 决定琥珀/灰 | 实测 `/api/quote/verify?type=stock&code=600519` → `"crossChecked":true` 且 note 写"交叉验证源 akshare 不可用"。当前 UI 不踩（note 非空时优先显示 note），但契约对外是假声明；子串承载语义与 OPT-1 的结论相悖。建议加机器可读字段（`compared`/`reason`） |
| CR9-12 | `kline.ts:95-110` 只匹配形态，`dayStart`（`:71-73`）对非法历法得 Invalid Date，比较全 false → 放行 | 实测 `?start=2026-02-31&end=2026-03-05` 两次均 200，返回区间从 03-03 起（窗口被静默改写，无 note）。建议：`!Number.isFinite(dayStart(s))` → 400 |
| CR9-13 | `ProductCharts.tsx:144-158` 的回落只在 `catch` 内；`kline.ts:219-233` 的 1m 透传把 `note` 置 null | C6b 计划原文含"请求失败/**返回空 candles**"，代码只覆盖前者；空 candles 时用户仍看到空图（与 R15 相悖），且降级 note 丢失 |
| CR9-14 | 门禁实测：`tsc --noEmit` 0 错；`vitest run` **181/182**（失败项 `gateway.test.ts:83-87`）；ds **12** 个离线套件全绿（cr7_research 23 / p2_m8 49 / g6_hk 28 / tencent_minute 18 / backup_db 19 / cr6_lru 18 / cr6_pipeline 10 / cr6_timeutil 6 / g3_crosscheck 8 / c1 5 / c3 5 / d3 9 = 198），但其中 2 个必须加 `PYTHONIOENCODING=utf-8` | `check()` 用 `print("OK"/"NG "+name)` 输出，而 CR7 起的用例名里带 🔁（`test_cr7_research.py:42`、`test_p2_m8.py:29`）——GBK 控制台下整脚本抛 `UnicodeEncodeError`。账本/PROGRESS 记的"8 套件""182/182"都不可按原命令复现。建议：用例名去 emoji（或 `sys.stdout.reconfigure`），并把 `gateway.test.ts:83` 改为 mock ds 或显式传 timeout |
| CR9-15 | `tests/test_backup_db.py:64` 断言尾部 `\| … if f != basename(dest)) or True` → 恒真 | 该用例想验"失败产物不残留"，实际永不失败；紧随其后的 `len(dbs)==1` 才真正兜住。C34 要求反向验证，恒真断言属假覆盖，删掉 `or True` 让其成为真断言（或删整条并说明由下一条覆盖） |
| CR9-16 | `akshare_provider.py:424-427` 用 `_date.today()` 算 1m 的 `beg/end` | §B 明文"data-service 一律用 `timeutil.beijing_*()`，禁用 `date.today()`"（CR-06）。本机 TZ=Asia/Shanghai 无症状，容器/异时区主机上会取到"昨天"→ 空序列 → 502 |
| CR9-17 | `akshare_provider.py:605-611` 的 `df["季度"]` 不在任何 try 内（try 只包 `_ak_request`） | 上游改列名 → 裸 `KeyError` → `/fund/holdings` 500，而非 R10 要求的 200+degraded。同文件 C2 已为"列缺失"建了显式降级范式（`:362-380`），照搬即可 |
| CR9-18 | `limiter.py:118-121` `get_limiter(name, **kwargs)` 首调用创建即固定；`pipeline.py:58` 无参先创建，`akshare_provider.py:70-78` 的显式调参被忽略 | 当前默认值（`:25-30`）与显式值恰好相同 ⇒ 无症状。但 CR8 批次二若要调东财参数，**改哪一处都不会生效**。建议：集中一处创建，或 `get_limiter` 对冲突 kwargs 抛错 |
| CR9-19 | `QuoteCard.tsx` 零 importer（含 `:92` 的裸 timestamp 渲染），且自带缺 `currency` 的私有 `Quote` 类型；`browse.ts:23/:112` 的 `stale` 零消费者 | 属 CR7-3"能力已在、消费侧无出口"同族的反向形态（组件已在、无人消费）。删文件/删字段，或接线，不留模糊态 |
| CR9-20 | `api/market/refresh/route.ts` 仍 `maxDuration=800` | 同一轮 C3 以实测把 `/api/sync` 抬到 1500；刷新（全类型快照）耗时**从未实测**。建议：先测再一次定数，不照抄（CR7-9 的教训就是"不要按注释 tuning"） |
| CR9-21 | `web/.env.example` 只有 8 个键，缺 `INGEST_TOKEN`/`ALLOWED_ORIGINS`；`api/hotspots/ingest/route.ts:10-12` 是 `if (expected && …)` 形态 | 键未设 ⇒ 校验整条跳过（fail-open）。compose 侧由 `docker-compose.yml:31` 的 `${INGEST_TOKEN:?}` 强制，所以只有**开发态**暴露。G7 关联，但属"模板缺键导致静默失去保护"，可独立补 |
| CR9-22 | `sync_scheduler.py:56` 有 `_web_base()` helper，`:159` 内联读 env；`:161` 非 2xx→继续等，`:165` 异常→break 放行 | 口径不齐 + 未来改 base 会漏一处。与 CR9-4 同文件，建议同批修 |
| CR9-23 | 状态/指针层：① `PLAN.md:31`(R13)/`:427`(G3) 结论仍写"⬜ 待实施"且把 BFF 写成 `?verify=1`（实际 `/api/quote/verify`，且 09-25 已上线）；② `FIX-LEDGER.md:295` D4-④ 仍标"⬜ 待办"而看板 `:33` 已记闭环、代码在 `providers/__init__.py:31-41`；③ `PROGRESS.md:26` 验证基线仍写 vitest **148/148（24 文件）**而同一文件 `:29` 写"CR7 全闭环"；④ `CODE-REVIEW.md:9/:25` 曾写"CR7 仍开放"；⑤ `.claude/rules/project.md:89` 仍写"当前开放轮次 CR7"（**未改**，因不在 docs/ 范围，待主人点头）；⑥ `FIX-LEDGER.md:140` 与 `CODE-REVIEW.md` 附录「整理期新增排除」称"C1–C34 的 34 条定义全在工作树 / `grep -cE … PLAN.md` = 34"——**为假**：实测工作树里 `docs/PLAN.md` 该 grep 返回 **0**，`git show d6ac165:PLAN.md` 亦 0，C1–C34 正文在 `docs/CONSTRAINTS.md`（表格式 34 行），`PLAN.md:8` 已明文"C 正文在 CONSTRAINTS" | 这一批没有行为后果，但会误导下一次改动（尤其⑥——它使一条**已核验排除**的证据命令失效，未来复跑会得出"约束丢了"的相反结论）。⑤ 需要主人点头，因为它在 `.claude/rules/` 不在 `docs/` |

### CR9 追加（同日 14:0x，实跑集成时发现的 2 条）

#### CR9-24（P2）· 长驻服务不带 `--reload` ⇒ 此前所有"实测/终验"都可能在跑改动前的代码

- **现象**：CR9-1 的守卫落码并提交（`7edc9ef`）后，直连 `GET :8000/kline?type=fund&code=110022` **仍返回 `source=tencent` 的串号数据**——因为 uvicorn 以 `"E:\python\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000` 启动，**无 `--reload`**，进程内是改动前的模块。
- **为什么严重**：本项目的验收高度依赖"本地实跑"（CR7 的集成终验、CR8 的界面实测、以及各条"手测待主人抽查"），而**代码改动对运行中的进程不可见**。这意味着任何"我改了 → 我实测通过"的记录，若中间没重启服务，其证据可能是**旧代码**的结果。反向风险同样存在：改坏了但没重启，看起来还是好的。
- **本轮的处置**：集成 `verify-all` 在跑到 test-db/p1（均 exit=0）后、p2 之前**主动中止**，正是为了避免用旧代码去验新守卫、并避免 p2 步骤[3] 把串号数据写进 `KlineDaily`（中止后只读核对确认**未被污染**：`fund/110022` 128 行仍是 2.7–2.8 净值，全库 `type='fund'` 无 `close>50` 行）。
- **历史证据的可信度分级（不回改记录，只标注）**：`FIX-LEDGER` 里凡"已实施 + 集成全绿"的条目，只有在服务已重启的前提下才成立；CR7 的 09-25 终验与 CR8 的 09-24 实测**均未记录"重启"这一步** → 标 ⚠️ 存疑，待下一次复跑时一并证真/证伪。
- **建议**：dev 启动命令加 `--reload`（README `:36` 的现命令不含），或在账本的"实测证据"一栏强制附一条**改后探针**（如 `curl` 一条断言新行为）。属流程约束，需要主人选一种固化方式。

#### CR9-7 严重度补记：紧凑时间戳会让 R13/V1 同族的当日交叉验证**必然假失败**

- 追加实测：ds 离线服务耦合套件 `tests/test_p0.py:91-96` 计算 `q_day = timestamp[:10].replace("-","")`——东财主源给 ISO 时得到 `20260925`，**腾讯备源给 `20260924161444` 时截出来是 `2026092416`**，于是 `same_day` 恒 False，断言 `same_day and |price-close|<0.01` 在**价格完全相等**（1237.0 vs 1237.0）的情况下仍然失败。
- 结论：CR9-7 不只是显示层可读性问题——**只要报价来自备源，这条 R13/V1 同族的守卫就被静默废掉**（今天即复现）。严重度按 **P2** 处置，修法优先在 provider 边界统一 ISO（`tencent_provider.py:99` 按 `YYYYMMDDHHMMSS` 解析），而不是各处格式化。



### CR9 追加二（09-26 14:2x–15:0x，集成实跑 + 浏览器手测所得）

> 背景：主人要求今天把 CR7 判到底。做法 = 用新代码重启 data-service → 跑完集成 7 套件 → 用浏览器实点补 CR7 挂着的 3 项手测。过程中得到 3 条新发现与 1 条自我更正。

#### CR9-25（P3）· 集成套件不声明"应跑总数"，被跳过的断言不计失败仍 exit=0

串行 `verify-all` 时 **test-p5 报「17 通过 / 0 失败」exit=0**，而 `ok()` 调用点有 21 处；单独复跑同一套件得 **21 通过 / 0 失败**。⇒ 串行负载下有 4 条断言所在分支**根本没执行**，而套件把"没跑"和"跑过且通过"合并成同一个绿色数字。历史上 P5 的验收数被记成 17 / 19 / 21 三种（见 `PROGRESS.md` 基线行与 `FIX-LEDGER` 09-25 终验行互不一致），根因即此，不是数据记错。**这条直接削弱"7 套件全绿"作为闭环判据的强度**：全绿 ≠ 全跑。建议：每个套件打印 `通过/应跑` 并把跳过显式计为 SKIP（或断言总数）。

#### CR9-26（P2）· hk 与 crypto 主数据为 0 行 ⇒ 这两类的消费侧从未在真实数据上跑通

- **实测**：`Product` 按类型计数 = `fund 27954 / stock 5913 / bond 1059 / us 1 / **hk 0 / crypto 0**`。
- **后果**：`/product/hk/00700` 直接 **404**（`page.tsx:66 if (!product) notFound()`，浏览器实测页面只剩"404 This page could not be found"）。CR7-4 修的是工具枚举 / 身份画像 / 币种三处消费侧，代码确实在（`tools.ts:20`、`profile.ts:83+`、`currency.ts`），但**库里没有一行 hk 产品**，所以分类浏览、详情页、搜索命中 hk 这条真实路径从未被验证过——CR7-4 的"手测待主人抽查"不是没做，而是**当时也做不了**。同一形态波及 crypto（0 行）与 us（仅 1 行 AAPL）。
- **为什么一直是 0**：09-26 14:38 那次真实同步（`runs=1`、455s）里 hk 记为 `error: "eastmoney cooling down (rate-limited); fallback to backup source"`、`tookMs=13`；清掉本地熔断后重跑（21.5s）得到 `hk eastmoney request failed on all hosts: RemoteDisconnected` ⇒ **东财 hk 列表接口本机今天不可达，且列表按设计没有备源**（CR6 排除表已记"hk 列表无备源，靠 C1 空载荷 + 70% 缩水保护双兜"）。crypto 则因本地代理未开长期失败。
- **附带一条误导性文案（同一处）**：`error` 里的 **"fallback to backup source" 是假的**——列表路径并无备源可用，用户/运维看到这句会以为已降级成功。与 CR8-1 的"文案合并三种成因"同族（`R16` 如实呈现）。
- **建议**：① 把"主数据类型完整率"变成一条可断言的观测（`/api/stats` 或 test-db 增一条"六类各 >0"断言），别让 0 行静默存在；② 列表侧失败文案去掉"已降级"字样；③ 真要交付 hk/crypto，需要先解决可达性（hk 列表备源 / crypto 代理），这属需求面决策，不在缺陷批里。

#### CR9-27（P3）· 中断提示文案把 180s 写死

手测做法（照账本）：把 `ChatUI.tsx:328` 的 deadline 临时改 `3_000` → 发送 → 页面出现 **"回答在 180s 处中断，本条可能不完整——可直接重新发送"**。功能判定 ✅（R17 达成：中断可见且有出口），但文案里的 180s 是硬编码字符串，与常量不同步——将来调 deadline 就会说谎。建议：由 deadline 常量插值。

#### CR9-5 自我更正（严重度 P2 → P3）

登记 CR9-5 时我写的是"`/sync/run` 无 type 白名单，可静默抑制当天同步"。今天复核 web 侧：**`api/sync/route.ts:22-26` 确实有 `SYNC_TYPES` 白名单**，所以浏览器/调度回调这条主路径是被守住的；缺口只剩 **ds `/sync/run` 直连**（内网端点，C9 规定浏览器只与 web 通信）⇒ 触发条件是"运维手敲错类型"，不是用户可达路径。按本文件的口径应记 **P3**，其余结论（未知类型仍置 `lastDate`）不变。

**教训回记**：本轮两次误判（上一条 CR8"已写未提交"、这一条 CR9-5 定级偏高）都源于**采信并行审计代理的陈述而未先复核**。已在文末排除表写下纪律：subagent 关于 git 状态 / 路由守卫 / 文件存在性的结论，必须由我自己用 `git status`、`grep`、`curl` 复一遍才能入账。

### CR9 追加三（09-26 15:2x–16:0x，批次一实施所得：1 条撤回 + 2 条新发现）

> 主人指令"先修 cr9"，按本账本批次一实施。实施前逐条回代码复核原指控，**结果推翻了我登记的一条**。

#### 撤回 CR9-5（原指控不成立）

登记时写的是"`POST /sync/run` 无 type 白名单，未知类型记成功并抑制当天同步"。实施前复核：`main.py:259` 的 `def sync_run(trigger: str = Query(...))` **根本没有 `type` 参数**，`_execute` 也是无参 POST `/api/sync`（同步全类型）；而 web 侧 `api/sync/route.ts:22-26` 本来就有 `SYNC_TYPES` 白名单。**这条指控的前提不存在**，撤回（原已在追加二里降为 P3，现整条撤销）。根因仍是同一条：审计代理给的行号我未复核端点函数签名就入账——已把"登记'某参数缺校验'前必须读该端点签名"补进文末排除表的纪律。

#### 新发现 CR9-28（P2，取代 CR9-5 的位置）· `/sync/status` 的 `ok` 与真实结果脱钩

`sync_scheduler._execute:75` 把结果硬写成 `{"ok": True, ...}`，而 web 返回的是真判定 `results.every(r => !r.error)`（`api/sync/route.ts:33`）。
- **实测**：09-26 14:38 那轮同步 `GET :8000/sync/status` → `lastResult.ok=true`，而 `results` 里 **stock/bond/crypto/hk 四类全带 error**（只有 fund 成功）。
- **为什么严重**：`/sync/status` 的 `ok` 是唯一能判断"今天要不要补跑"的状态位；它说谎就等于把"四类主数据今天没更新"这件事对运维隐藏。CR7-4 手测之所以今天做不了（hk 0 行），正是这类状态失真的下游后果。
- **修法（已实施）**：跟随 web 的 `ok`，并附 `failedTypes` + 显式 `note`；**失败类型不自动重试是有意取舍**（整轮同步实测 455~561s，反复重试会持续占东财源族，与 CR7-7/C1 的让位设计相冲），故只暴露缺口、不改调度行为。
- **验收**：`data-service/tests/test_cr9_sync_status.py` 7 项，含 C34 反向对照（"全成功仍为 True"证明 `ok` 不是恒假桩；"失败轮仍置 lastDate"锁住那条取舍，将来要改必须先改文档）。

#### 新发现 CR9-29（P3）· 腾讯日 K 不返回 `amount`，备源服务时字段契约不齐

`GET :8000/kline?type=stock&code=600519`（东财冷却、由 tencent 服务）→ candles 每行只有 `date/open/close/high/low/volume`，**无 `amount`**；`test_p0.py:82`「kline 字段完整（volume/amount 非空）」因此必挂。这与 CR9-6（缺 `currency`）、CR9-7（`timestamp` 三形态）是**同一个根因的第三种表现：降级路径丢语义字段**。修法：补齐 amount，或在备源显式标注该字段不可用——与 CR8-1 拍板的 `reasons[]` 方向一致。

#### 批次一实施结果（修 4 撤 1，证据）

| 项 | 实现 | 证据 |
|---|---|---|
| CR9-2 | `chat-stream-exit.ts` 加 `sawError → "errored"` 第四形态；`ChatUI` 记 `sawErrorEvent`，收尾时 `errored` 不覆盖服务端真因 | `chat-stream-exit.test.ts` +3（含"error 与到期同时成立仍判 errored"）；vitest **185/185** |
| CR9-6 | `tencent_provider` 新增 `CURRENCY_BY_TYPE`；`browse.ts` 透传 `currency`；详情页指标卡走 `priceWithCurrency`、日线表头标一次币种（不逐格加，避免噪声） | `test_g6_hk` 断言 hk 备源 `currency=HKD`、`test_p2_m8` 断言 A股 `CNY`；实网 `stock/hk/fund` 三查均带正确币种 |
| CR9-7 | `_ts_iso()` 在 provider 边界统一 ISO；**实施中实测出第三种形态**：港股是 `2026/09/18 16:08:32`（斜杠+空格，非我登记时写的连字符），故改成"只取数字"归一而非逐个 replace；不满 14 位原样返回不猜 | 首版实现漏斜杠形态 → `test_g6_hk` 精确失败 1 项，修正后 32/32；`test_p2_m8` 原断言 `== "20260911150000"` 实为把缺陷锁成契约，已改断言 ISO |
| CR9-27 | `deadlineMs` 常量与提示文案同源插值 | 同上 vitest |
| CR9-28 | `_execute` 跟随真 ok + `failedTypes`/`note` | `test_cr9_sync_status` 7/7 |

**回归面**：ds 离线 14 套件全绿（新增 `test_cr9_sync_status`；`tencent_minute` 20、`g6_hk` 32、`p2_m8` 50）；`tsc` 0 错；vitest 185/185。**p0（服务耦合套件）今天 13/15**，两条失败分别是"detail 文案随熔断状态变化"（环境态）与 CR9-29（真实缺口），非本批引入。提交 `000d721`。

> **CR9 合计（追加二时点的实况，2026-09-26 15:2x）**：**29 项 = P1×1 + P2×8 + P3×19 + 误报撤回×1**；已修/处置 7 项，余 21 项。**最新计数看本文件末段「CR9 追加六」的合计行，权威口径在 [FIX-LEDGER.md](FIX-LEDGER.md) 速览**——本行只作该时点的快照留痕，不再充当"最新"。



### CR9 追加四（09-26 17:1x–18:0x，批次三实施所得：3 条新发现，2 修 1 待判）

#### 新发现 CR9-30（P3）· 限速态下 `/quote` 的 detail 丢掉标的标识，错误无法归因
`main.py` 的 `/quote` 在 `ProviderError` 时 `detail=str(e)`，而 `_em_request` 被限速拒绝时的文案是
`"eastmoney cooling down (rate-limited); fallback to backup source"`——**整句与入参无关**。
于是东财冷却期间 `detail` 里不再有代码，`test_p0`「quote 不存在代码 → 502 + detail」必挂。
今天该形态出现两次（16:4x、17:5x），每次都把"是环境噪声还是真回归"变成不可判定——
**这不是环境问题，是可诊断性缺口**（同族：CR9-26 的"失败文案谎称已降级"）。
**修法**：端点边界补主语 `detail=f"{type}/{code}: {e}"`，逐源理由原文保留在后。
已修，证据：`test_cr9_symbol_guard` 新 3 项（强制 `EM_LIMITER.acquire` 恒假 → 502 + detail 含 `stock/999999` + 逐源理由不吞）。

#### 新发现 CR9-31（P3）· 东财债列表超时降级后，`/products?type=bond` 只剩 327/1059 行
16:44 实测：`bond list primary (em) failed: ak.bond_zh_cov 超时（>90.0s），已放弃等待并降级`
⇒ 同一次 `test_p1` 得 `count=327`（断言要求 >500）；16:59 主源恢复后同一端点 **1059 行 / 5.7s / 无降级 note**。
⇒ 降级路径的**覆盖面只剩 31%**，且那次降级响应是否带 note **未采集到**（响应已过期，不假装知道）。
与 CR9-26（hk/crypto 列表按设计无备源）同族：**列表类备源的覆盖率从来没有被断言过**。
**未修**，需先实测备源列表的真实口径（327 是"备源本来只有这些"还是"分页被截断"）。

#### 新发现 CR9-32（P3）· `kline-range.test.ts:34-38` 是一条我复现不出来、却稳定通过的绿用例
用例名"end 非法 → error（点名 end）"，实际入参是 `normalizeRange(null, "2026-06-30")`——
**合法日期**。按当前源码它不该返回 error；实测确认：
- 独立探针文件连调 3 次同结果 `{start:"2026-06-28", end:"2026-06-30"}`（无 error）；
- 在该测试文件内插 `console.log`：`r` = `{error:"invalid end format ...: 2026-06-30"}`，而**同一行里紧接着的另一次同参调用返回正常**；
- 字面量字节核对为纯 ASCII `2026-06-30`（无全角/零宽/尾空格）；清 `node_modules/.vite`（仅 4K）后仍 6/6 绿。
⇒ 同一函数、同一入参，在同一 tick 内给出两种结果，我给不出解释。**这条与 CR9-15 的 `or True` 同属"绿色不等于有效"**，
且它比 CR9-15 更危险：断言看着具体、跑着恒过。修法方向：把它换成显式的非法入参（`2026-06/30` 或 `20260630`）并断言点名 end——
CR9-12 的新用例已经覆盖了这一形态，所以**本条现在的实际价值只剩"别拿它当证据"**。⚠️ 待主人判定是否直接改写。

#### 批次三实施结果（修 10 项：CR9-8/11/12/13/15/16/17/21/25/29/30）
| 项 | 落点 | 证据 |
|---|---|---|
| CR9-15 | `test_backup_db.py:70` 去掉 `or True`，改为断"失败路径不得新增 dev-* 产物" | 🔁 反向实证：注入一个泄漏空壳 → 该断言与"仅 1 个产物"同时变红；无泄漏时实测确无残留 |
| CR9-8 | `providers/__init__.py` 注释纠错 | 实测 `get_provider("hk")` → `akshare-hk`、`get_provider("us")` → KeyError；原注释两句皆错 |
| CR9-16 | `akshare_provider.py` 三处本地 `date.today()` → `beijing_today()`/`beijing_now().year`，删掉局部 `from datetime import date as _date` | `test_p2_m8` 新 4 项（把 `beijing_today` 钉成 `2026-03-31` 断请求 beg/end + 源码内不再出现 `date.today()`） |
| CR9-17 | 缺「季度」列 → 显式 `ProviderError`（含实际列名诊断），不再裸 `KeyError`→500 | `test_p2_m8` 新 3 项 + 正向对照；🔁 旁路守卫 → 精确复现 `KeyError: '季度'` |
| CR9-12 | `normalizeRange` 加历法校验（`dayStart` 回环比对），非法历法 → `{error}` → 路由 400 | `kline-range.test.ts` 新 5 项，含**闰年 2024-02-29 必须放行 / 非闰年 2026-02-29 拒绝**的成对断言 |
| CR9-13 | `ProductCharts` 回落动作提为 `fallbackToDaily3M()`，新增"200 + 空 candles"触发；`kline.ts` 1m 路径 `note: ds.note ?? null`（`DsKline` 补 `note` 字段） | 行为：软失败不再渲染成无说明空白图；降级说明得以上屏 |
| CR9-11 | `chain.py` 新增机器可读三态 `verifyVerdict`；按钮按三态判色，字段缺失时回落原推断 | `test_g3_crosscheck` 由 8→13 项，其中一条专门钉"备源不可用时 `crossChecked` 仍为 true"这个语义坑；🔁 换 HEAD 版 chain.py → 恰好 4 条新断言红 |
| CR9-21 | `web/.env.example` 实为**半误报**：`INGEST_TOKEN` 已在（注释态），`ALLOWED_ORIGINS` 确缺（`request-origin.ts:29` 在读） | 改成两键均为空值 + 写明 fail-open 语义与暴露面前提；键值一律为空 |
| CR9-29 | 腾讯日 K 实测每行恰 6 字段（**无成交额可取**）⇒ 走"显式声明"而非"补齐"：`amount` 键恒在 + 值 null + 响应 note 说明；`test_p0` 的断言改为**按源分别断** | 离线 2 项 + 实网 p0 该条转绿（本次实网恰好走备源，等于端到端验过） |
| CR9-25 | `verify-all.mjs` 声明各套件应跑断言数并对比实跑数，缺口公开打印（放弃"静态数 `ok(`"方案——循环里的调用点会 0..n 次，p2 就是 43 点 vs 38 实跑，必误报） | 本次 7 套件全跑满：16/16、20/20、38/38、27/27、19/19、24/24、**21/21**（p5 串行不再欠 4 条） |

### CR9 追加五（09-26 23:00 – 09-27 01:0x，批次四：主人按编号拍板 D1–D10 后实施）

> 拍板顺序与结果：D1（CR9-32 处置）→ D3（CR9-19 裁剪）→ D7（CR9-23⑤）→ D6（CR9-24 固化 (b)）
> → D2（CR9-10 接线）→ D5-①（CR9-26 文案＋断言，可达性 D5-② 仍待拍板）→ D9（环境）
> → D4（CR9-3 走 (a)）→ D10（CR9-13 手测，主人自己点）→ D5-②/D8（延后）。
> 本批新登记 **CR9-33/34/35**，并**撤回 CR9-32**（我此前的测量仪器在说谎，不是代码）。

#### 撤回 CR9-32（原指控不成立）· 我的"复现不出"来自显示层把斜杠日期渲染成连字符

发现原文（本文件 `#### 新发现 CR9-32`）写的是"`kline-range.test.ts:34-38` 入参却是合法日期
`2026-06-30`"。**核对字面量字节后推翻**：那一行的实参是 `2026/06/30`——**斜杠 0x2f**，
形态确实非法，`iso()` 正则不匹配 ⇒ 走 `invalid end format` 分支 ⇒ 断言点名 end，
**绿得完全正确**。逐字码点为证（node 读文件，非肉眼）：

```
file literal hex : 32 30 32 36 2f 30 36 2f 33 30      ← 0x2f 斜杠（文件真实字节）
my typed    hex  : 32 30 32 36 2d 30 36 2d 33 30      ← 0x2d 连字符（我"同一行重打的那次"）
```

为什么我会登记成一条"复现不出却恒绿"的用例：**回显给我的文本会把日期形态里的斜杠归一化成
连字符**——`od -c`、`JSON.stringify`、以及我自己在编辑器里重打的字符串三者都显示成
`2026-06-30`，只有打印码点才看见 0x2f。于是"独立探针不报错"与"文件里那条报错"同时成立，
我把它当成了代码缺陷。**教训**：凡"字面量形态本身是被告"的判断，必须用码点/十六进制取证，
不能采信任何渲染出来的文本（含我自己写进探针的那一份）。

配套动作（不改断言语义）：用例名改为"end 斜杠分隔（形态非法）→ error（点名 end）"并加两行
注释，免得下一个人（或下一个我）再踩；反向对照仍在同文件（合法连字符版必须通过）。
**C34 🔁 的取证方式换了**：本想用"原地回退 `kline.ts` 的 end 分支"证明该用例不是恒过，
被权限分类器拦下（不许改生产码试测试）——改用**同文件既有反向对照 + 一次性探针文件**取证：
`normalizeRange(null, 斜杠版)` 的 error 文案**逐字**等于 `invalid end format (expect YYYY-MM-DD): <入参>`，
`normalizeRange(null, 连字符版)` 返回 `{start:"2026-06-28", end:"2026-06-30"}`（探针跑完即删）。

#### 新发现 CR9-33（P3）· 一轮同步的耗时差一个数量级，而超时预算只按慢的那一侧定
09-26 的补跑态实测整轮 ≥29 分钟、打穿 `requests.post(timeout=1800)`（PROGRESS 已记）；
09-27 **23:00 定时态**同一批类型 `runs=1` 总耗时约 **430s**（fund 单类 358s、stock 41s、
crypto 43s、bond 1.3s、hk 4ms）。⇒ 30 分钟不是同步的固有成本，而是**补跑态与定时态的形态差**；
`/api/sync` 的 `maxDuration=1500` 与调度侧 1800s 只在定时态成立。修法待拍板：要么按形态分别设预算，
要么让补跑态自带分批/续跑（与 CR9-26/D5-② 的可达性决策同批讨论）。

#### 新发现 CR9-34（P3）· 「验证门槛」里的 ds 套件短名不落在任何文件上，照抄命令静默跳过 16 项
门槛原文写"命令：`PYTHONPATH=. .venv/Scripts/python tests/test_<名>.py`"，清单里的
`c1 11`/`c3 5` **不是文件名**（真名 `test_c1_catchup_yield.py`/`test_c3_readtimeout.py`）。
本轮照抄跑批时这两条各报 `can't open file`，而我的循环只看"有没有打印 通过" ⇒ **两个套件被静默跳过**，
差点以"16 套件全绿"入账。修法：门槛里的 16 个名字一律改成可复制的真实文件名，跑批脚本必须带 exit code。

#### 新发现 CR9-35（P3，已随批修）· `test_c1_catchup_yield` 依赖真实墙上时钟，00:00–01:59 跑测必然只剩 3/11
`_catch_up_if_needed` 开头是"未到当日调度时刻（`DEFAULT_SYNC_HOUR=2`）→ 直接 return"。
本套件的 `_run_case` 钉住了 `run_now`/`sleep`/热点 `_state`，**唯独没钉时刻** ⇒
09-27 00:4x 复跑时 8 个用例一律 `{n:0, polls:0}`（看起来像 CR9-4 的修复失效了），实际是被那道门
整体吞掉。修法（只动测试）：`_run_case` 加 `at_hour/at_minute`，默认钉到当天 09:00；
并补 ⑨ 覆盖此前**零用例触碰**的"未到点即跳过"分支 + 🔁 反向对照（`SYNC_HOUR=0` 时同一时刻必须照常同步）
⇒ **13/13**，且任何钟点可复跑。与 CR9-14 同族：门禁的可复现性也要覆盖"什么时候跑"。

#### CR9-31 的未采集项已补齐（仍未修，D8 拍板延后）
09-27 01:0x 实网 `test_p1` 当场红一条：`products?type=bond 返回 200 且数量 > 500 ← status=200 count=327`。
同一时刻直连 ds 取证：`/products?type=bond` → `count=327`，响应键只有 `type,count,products`——
**没有 `source`/`degraded`/`note`** ⇒ 原登记里那句"那次降级是否带 note 未采集到"现在有答案了：
**降级态对消费侧完全不可见**（违 R16）。327 与 `sina_bond_provider` 文档记的"新浪 cov_spot 全量约 320 只"
吻合 ⇒ 是备源天然覆盖面，不是分页截断。**这是环境态不是今日代码回归**（同一时刻 p0 15/15、其余 15 个离线套件全绿）。

#### 批次四实施结果（修 5 项 + 撤回 1 项：CR9-32 撤回、CR9-19/23⑤/24/10/26①/3）
| 项 | 落点 | 证据 |
|---|---|---|
| CR9-19 | 删 `web/app/components/QuoteCard.tsx`（零 importer）；`lib/browse.ts` 去掉 `stale` 字段与计算 | `grep -rn "QuoteCard" web/app web/lib web/scripts` = 0（只剩 docs 里的历史行）；`tsc` 0 错；观察留档：同结构的 `quoteSource`（`browse.ts:24`、`search.ts:20/215`）同样零消费者，本批**未动**（不在拍板范围内） |
| CR9-23⑤ | `.claude/rules/project.md:89` 轮次指针 CR7 → CR9（主人点名批准这项跨 docs 改动） | `grep -n "当前开放轮次" .claude/rules/project.md` |
| CR9-24 | 走拍板 (b)：门槛新增 **⑤ 改后探针** 条；待拍板第 13 条转 ✅ | 本轮两条探针：ds 重启后 `:8000/quote` 在限速态返回 `主源不可用，已降级至 tencent（akshare: eastmoney cooling down (rate-limited)）`（旧谎称串已不在）；web 侧 `:3000/api/events?type=nope&code=600519` → 400 `unsupported type` |
| CR9-10 | 新增 `lib/validate.ts:checkSubject()`；`/api/events` 与内置工具执行路径（`tools.ts` 的 `guardToolArgs`）统一走它；`PRODUCT_TYPE_ENUM` 改为 `QUOTE_TYPES` 的别名（消除第二份类型数组） | `validate.test.ts` 4→**9**（含"合法入参不得报错"反证）、`gateway.test.ts` +1 条"四条非法入参零次 socket"（探针先自检计数器能记录）、`scripts/test-p2.mjs` +2 条事件接口 400；实网探针见上一行 |
| CR9-26① | `_em_request` 的限速文案去掉 `"; fallback to backup source"`（该函数不知道有没有备源，列表类必然说谎）；`test-db.mjs` 新增主数据**类型完整率**断言 | `test_cr9_symbol_guard` 24→**25**（新增"限速文案不谎称已降级"）；`test-db` 16→**18**，🔁 注入一行未声明类型 `zzz-tmp` → 合计 34927 vs 全表 34928 精确变红、删除后复原且 leftover=0；实测打印 `完整率 4/6｜stock=5913 fund=27954 bond=1059 hk=0 us=1 crypto=0｜缺口：hk,crypto` |
| CR9-3(a) | `pipeline.py`：`_board_names()` 顺带抓 `板块代码` 入缓存；新增 `_board_code(name, source)`；`map_board_products` 有代码就传 BK 代码 | **requests 层计数实证**（09-27 00:1x）：`*_cons_em(symbol="光伏设备")` → **9 个东财请求**（`fs=m:90+t:3` 整表分页），`symbol="BK0446"` → **1 个请求**（`fs=b:BK0446`）；一次 pipeline 最多 10 次映射 ⇒ 百次级扇出。**没动 C29 计次口径**（(b) 路线仍待拍板）。`test_cr6_pipeline` 10→**16**，含 🔁"无代码时按名称请求"证明差异只出自缓存命中 |
| CR9-35 | `test_c1_catchup_yield.py` 钉时刻 + 补 ⑨ 分支 | 见上一条发现原文；**3/11 → 13/13** |

### CR9 追加六（09-27 01:4x–02:4x，主人指令："以 PLAN 的需求为绝对核心准则做全量测试"）

#### CR9-37（P3，已修）· CR9-10 的闸门初版会让 P5 验收②（AAPL 走同一研报链路）失效
- **成因**：我写 `guardToolArgs` 时把 `checkSubject` 的归一化结果整体回写（`{...args, ...v}`），于是**调用方缺省的 type 被填成 `"stock"`**。而 `deep_research`/`get_research_report` 的规则是 `args.type ?? (/\d{6}/.test(code) ? "stock" : "us")`（PLAN M4 的 L2 工具 + 验证方式 P5-②"详情页按钮对 AAPL 触发同一链路"）——回填之后**us 分支永远走不到**：LLM 只发 `{code:"AAPL"}` 就会被按 A股立项研报。
- **第二条同源缺陷**：闸门用 `typeof args.code === "string"` 判类型，而 **function calling 常把纯数字代码发成 number**（`{"code": 600519}`）。改动前 `dsGet` 拼 URL 时自然字符串化、工作正常；加闸门后这类合法调用被当非法直接拒。
- **修法**：**闸门只拒绝、不补全**——只在调用方显式给了 type 时才校验并回写；`code` 一律 `String()`+trim（保留改动前的宽容度）。
- **需求面用例**（`lib/gateway.test.ts` +3）：数字 code 必须放行且以 `code=600519` 出网；缺省 type 不得被回填；非 code 字段（`days`）不得被改写。另补一条 **P4 红线在 schema 层的等价断言**：`PRODUCT_TYPE_ENUM` 归一为 `QUOTE_TYPES` 别名后，发给 LLM 的 enum 取值必须逐项不变（研报两工具仍为 `["stock","us"]`）。
- **教训（并入文末排除表纪律）**：给既有调用链加"更严格的校验"时，验收不能只测"非法被拒"，**必须同时证明合法形态的集合没有被我缩小**——"顺手归一化"（整体回写、类型收窄）正是缩小合法集的典型写法。

#### CR9-38（P3，待拍板，未改）· P4 验收里有一条断言在检查 LLM 自由文本，门禁因此随机红
`scripts/test-p4.mjs:229`：问"贵州茅台的股票代码是什么？"，然后 `ok("第一轮回答包含代码 600519", /600519/.test(t1))`——**答案里带不带数字完全由模型措辞决定**，与工具链、数据源都无关。
09-27 复跑三次：批次里那次 18/19（就是这一条 NG）；单跑第 1 次崩在 dev 服务对该路由返回 HTML（`SyntaxError: Unexpected token '<'`，套件没打印汇总行 ⇒ 按 CR9-25 会被记成 `0/19` 缺口）；第 2、3 次 19/19。
⇒ 两种不稳定都**不是本批改动带来的**，但它们让"集成 7 套件全绿"在这一条上失去判别力。**建议（未拍板不动）**：① 该断言改查 **SSE 的 `tool` 事件**（工具确实按 `code=600519` 调用过）而不是模型散文；② `ask`/`getJson` 加一层"响应不是 JSON 就带状态码显式失败"，别让它以未捕获异常的形式崩掉整套件。

#### 按 PLAN 条目的逐条判定（本批改动的射程内）
| 需求条目 | 判定 | 证据 |
|---|---|---|
| **需求 1 / M1**「相关产品来自**板块成分映射**而非模糊匹配」 | ✅ 未失效（降级路径已实测） | 当日 `/api/hotspots` = 14 条 digest、`related` 逐条非空（样本 9/9/16）；用**最新代码**直接跑 `map_board_products("创新药"/"光伏设备")` → `source=sina·创新药`/`sina·光伏`、各 6 只成分，note 如实列"新浪板块名称未匹配…"。东财名单不可达 ⇒ codes 缓存为空 ⇒ 自动按名称请求 ⇒ **与改动前逐字同行为** |
| ⚠️ 同一条需求的**验收欠账** | ⬜ BK 代码路径的"成分等价"仍无实网证据 | requests 层已实证扇出 **9→1**（`fs=m:90+t:3` vs `fs=b:BKxxxx`），但 `push2.eastmoney.com` 从 09-26 起持续被本机系统代理按 host 拒（`ProxyError`，多次复测同结果），拿不到"两条路径成分是否相同"的比对。**离线已钉**"传代码/传名称走同一解析、同一返回形态"（`test_cr6_pipeline` 16/16）；实网复测命令记在 FIX-LEDGER 的 CR9-3 行 |
| **需求 2 / M2 + R14 分类浏览** | ✅ 未失效 | `/api/search?q=&type=stock&sort=changePct` → `total=5913`、本页 20 条、**20/20 带实时价**、`page 1/296`；字段 `type,code,name,exchange,tags,price,changePct,currency,quoteSource`（被删的 `stale` 从未有消费者，界面不依赖） |
| **需求 2 / 关键词与代码搜索** | ✅ 未失效 | `q=600519` → 命中 1 条，`price=1237`、`currency=CNY`、`quoteSource` 齐 |
| **需求 3 / M3 六区结构 + R16 来源标注 + 免责** | ✅ 未失效 | `/product/fund/110022` 服务端 HTML 含 净值 / 数据来源 / 变化解读 / 明细数据 / 深度分析 / "仅供参考，不构成投资建议" |
| **需求 3 / R11 事件标注** | ✅ 未失效且更严 | `?type=stock&code=600519`、`?type=fund&code=110022` 仍 200（fund 照旧返回显式缺口说明），非法 type/code 转 400。**补一条此前没查的事实**：详情页 `page.tsx:81` 是**服务端直调 `fetchEvents`**、不经这条 HTTP 路由 ⇒ 路由收紧不改变界面行为（我 09-26 的"无 UI 消费者"只说对了 HTTP 侧） |
| **需求 4 / M4 工具链** | ⚠️ 曾被我的闸门破坏（CR9-37）⇒ **已修并钉住** | `vitest` **199/199**（含 3 条新需求面断言）；`test-p4` 单跑 3 次：1 次崩于 CR9-38 的 HTML、2 次 19/19 |
| **需求 4 / P4 红线（工具名 + 寻址面不变）** | ✅ | 9 个工具名等值断言 + **新增 enum 取值逐项断言**（归一常量之后不变） |
| **需求 5 / M5 研报（P5-② AAPL 同一链路）** | ✅（修 CR9-37 之后） | 由"缺省 type 不回填"断言钉住；`RESEARCH_TYPE_ENUM=["stock","us"]` 未动 |
| **M8 / R15 多源降级语义** | ✅ 未失效 | 令牌桶退避后复测 `/quotes?type=bond` 由 `source=sina-bond` 正常交付（备源生效、note 如实）；`/quote?type=bond&code=113050` 的失败逐源可归因（CR9-30 主语 + 不再谎称已降级） |
| **M1 / G2 每日同步** | ✅ 未触及 | 本批未改同步链路；`/sync/status` 形态同 CR9-28 |

**门禁（02:4x 终态；与 01:3x 的差值只有"新增 3 条需求面用例"和"一次 p4 抖动"）**：`tsc` 0 错 ｜ `vitest` **199/199（31 文件）** ｜ ds 离线 **16 套件 288 项全绿**（逐套件 exit=0，强制 gbk 复跑）｜ 实网 **p0 15/15、p1 11/13**（两条红都是外部源态：bond 列表 327＝CR9-31；转债实时行情退避后复测由 sina-bond 正常交付）｜ 集成 7 套件：db 18、p1 20、p2 40、p3 27、**p4 18/19**（CR9-38 那条 LLM 措辞断言）、p6 24、p5 21。

> **CR9 合计与批次去向**：权威计数**只在 [FIX-LEDGER.md](FIX-LEDGER.md) 看板维护**（本文件不复述，避免又一处需要人同步的镜像数字——09-27 速览去重已定过这条规矩）。追加六的落码项＝CR9-10/19/23⑤/24/26①/3(a) ＋ 撤回 CR9-32 ＋ 新登记 CR9-33/34/35/36/37/38；追加七的落码项＝CR9-9/18/20/31/33/38 ＋ 定案 CR9-3(b) ＋ 新登记并处置 CR9-39/40/41。


### CR9 追加七（09-27 10:1x–12:0x，主人指令："按你建议的顺序把剩下的执行完 + 以 PLAN 需求为核心做全量测试"）

> 顺序＝CR9-18 → CR9-9＋CR9-20 → CR9-31 → CR9-3(b)／CR9-26②／CR9-33。**闭 6 项、定案 1 项、新登记 3 项**，其中两条新登记是**我自己的测量错了**，不是代码错了。

#### 新发现 CR9-39（P3，已修）· `verify-all` 从仓库根跑会静默得到"7 套件全部没跑"

门槛④ 的权威命令写的是 `node web/scripts/verify-all.mjs`（从仓库根），而脚本内部是 `spawnSync(node, ["scripts/"+s], {cwd: process.cwd()})` ⇒ 7 个子进程全部 `Cannot find module`，**而那行错误被 tail 的过滤正则吃掉**，输出只剩 `exit=1 断言 0/18`。我照文档跑了一整轮，第一判断是"批次五把集成打挂了"，直到单独跑 `test-db.mjs` 全绿才发现是路径问题。**与 CR9-34 同族但更阴**：CR9-34 是"静默跳过"，这条是**把"没跑"伪装成"跑挂了"**。修法：路径与产物一律相对本文件解析（`WEB_DIR`）＋ tail 正则保住 `Error|Cannot find`。

#### 撤回 CR9-40（原指控不成立）· "hk 行情全 host 不可用"是我的探针用了合成代码

扇出实测脚本里我拿 `00001..00050` 当港股代码打 `/quotes?type=hk`，结果 8 发全挂 ⇒ 我写下"hk 行情今日不可用"。**同一分钟用真实代码复探立刻推翻**：`/quote?type=hk&code=00700` → `436.6 HKD source=akshare-hk`、`codes=00700,00005` 两条都有、`/kline?type=hk` 200（`source=tencent` 备源）。⇒ **hk 取数侧今日健康，本批没有"港股挂了"这条**。合成样本可以测"路径与限速"（批间隔 A/B 就是靠它），**但不能用它对外部源"有没有数据"下结论**。

#### 新发现 CR9-41（P2，已闭环）· crypto 主数据 0 行的根因不是"外网不通"，是我们自己把代理废了

`main.py:12` 为保护国内源设了 `NO_PROXY=*`，而 requests 的 `should_bypass_proxies` 会让**显式传入的代理也被绕过**……代码其实早就为此准备了 `trust_env=False` 的独立会话（`crypto_provider._overseas_session()` + `_proxies()` 读 `HTTPS_PROXY`），**缺的只是没人给这个环境变量赋值**——注册表系统代理在 env 里根本看不见，所以"env 里没有 proxy"这句话只对了一半。同进程两档实测：不设 → `ProviderError: coingecko unreachable`（42s 才失败）；设 `HTTPS_PROXY=http://127.0.0.1:7897` → **`count=250`（BTC/ETH/USDT）**。**已按此配置起服务并跑通端到端**：`POST /api/sync?type=crypto` → 250 行落库、快照 `updated=250/250 failedBatches=0`、`/product/crypto/BTC` 200、`/api/quote?type=crypto&code=BTC` 真价 ⇒ **PLAN P2"股票/基金/虚拟币各验一个标的"从此三条腿都有数据**。类型完整率 **4/6 → 5/6（只剩 hk）**；`test-p2` 因 BTC 可达多出一条 `valueOnly` 断言（**40→41，两档都登记进 `PLANNED`**）。compose 侧本来就透传（`docker-compose.yml:74/103`），**只有本机手工启动会漏**——09-27 15:2x 主人拍板走 **A（零代码）** 并落地：`web/.env.example` 的 R12 块改为空值键 + 机制注释、PLAN「配置项（.env）」加一行"必须与 uvicorn 同行内联 export"。处置与改后探针见 [FIX-LEDGER.md](FIX-LEDGER.md) 待拍板第 14 条。

#### 批次五实施结果（修 6 ＋ 定案 1，全部门禁复跑）

| 项 | 落码 | 断言增量 | 实测依据（不是推算） |
|---|---|---|---|
| **CR9-18** | `limiter.py:PROFILES` 唯一来源；`get_limiter(name)` **签名去掉 kwargs** | `test_p2_m8` +8 | 传参改 `TypeError`（结构上不再有第二条通道）；🔁 改 `PROFILES` 对新建族立即生效 |
| **CR9-9** | 限速集合按源补全为 `stock/fund/bond/hk`；批间隔 1500→**5000** | `market-snapshot.test.ts` +3 | **同日 A/B、同一批转债标的、各 20 批 × 100 只**：@1.5s → 尝试速率 14.3 批/分（＞桶的 12）、非主源 **7/20**、批 14 起连坐熔断；@5.5s（桶清零后）→ 10.1 批/分、非主源 **0/20**、单批 2.69s→**0.58s** |
| **CR9-20** | `maxDuration` 800→**1500** | — | 当日真实批次 stock 60 + fund 30 + bond 11 + hk 48 = **149 个东财批次**；实跑锚点：改后代码下 `refresh?type=bond` **11 批 51.7s（4.7s/批）且快照照常产出 `updated=311`** ⇒ 全类型 ≈700s（含写库与净值首拉 ≈750~900s）；并写明熔断日上界 ~60min，`maxDuration` 盖不住 |
| **CR9-31** | `(items, meta)` 信封 + REST/MCP 两条出口 + 消费侧文案与留痕 | `test_p2_m8` +8、`sync-shrink` +3、`test_p1` 13→14 | 三条改后探针（主源态 1059/`akshare`、熔断态 327/`sina-bond-cov-spot`/`degraded`、`POST /api/sync?type=bond` 的 error 带出上游原话） |
| **CR9-33** | 回调预算按形态分档（1800/2700）+ 回写 `callbackTimeoutS` | `test_c3_readtimeout` 5→14 | 依据是 09-26/09-27 两个实测点；**今日测不了健康态耗时**（东财列表类全天抖动 + 我做过熔断演练），已如实记在账本行里 |
| **CR9-38** | p4 措辞断言 → 三条结构化断言；`jsonOf` 让非 JSON 显式失败 | p4 19→**20** | 单跑 20/20；**我第一版新断言把历史判成"必须四条且每条有正文"，实测形态含 `tool` 行与空 assistant ⇒ 当场 NG 后修正**（CR9-10 同族教训） |
| **CR9-3(b)** | **不改**（定案） | — | 逐调用点扇出实测表见 C-5：热路径 **1**、单股 **2**、转债列表 **4**、板块名称/BK **23/8**（健康态 9/1）、**失败路径 6–8** ⇒ 改计次等于在上游抖动时加倍惩罚，与 C29 动机相反 |

#### 按 PLAN 条目的逐条判定（本批改动射程内）

| 需求（PLAN 原文口径） | 本批是否碰到 | 判定与证据 |
|---|---|---|
| **P1 搜索/打分排序**（含点击率加权） | CR9-31 改了 `/products` 信封 | **不回归**：新增键不改 `products` 数组形态；`test-p1.mjs` 20/20、`test-db` 18/18；同步载荷多出的 `source/note` 不进 `Product` 列 |
| **P2 三类标的 + 自定义区间 + 加密降级说明** | CR9-41 让 crypto 有数据 | **变好并可验**：`/product/crypto/BTC` 200、`/api/quote?type=crypto` 真价（此前该类 0 行、无从验证）；p2 集成 41/41 含 `valueOnly` 断言 |
| **P2 分类浏览按涨幅排序（R14 快照）** | CR9-9 批间隔 ×3.3 | **不回归**：快照仍产出（实测 bond `updated=314/1059`、crypto `250/250`、`failedBatches` 语义不变 = C12）；代价是刷新变慢，已由 CR9-20 把预算对齐 |
| **P3 热点任务 + 板块映射 + SSE** | 未触碰（(a) 已在批次四） | 仍欠 BK 成分等价性实网验收（今日 em 名单接口仍挂），账本未写"已闭环" |
| **P4 工具链含真实行情** | CR9-38 改了 p4 断言 | **不回归**：`test-p4` 20/20，其中"工具执行全部成功（行情源可用）"仍是原语义；只把措辞判定换成事件/结构判定 |
| **P5 意图升档 → 研报落库** | 未触碰（CR9-37 已在前批修） | `test-p5` 21/21（多档形态命中） |
| **P6 MCP 工具 / 技能 / Gateway** | CR9-31 顺带改了 MCP `list_products` | **不回归**：`test-p6` 24/24、`test_p6_mcp` 7/7、`test_d3_guards` 9/9（含挂死看门狗用例，信封改动未破坏降级形态） |
| **G2 每日自动同步** | CR9-33 分预算、CR9-9 影响其尾部耗时 | **口径更诚实**：定时态预算不变、补跑态 2700s；**健康态总耗时今日未复测，已记为待补**（今晚 23:00 那轮会自动留下 `callbackTimeoutS` + 逐类 `tookMs`） |
| **R16 降级可感知/可判定** | CR9-31 主战场 | **加强**：列表类降级从"只能事后翻日志"变为响应自声明，且验收断言按源取数（C23） |
| **R15/M8 多源与限流** | CR9-9/18/3(b) | **不回归**：`p0 15/15`、`p1 14/14`；ds 离线 313 项全绿 |

**门禁终态（09-27 11:2x–11:5x，同一份代码、同一进程）**：`tsc` 0 错｜`vitest` **205/205（31 文件）**｜ds 离线 **16 套件 313 项逐套件 exit=0**｜ds 实网 **p0 15/15、p1 14/14**｜集成 **7 套件全 exit=0 且断言跑满**（db 18、p1 20、p2 41/41、p3 27、p4 20、p6 24、p5 21/21）。



> 做法不是重跑门禁，而是**先把 PLAN 的需求条目（M1–M8 + 「验证方式」P1–P7）与本批 10 个改动文件逐条对齐，再对每条受影响的需求实测判定**。
> 结果：**抓到 1 条我自己带出的回归**（CR9-37 —— "修复自身带出新缺陷"这一类的第 5 次复现，前四次是 CR9-2/6/8/13），另暴露 1 条既有验收的随机性（CR9-38）。

### 本轮实测的门禁与探针清单（供复核）

| 动作 | 结果 |
|---|---|
| `cd web && npx tsc --noEmit` | exit 0，无输出 |
| `cd web && npx vitest run` | **181 passed / 1 failed（31 文件）**，失败项 `lib/gateway.test.ts:83`，重跑单文件同样挂（5.53s > 5s） |
| `PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python tests/<12 个>` | 全绿，合计 198 项；缺 `PYTHONIOENCODING` 时 `test_cr7_research` / `test_p2_m8` **崩在 print** |
| `curl :8000/kline?type=fund&code=110022` | `source=tencent`，37 根，首行 close=146.88（**CR9-1 实证**） |
| `curl :3000/api/quote?type=hk&code=00700` | 436.6 **无 currency**（**CR9-6 实证**） |
| `curl :3000/api/quote/verify?type=stock&code=600519` | `crossChecked:true` + note 称备源不可用（**CR9-11 实证**） |
| `curl ":3000/api/kline?…&start=20260201"` / `start=2026-02-31` | 前者 400（CR7-2/A2-② 生效）；后者 200 且窗口被改（**CR9-12 实证**） |
| `sqlite3`（`dev.db` 副本，`mode=ro`） | `KlineDaily`：`type='fund'` 非场内前缀 639 行均为真净值；`fund/000001` 0 行 → **尚未污染** |
| 集成 `verify-all`（新代码重启后，14:3x–14:5x 串行） | **7 套件全 exit=0**：db 16/16、p1 20/20（用时 55s）、p2 **38/38**（161s）、p3 27/27（47s）、p4 19/19（16s）、p6 24/24（86s）、p5 **17/17（104s）→ 单独复跑 21/21** ⇒ CR9-25；跑后只读核对 `KlineDaily` 无 `type='fund' and close>50` 行、`fund/110022` 128 行皆净值 ⇒ **守卫的实网验收通过，库未污染** |
| 浏览器手测（Qoder Browser Connector，:3000 实点） | ① `/product/stock/600519` 点「双源核对」→ `data-testid=verify-note` 如实显示"主源不可用已降级至 tencent…交叉验证源 akshare 不可用" ✅ CR7-3；但该类为 `text-zinc-500` 灰字、与"双源一致"同色 ⇒ **CR9-11 在 UI 复现**；② 页面现价下方渲染 `来源：tencent · 20260924161444` ⇒ **CR9-7 在 UI 复现**；③ `/chat` 临时把 deadline 改 3s → 出现"回答在 180s 处中断…" ✅ CR7-5（文案硬编码 ⇒ CR9-27），已回退并 `git status` 干净；④ `/product/hk/00700` → **404**（`Product` 无 hk 行）⇒ CR9-26，CR7-4 手测**今日不可执行** |
| 密钥自查 | `.env` 未被跟踪、`git log --all -- .env` 全历史空；两个 `.env.example` 密钥位全空 |

> **建议处置顺序与修复计划见 [FIX-LEDGER.md](FIX-LEDGER.md)「CR9 · 修复计划」。** 其中 CR9-1 建议先于 CR8 批次二（批次二要改的正是同一条取数链）。

### CR9 追加八（09-27 16:0x–16:2x · 主人实点 CR9-13 的现场发现两条新缺陷 → 批次六）

**触发方式与取证纪律**：这次不是我审出来的，是**主人按我给的复现步骤实点**后回报的两个观感问题。我从他的两张截图回代码定位，取证一律用**已存在的产物**（15:38 存下的 `:8000/kline?type=stock&code=600519&interval=1m` 响应），**本批未向任何外部源发请求**——上一段我因反复打东财被主人判为"乱搞现场"，纪律已改（一次东财失败就会打开进程内熔断，会改变他几分钟后的界面所见）。

#### 先结清旧债：CR9-13 验收通过（D10 关闭）

| 主人实点步骤 | 屏幕上的结果 | 判定 |
|---|---|---|
| `/product/fund/110022` 点「1D」 | 出 3M 日线图 ＋ 橙色"分钟线暂不可用，已显示近 3 个月日线" ＋ `数据来源：akshare-fund-nav-hist（该品种仅收盘值序列）` | ✅ 回落与 R16 标注都生效 |
| `/product/stock/600519` 点「1W」再点「1D」 | `数据来源：tencent` ＋ 备注"主源不可用，已降级至 tencent（akshare: eastmoney kline failed on all hosts: RemoteDisconnected）" | ✅ 降级可感知 |

⇒ 同时把"**200 + 0 根**"那条触发器**改判**：东财挂时腾讯给的是 **267 根非空**序列（见下表），不是空；该分支只在"上游 200 且零根"这一形态出现，今日两种形态都不产生它 ⇒ **归离线单测覆盖，不再挂"待观测"**。

#### CR9-42（P2 · UI 表达层）· 分钟线 OHLC 退化被画成散点

**现象（主人原话）**："感觉 1D 好像没有什么数据"。
**取证（15:38 那份响应，未重新请求）**：`source=tencent`、`candles.length=267`、覆盖 09:30–15:30、`volume`/`amount` 267/267 有值、**`open===high===low===close` 的根数 267/267**。
**根因**：`ProductCharts.tsx:322-330` 不分粒度一律 `type:"candlestick"` ⇒ 四值相等的 bar 实体高度为 0，只剩边框，267 根就成了稀疏散点，再被 1230–1251 的 y 轴跨度压扁。**而"四值全相等"这条判据仓库里早就有**——`lib/kline.ts:376` 的日线路径正是用它推 `valueOnly`；**漏的是 1m 透传分支 `:241`**（只看 ds 的 `valueOnly`）。
**修法（比我先提的"≥90%"更严）**：判据提为 `lib/kline-shape.ts:isFlatOhlcSeries()`（`every` 全等）作单一来源，日线/分钟共用；`KlineResult` 新增 `flatOhlc` **自声明字段**（R16：形态由数据自己说，不让前端按粒度猜）；图表在 `valueOnly || flatOhlc` 时画收盘价折线；文案分治——净值型"该品种仅收盘值序列"、降级源"该序列仅有收盘价"（混用就是 CR8-4 那类"一字段载多语义"）。
**为什么不按 interval 硬切**：日线同样会出现全等序列（长期停牌、一字板），按粒度切会漏，按形态切一处覆盖两类。
🔁 **反向验证**：把实现临时换成"≥90% 即退化"⇒ `kline-shape.test.ts` 的成对边界用例（267 根里 1 根带区间 → 必须是合法 K 线）精确失败 `expected true to be false`；复原后 5/5、`vitest` 205→210。**日线路径行为逐字不变**（等价改写），`test-p2` 的三条 `valueOnly` 断言（场内 ETF false／净值 true／BTC true）都在日线、不受影响。

#### CR9-43（P3 · UI 反馈层）· 回落把高亮改成数据档 ⇒"点了 1D 只闪一下"

**现象（主人原话）**："点击图中 1D 之后，页面会闪一下，但是不会实际切到 1D 并展示对应图表。点击其他的 1W、1M 等都没有这个问题"。
**根因**：`applyPreset:182` 先 `setRangeKey("1D")`（所以会闪）→ 请求失败进 `fallbackToDaily3M()`，它固定传 `rangeKey:"3M"` → `:129` 把高亮改成 3M；说明文字又在图下方 `:502`，离按钮太远 ⇒ 读作"没反应"。数据本身没错（3M 日线已出图）。
**修法**：把**用户意图档**与**数据档**分开——新增 `fallbackFrom` 状态，回落时高亮跟随 `fallbackFrom`（用户按的那一档），`rangeKey` 继续记数据档，于是 `addCompare:198` 的对比窗口仍按 3M 取数、不被 UI 反馈污染；并在按钮行右侧加 chip「1D 无分钟数据 · 已显示 3M 日线」（`data-testid="fallback-chip"`；**09-27 17:0x 档位文案改中文后为「当日无分钟数据，已改显示近3月日线」**）。正常加载一律清空。
**主人当场提问：CR8 批次二的"多数据源"方案能不能顺带解决这条？** 判定是**不能**：CR8-1/CR8-3/OPT-2 的改动面全在 `fetch_news`/ingest 契约与新闻卡片上，**不触及行情 provider 链**。可移植的只有 OPT-2 的原则——"按数据丰富度排序、择优、并集"；落到行情层需要 provider 自己声明"给不给分钟 OHLC"，那是**新契约**（`/kline` 加能力字段 + 4 个 provider + BFF，且要重跑实网 p0/p1）。收益是"分钟档永远优先给真有分钟内区间的源"，但**本批的修法已经把观感问题结掉**（折线 + 自声明 + chip），所以建议**不立项、只留档**；主人若要立项，我按 CR9-45 续号。**（09-27 18:5x 编号更正：此处原写"CR9-44"，但 44 已被同日追加九登记的「转债分时注释与注册不一致」占用 ⇒ 前向引用改为 45，不留空号。）**

#### 我自己的两条错（同批纠偏，不留旧说法）

1. **编号空号**：上一条口头把这两条报成"CR9-43/44"，实际仓库里 **`CR9-42` 从未存在**（批次五我起草的那行 Edit 当时失败即作废）⇒ 正确顺延是 **CR9-42 / CR9-43**，已在落码前用三步占位改名（44→TEMP→43→42）机械修正并全仓校验无残留、无空号。
2. **验证现场**：本批全程不向外部源发请求（用存量响应取证），并把"手测前不打上游探针"写进长期规则。

**门禁（16:2x，同一进程）**：`tsc` 0 错｜`vitest` **210/210（32 文件）**｜ds 侧**零改动** ⇒ 离线 313 项与实网 p0/p1 未重跑（理由在此声明，不是漏跑）｜**CR9-42/43 的界面复验欠主人实点**。

**复验与文案后续（17:0x，同一进程）**：

- **CR9-42 复验通过**（Browser Connector 实点 `stock/600519` 点「当日」；**操作者是我，不是主人**）：图下方文案 `数据来源：tencent（该序列仅有收盘价）` ⇒ `flatOhlc=true` 且 `valueOnly=false`，新分支生效；`备注：主源不可用，已降级至 tencent（akshare: eastmoney kline failed on all hosts: …RemoteDisconnected…）`；档位按钮数组只有「当日」`active:true`；截图为 09:30→15:10 一条连续蓝线带面积填充（y 1,230–1,251），不再是散点。**CR9-43 复验通过（17:1x，主人指令"点当日验证 110022 高亮和 chip"⇒ 由我实点，非主人本人）**：`fund/110022` 点「当日」后按钮数组字面回读 `{ 当日: active:true, 近1周/近1月/近3月/近6月/近1年: false }`（**高亮留在用户按的那一档**），chip `[data-testid=fallback-chip]` → `当日无分钟数据，已改显示近3月日线`，图下方 `分钟线暂不可用，已显示近 3 个月日线` ＋ `数据来源：akshare-fund-nav-hist（该品种仅收盘值序列）` ＋ `备注：增量复查窗口内（30 分钟），本次使用缓存`，截图为 06-29→09-21 连续折线带阶段底色 ⇒ **出图且有明确说明**，"点了没反应"的观感消除。
**顺带观测（非本批缺陷、未复现即不立项）**：同一次页面首屏 SSR 的行情卡回 `暂无实时行情（data-service timeout after 15000ms（服务在跑但未及时响应））`——该轮 `:8000` 同时被一个耗时 >60s 的 `interval=1m` 请求占着（东财分钟线跨 host 重试到 45s 超时），与 CR9-33 记的"同步/取数耗时按形态差一个量级"同源，先记现象。
- **档位文案中文化**（主人指令："这个 1D、1M 我看起来很不方便…改成中文"）：`PRESETS.label` → 当日/近1周/近1月/近3月/近6月/近1年，**`key` 仍是 1D/3M 不动**（它是状态比较用的内部标识，渲染层由 `presetLabel()` 翻译）；chip、"当日分钟线不参与阶段划分"、指标卡 `区间最高(3M)`→`(近3月)` 同步改。**锁步改的集成断言**：`test-p2.mjs:334-335` 的 `区间最高(3M)` 与 `>1Y<` 是 UI 字面断言，不改则下次 verify-all 必红。门禁：`tsc` 0 错、`vitest` **210/210（32 文件）**（无一条断言这些字符串，故数字不变）。

---

### CR9 追加九（09-27 18:1x–18:5x · 批次七**立项评估轮**：详情页「当日实时价格」区域 ＋ 上游额度/覆盖实测，**零代码**）

> **本轮性质**：主人从"缺少当日数据就别显示那个标签"出发，演进为"**删掉「当日」档位 ＋ 在 ② 现状区与 ③ 主图区之间新增一个自动轮询的「当日实时价格」区域**"。他明确"评估下方案"＝**一行代码都不动**，且追加两条立场：**不接受单一数据源**（"我不希望只有一个腾讯源，而是多源一起评估"）、**国外品种也要纳入实时**（并反问"这个是只能用东财吗"）。本轮产出＝两轮实测数字 ＋ 三条定案 ＋ 六个待他点头的岔口 ＋ 一条新发现（CR9-44）。

#### 需求演进（原话按时间序）

1. "如果缺少当日数据，就控制当日这个标签不显示，以此类推，避免用户点了还是其他的数据反而造成误解"。
2. （红框指 ②③ 之间）"我想在这个中间新增一个当日实时价格的区域，用于实时显示价格变动情况，**如果当日这个产品有开盘就显示，没有就不显示**。原有的区域则去掉「当日」这个标签"。
3. "每次进页面就展示当前最新状态，并且每隔 N 秒就自动轮询（真"实时"），轮询机制效果参考一般的股价查询网页"＋"用国内源，这样比较稳定"。
4. "国内源帮我评估下哪个最稳定"／"Yahoo、币安、CoinGecko 这三个现在能否访问到"／"光腾讯是不是就能覆盖所有的投资产品类型了？"／"能不能做一个单独的数据请求器，同时请求多个国内网站，汇总数据再展示？"

#### 实测 A：额度与耗时探针（`test-script/realtime_probe.py`，18:14:01 → 18:23:02，独立进程直连上游，**不经 ds、不碰其令牌桶状态**）

```
tencent_quote_stock    ok=12/12 gap=5s  p50=533ms p95= 756ms bytes=  550 {price:'1237.00',   ts:'20260924161444'}
tencent_minute_stock   ok=12/12 gap=5s  p50=458ms p95= 502ms bytes=11024 {day:'20260924', bars:267}
tencent_quote_hk       ok=12/12 gap=5s  p50=465ms p95= 600ms bytes=  432 {price:'436.600',   ts:'2026-09-25 16:08:20'}
tencent_minute_hk      ok=12/12 gap=5s  p50=490ms p95= 644ms bytes=14167 {day:'20260925', bars:332}
sina_quote_stock       ok=12/12 gap=5s  p50=356ms p95=1298ms bytes=  288 {price:'1237.000', day:'2026-09-24'}
tencent_quote_us?      ok= 6/6  gap=10s p50=569ms p95=1485ms bytes=  387 {name:苹果, price:'341.07', ts:'2026-09-25 16:00:01'}
coingecko_simple       ok= 5/6  gap=10s p50=721ms p95= 724ms bytes=   25 {price:85018}  ERR=['HTTP 429'] x1
yahoo_chart_1m         ok= 6/6  gap=10s p50=772ms p95=1002ms bytes=35670 {bars:391, last:'2026-09-25'}
binance_kline_1m       ok= 0/6  gap=10s ERR=['HTTP 451'] x6
eastmoney_quote_ctl    ok= 0/10 gap=6s  ERR=['ConnectionError'] x10
```

**读法与边界（不夸大）**：东财那一行刻意只发 10 次 @6s（＝10 次/分，落在自家 `PROFILES["eastmoney"].rate_per_min=12` 护栏内），**全在传输层失败、连接都没建立 ⇒ 不消耗它的 IP 额度**，不影响当晚 23:00 同步。它 0/10 的判读要划两条界：① 探针只带最小 headers、无 Referer，理论上存在"被 WAF 掐连接"的可能；② 但**同一天 ds 真实链路在 4 个 host 上拿到的是 `RemoteDisconnected`**（见追加八那条降级备注），两条独立观测同向 ⇒ 本轮结论只到"**东财不适合做轮询主力**"，不到"东财挂了"。

#### 实测 B：腾讯的品种覆盖矩阵（18:4x，同法逐类型各发一发）

| 类型 | 现价 | 分时 | 字面证据 |
| --- | --- | --- | --- |
| A股 `sh600519` | ✅ | ✅ 267 根 | `贵州茅台~1237.00` / `day=20260924` |
| 场内基金 `sh510300` | ✅ | ✅ 267 根 | `沪深300ETF华泰柏瑞~4.515` |
| 港股 `hk00700` | ✅ | ✅ 332 根 | `436.600` / `day=20260925` |
| 转债 `sh113050` | ⚠ **空壳** | ❌ 仅 1 根 | 名字有（`南银转债`）但 `今开 0.000`、`成交量 0`、时间戳 `20260924090000`；minute `bars=1` |
| 美股 `usAAPL` | ✅ | ❌ 形态异常 | `苹果~AAPL.OQ~341.07`；minute `day=`（空归属日）`bars=1` |
| 场外基金 `110022` | ❌ | — | `v_pv_none_match="1"`（腾讯库里无此品种） |
| 加密 `btcusd`/`usBTCUSD`/`czcbtcusd` | ❌ | — | 三种符号全 `v_pv_none_match` |

⇒ **腾讯"现价＋分时"完整覆盖只有 3/6（stock、场内基金、hk）**，"光腾讯能不能全覆盖"的答案是**不能**。而场外基金那条 `none_match` 正是 CR9-1 护栏在起作用（`tencent_provider.py:86-89` 用场内判据强制拒绝，防同码不同品种冒领）——**不能为了"单源好看"把它拆掉**。另：`sina_bond_provider.py` 的 docstring 早在 2026-09-13 就实测排除过"腾讯对转债格式兼容但非交易时段恒为面值/零成交"，**今天的 `bars=1 / 今开0.000 / 成交量0` 是同一事实的第二次独立取证**。

#### CR9-44（P3 · 证据/文档层）· 腾讯分时 docstring 声称覆盖转债，但转债链里根本没注册它

> ✅ **2026-10-01 已修（主人指令"CR9-44 先补注释"）**：按下面"该改哪一边"的实测结论**只改注释、不扩注册**——`_minute_kline` docstring 首行删 `bond(转债)` 并补明"bond 链备源是 `sina_bond_provider`／腾讯对转债是空壳形态／东财一熔断转债分时即无源"，模块 docstring 的"不覆盖"行同步。证据与门禁见 [FIX-LEDGER.md](FIX-LEDGER.md) CR9-44 行；本节以下保留当时的发现原文。

**发现**：`tencent_provider.py:262` 的 `_minute_kline` docstring 写着"仅 stock/fund(场内)/**bond(转债)**/hk"，但同文件的注册只有 `register_chain(["stock","fund"], position=1)`（`:333`）与 `register_chain(["hk"], position=1)`（`:337`）——**bond 链里没有 TencentProvider**（`grep -rn 'register' app/providers/*.py` 可复核；bond 链＝akshare 主 + `sina_bond_provider` `:151`）。⇒ 转债分时**永远走不到腾讯**，只能吃东财，而注释会让人以为它有备源。

**该改哪一边（实测定，不按注释定）**：实测 B 给出腾讯转债形态＝`南银转债 / 今开 0.000 / 成交量 0 / minute bars=1`，与 `sina_bond_provider.py:9-13` 那条 2026-09-13 的排除记录（"腾讯 `qt.gtimg.cn` 对转债格式兼容但非交易时段恒为面值/零成交，不可靠；`fqkline`/`kline` 转债 day 恒为空"）**同向**。⇒ **修注释、不扩注册**：把 docstring 的 `bond(转债)` 删掉并注明"转债不覆盖，见 `sina_bond_provider` 的排除记录"。

**为什么值得单独一条**：这类"注释声称的能力比注册的宽"是 CR9-19/CR9-31 同族——**注释会被下游当契约读**。批次七若要给转债做实时区域，按这条注释就会以为有腾讯兜底，实际东财一熔断转债分时即无源（而 `chain_call` 报的是"无备源"，不是"注释里那个备源没注册"）。

#### 三条定案（本轮由实测自动收口，不再复议）

1. **换源，不动东财桶**。`limiter.py:123-133` 的 `PROFILES["eastmoney"]`（`min_interval 5s / burst 2 / rate_per_min 12 / failure_threshold 2 / cooldown 180→900s`）是**全进程共享**额度（详情页轮询＋热点 pipeline＋板块成分＋23:00 同步都在抢，`sync_scheduler.py:178` 的注释正是这件事）。按 60/N 折算：N=5s ⇒ 12 次/分＝**占满整族**；N=10s ⇒ 50%；N=30s ⇒ 17%。为 UI 观感放宽这个桶＝拿主数据链稳定性换一个页面 ⇒ **实时轮询不打东财**。
2. **N 分层：现价 10s、分时曲线 60s**。依据：腾讯 5s 连发零失败（⇒ 10s 有 2 倍余量）；而分时原生粒度就是 1 分钟，**快于 60s 拿不到新点**。硬闸门四条：并发＝1（到点有在途请求就跳过而非排队）、`document.hidden` 即停、**非交易日/收盘不轮询**、连续 2 次失败前端退避 30s→120s→停并显示"最后更新时间"。
3. **"当日有没有数据"的唯一判据＝分时序列归属日期 == 北京今日**。实证：09-27（周日）腾讯仍返回 `day:'20260924'` 的 **267 根完整序列**、新浪给 `day:'2026-09-24'`、hk 给 `ts:'2026-09-25 16:08:20'` ⇒ **"有没有返回蜡烛"完全不能当判据**，且**三家日期形态各异、必须按源归一化**（不能一个正则了事）。这条顺带能收掉 CR9-7（页面上 `来源：tencent · 20260924161444` 那种陈旧时间戳）。

#### 现状盘点：app 里根本没有行情轮询（PLAN 无此表，本轮新事实）

| 页面/区域 | 路径 | 实时 or 读库 | 上游 |
| --- | --- | --- | --- |
| 首页热点卡片流 | `page.tsx:9`→`prisma.hotspotDigest` | **读库**（跑批产物） | pipeline 打东财新闻＋LLM |
| 搜索/浏览 结果集 | `lib/search.ts`/`browse.ts`→`prisma.product` | **读库**（23:00 同步） | — |
| 搜索/浏览 价格列 | `quote-enrich`→ds `/quotes`（`main.py:98`，一次批量） | **实时**，失败**静默回退** `Product.lastPrice` 快照 | 东财批量；bond 备新浪 `cov_spot`；hk 备腾讯 |
| 详情页 ② 现价 | `page.tsx:79` `dsGet("/quote")` | **每次进页面实时一发** | 东财主→腾讯备；场外＝NAV；转债＝新浪快照 |
| 详情页 ③ 日线 | `lib/kline.ts`→`prisma.klineDaily` | **读库**＋尾部增量（30 分钟窗口） | 东财（备：腾讯/新浪） |
| 详情页「当日」分时 | `lib/kline.ts:142` `interval=1m` | 每次点击实时回源、**不落库** | 东财 klt=1→腾讯 minute |
| 详情页 ④ 事件 | `lib/events.ts:105` `/news` | 实时 | 东财新闻 |
| 双源核对按钮 | `/api/quote/verify`→`verify_metric`（`chain.py:45-85`） | **按需**再打一发备源（串行、`max_extra_sources=1`、无缓存） | 链上第二源 |
| /chat 工具 | `lib/tools.ts:282/357/378` | 工具执行时实时 | 按类型分派 |

⇒ 全 app 唯一的轮询器是 `ResearchPanel.tsx:91`（研报进度每 10s；`:110` 那条注释正是它踩过的清理坑）；**行情零轮询** ⇒ "实时区域"是**新增行为**，不是打开某个开关。**顺带发现一条 R16 意义上的"看不见的降级"**：搜索页价格富集失败时静默回退快照、界面不区分（`Product.lastPrice` 注释＝"展示仍以实时富集为准"、`browse.ts:99`＝"失败回退快照值"）——**本轮不登记编号**，待主人点头才立项。

#### 关于"单独的多源汇总器"（他最后一条提案）的架构判定

- **现状里没有这个东西**：`chain_call` 是顺序降级（只有一个源真正出数）；`/quote/verified` 是按需比对器（值仍来自单源，备源只产 `verdicts` 不改值，串行、无缓存无熔断）；真"源"只有那 7 个 provider。⇒ 要新建。
- **红线：不能注册成链上的一个 provider**（"源里有源"）——`chain_call` 会把它当成员再降级一次，且 `chain.py:84` 的 `provider.source == primary_source` 去重判据会失效。正确位置＝**链之上、自带契约的独立端点**。
- **层级推荐改口（我的自我纠正）**：我先一轮推荐放 web BFF（理由是"不想动同步的 provider 链"）；既然定位是"链之上的独立端点"，该理由不成立 ⇒ **放 ds 更好**：点名源是进程内直调（不必给 `/quote` 加 `source=` 再跨网络拼回）、**额度/熔断/缓存状态与主数据链同进程**（批次五 CR9-18 同一课：共享状态必须单点）、积木现成（`utils/timeout.py:run_with_timeout`、`utils/lru.py`、`sina_bond_provider` 的 `CACHE_TTL=60.0` 快照模式、`verify_metric` 的机器可读 `verdicts`）、**能离线单测**（stub 三个 provider 即可测共识/分歧/空壳门，不必靠浏览器实点）。ds 端点是同步 `def`、FastAPI 本就走线程池，聚合内部用 3-worker `ThreadPoolExecutor` ＋每源独立超时即可，**不动 `_chain_call`**。
- **两条硬条件**（不满足就别做）：① 每路独立短超时（建议 3s）＋到点先用已回来的——扇出延迟＝max(各源) 而非 avg，东财真实链路单次可拖到 45s，进聚合即"实时"当场破产；② 聚合不含东财。
- **可信度门**：转债那种"格式对、值是空壳"的载荷必须挡在共识之外（判据：有成交＋归属当日＋非零开）；过不了门的源仍出现在 `sources` 里但不参与取值（R16：不藏）。
- **跨源拼字段（现价取 A、量取 B、分时取 C）＝强烈不建议**：同源内口径都要对齐（`tencent_provider.py:269-271` 专为"东财 f56 是每分钟增量、腾讯是累计"写了 diff 对齐），跨源拼出来的数"看着对、其实错"，且 `chain_call` 会把它标成"已降级但成功"——正是 CR9-1 那类持久污染的形状。

#### 门禁与"本轮没跑什么"的显式声明

**本轮零代码改动** ⇒ 未跑 `tsc`/`vitest`/ds 离线/实网任何一项（**不是漏跑**：改动面只有 `docs/` 三个文件 ＋ 一个 `test-script/` 只读观测脚本，二者都不在门禁的编译与测试路径内）。实测可复现命令：`cd data-service && HTTPS_PROXY=http://127.0.0.1:<代理端口> NO_PROXY="qt.gtimg.cn,ifzq.gtimg.cn,hq.sinajs.cn,push2.eastmoney.com" ./.venv/Scripts/python.exe ../test-script/realtime_probe.py`（**`NO_PROXY` 必须列国内域名**，否则测的是代理不是上游）。

**证据会过期**：以上额度/覆盖数字全部产于 **2026-09-27（周日）**。周日没有成交 ⇒ 只能定"额度/耗时/形态"，**"多少秒看得出在动"与"共识分歧率"必须交易日复测**才能校准 N 与 TTL；东财 0/10 也只代表当日该机状态。

#### 追加十 · 死项清理轮（2026-09-28 00:0x–00:3x）：CR9-45/46/47

> **本轮性质**：主人指令"先跑 1–3（删根 `verify-suites.txt`／删 rules 里 `ALPHA_VANTAGE_API_KEY`／`b2-chain` 并进 `test-p4`），执行一个测试一个"。改动面＝1 个未跟踪产物 + 1 行文档 + 2 个测试脚本，**产品代码零改动**。三条新发现全部是执行途中实测撞出来的。占号依 `FIX-LEDGER.md` #15 的规则「前向引用不构成预留，谁先落地谁占号」⇒ 本轮占 **45/46/47**，批次七那条前置实测债顺延。

##### CR9-45（P2 · 可观测性/架构）· `/health` 与上游健康度不独立：ds 全端点同步 `def` ＋ 看门狗放弃线程无上限

**发现（全部实测，非推断）**：

- `main.py` 里**每一个**端点都是同步 `def`，包括 `/health`（`:75-76`）⇒ FastAPI 一律派到 anyio 线程池（默认 40 worker）。
- `utils/timeout.py:39-98` 的看门狗每次调用起一个 daemon 线程、`join(seconds)` 超时后**无法强杀、只计数**（`:81-83`），≥20 时告警（`:87`）。
- 09-28 00:1x–00:3x 实况：活跃日志 `ds-clean.log` 共 **138 条** `watchdog abandoned threads` 告警，计数 **20 → 峰值 102**，末 10 条字面 `[102, 100, 99, 95, 94, 92, 88, 88, 84, 80]`（在缓慢排空，符合 `:8` 的设计"上游恢复/连接超时后自然结束"）；同期 `curl -m 8 :8000/health` → **`health=000 t=8.011473s`**（多次复探全 000），`/sync/status` → **curl 退出码 28**。web 侧因此报 `data-service timeout after 20000ms（服务在跑但未及时响应）`，`test-p4` 的"工具执行全部成功（行情源可用）"判红。
- 进程活着、端口在听：`netstat -ano` → `127.0.0.1:8000 LISTENING 22136`；`Get-CimInstance Win32_Process` → 22136 起于 `2026/9/27 15:59:20`，另有 3248 同刻启动 —— **实测 `22136.ParentProcessId = 3248`**（`.venv\Scripts\python.exe` 启动器 → 基础解释器 `E:\python\python.exe`），**不是重复实例**。

**为什么算缺陷而不只是"上游挂了"**：`/health` 是**零外部依赖**的端点，却与打上游的端点**共用同一个线程池**；上游一挂起，健康检查跟着失联 ⇒ `docker-compose` 的 healthcheck（C31 那条"两容器 healthy"验收）会把"上游慢"误判成"容器死"。与 CR9-30（错误无法归因）同族：**观测通道与被观测对象不隔离**。

**处置候选（未拍板，本轮零代码）**：① `/health` 改 `async def`（离开线程池，改动一行）；② 给看门狗加"在飞上限"，超限直接快速失败、不再起线程；③ 给 akshare 侧 requests 补 socket 超时（治本，但"akshare 内部无 timeout"正是 `timeout.py:3` 写明的前提）；④ 健康检查与业务分池。**推荐 ①＋②**（①治观测、②治无上限累积）。

##### CR9-46（P3 · 测试脚本自身）· `b2-chain.mjs` 的 180s deadline 贴着实测耗时 ⇒ 正常态也会把自己判红

- 09-28 单跑 `b2-chain.mjs` 字面结果：**4 通过 / 3 失败**，红的是 `流式正文非空 — deltaLen=0`、`正常收尾`、`回答引用真实数据`。
- 同一条消息的诊断探针（deadline 放到 300s、不早退）字面结果：`readerDone=true deltaLen=1945 firstDelta=3.8s`，`done` 事件出现在 **178.0s** ⇒ **产品是好的**；是脚本 180s 上限贴着 178s 真实耗时，而正文 delta 全在末尾，一超时三条一起红。
- 同族：CR9-27（把 180s 写死进文案）、CR7-5（ChatUI 180s 静默截断）。**教训**：deadline 要留余量，且"红"必须能区分"功能坏"与"仪器不够耐心"。
- ✅ **本轮已处置**：3 条不可替代的结构化断言并进 `test-p4.mjs` 新增第 5 段「组合链」（deadline **300s**），原文件 `git rm`；`verify-all.mjs` 的 `PLANNED["test-p4.mjs"]` 按 CR9-25 维护契约 **20→23**。**没搬** b2-chain 的 `get_hotspots || deltaLen > 50` 逃生门——模型凭记忆作答也能过，属 CR9-38 判过的"没有判别力"。复跑字面：`[5]` 三条全 OK、`== 结果：18 通过 / 5 失败 ==`（执行断言 **23 = 新 PLANNED 23**）。

##### CR9-47（P3 · 证据层）· 改 `web/**` 任何文件都会触发 Next dev 重编译，同窗口内的 SSR 断言会读到瞬态 500

- 实况：本轮**基线**跑 `test-p4` 时 [3] `/chat` 四条全 OK；我编辑 `web/scripts/test-p4.mjs` 之后复跑，同一段变成 **`NG HTTP 200 — status=500`** ＋ 三条连带红。`web-dev.log` 对应位置字面为 `⨯ SyntaxError: Unexpected end of JSON input at JSON.parse { page: '/chat' }`、`⨯ Failed to generate static paths for /api/chat/sessions/[id]`，紧跟一串 `✓ Compiled in 2xx ms (1265 modules)`。
- 复探即证伪：`curl /chat` 连续三次 **200**（`0.564806s / 0.068096s / 0.057713s`）⇒ 瞬态，不是回归。
- 与 CR9-24（跑旧进程）、CR9-34（假文件名）、CR9-39（cwd 依赖）同族：**门禁可复现性缺口**。规矩补一句：**跑集成套件期间不得编辑 `web/**`；SSR 页面出现 500 必须先复探 3 次再判定。**

#### 追加十一 · 门禁④补跑轮与四件重估（2026-09-29 23:1x–09-30 00:0x，零代码）

> 执行结果的字面数字在 [PROGRESS.md](PROGRESS.md) 同日续 18 与 [FIX-LEDGER.md](FIX-LEDGER.md) 门槛④；本节只放**论证与定性**，不复述计数。

**① CR9-45 的触发器集合被一轮对照实测收窄。** 09-29 夜整套门禁④（7 套件、23:39–23:44）期间 `watchdog abandoned` = **0** 条 ⇒ 集成门禁**不是**触发器。触发器是同步/补跑/重探针这类**分钟级占满东财桶**的负载，即**每晚 02:00 的 daily sync 本身**。这把本条的性质从"优化项"改成**前置条件**：这个项目的常态就是 ds 过夜跑（02:00 同步＋08:30/16:30 热点），而 09-29 夜的"解法"是不让 ds 过夜——对一台靠夜间同步活着的机器不成立。**修法顺序维持 ①→②**：① `/health` 改 `async def`（两行，把"ds 死了"与"ds 饿死了"变成一次 curl 可区分——三次事故里最贵的成本是归因不是修复）；② 看门狗加在飞上限（上限按 sync 形态取 12＝40 池留 28 给真实请求含 `/health`，到限快速失败走 `chain_call` 降级，合 C3-③ 与 R16）。**③④ 仍否**：③ 的落点只能在第三方内部（明令不翻 `.venv`）或全局 `socket.setdefaulttimeout` 钝器（同时作用到我们自己的同步 requests，与 Windows proactor 的交互不可控、不可单测）——**根因正确 ≠ 落点安全**；④ 独立池对 `/health` 是①的更贵版本、对上游调用则只是换房间出血。

**② 新发现（登记为待拍板 #16，不占 CR 号直到落地）：压补跑与 daily cron 共用同一组 env。** `sync_scheduler.py:190` 的补跑判据与 `:247-251` 的 cron 时刻读的是同一个 `SYNC_HOUR/SYNC_MINUTE` ⇒ "想起一个不触发补跑的健康 ds 做测试"**唯一**办法是把调度时刻撒谎到未来，且**必须记得在撒谎到的时刻前停服务**（09-29 夜靠 23:45 手动 kill 躲过 23:59，是运气加闹钟不是机制）。推荐两行解耦：`SYNC_CATCHUP=off` 只关启动补跑、cron 保持默认 02:00；作为明天白天 ③＋④ 同窗的前置。

**③ `/api/events` 的接缝闭合，且确认无新缺陷（待拍板 #18）。** 三个实测：HTTP 路由（`web/app/api/events/route.ts`）的全仓消费方只有 `test-p2.mjs:274/280/291/297` 四条；能力的第一消费者是 `page.tsx:81` **直调** `fetchEvents(type, code)`（服务端组件 import 库函数，不走 HTTP）；`fetchEvents` 自身**不做主体校验**（`events.ts:92-125` 只判 `type !== "stock"`），但 `page.tsx:63-66` 在调它之前先 `prisma.product.findUnique`、查不到即 `notFound()` ⇒ **页面路径的守卫是"产品行必须存在"的语义白名单**（`..%2Fetc` 在那条路上 404，到不了 ds），路由路径的守卫才是 CR9-10 接的 `checkSubject` 语法白名单。**结论**：同意不重判 CR9-10；两种守卫不同类、互不冗余、**不要统一**——"统一两种守卫"是未来某轮最可能手滑的"清理"，而删路由会同时删掉 CR9-10 接线的唯一端到端证据（09-29 夜 test-p2 41/41 含该四条＝新鲜绿证）。

**④ 对 `:825-826` 那处"既有表格缺陷"的复核定性下调。** 上轮我报"一行只有 2 个竖线、补记溢成 `>` 引用、破坏渲染表格"。逐字复核：825 是**合法的两格行**（与 823 表头同构），826 是紧跟其后的**缩进 `>` 引用块** ⇒ CommonMark 下表格在 825 正常结束、826 渲染为表外独立块——**表格没坏**，坏的是源码观感（缩进让它读起来像 825 行的延续）与补记的归属。修法二选一：补记改成独立表格行，或去缩进作表后正式段落。仍建议修、与 #18 同批 docs 提交、commit message 单列；但理由从"渲染坏了"更正为"归属歧义"。

**⑤ `test-p4` §5 的耗时按双峰记。** 09-28 实测 **178.0s**（据此估窗口）、09-29 夜终跑 **25s**——LLM 延迟主导的双峰，两档都真实。上轮我用 178s 估"④ 约 8 分钟"偏保守一档（实际全程 5.5 分钟）；账本与门槛按两档记，后续排窗口不得只引用一个数。

#### 追加十二 · CR9-45② 落地轮：口径澄清、一次自伤演练、额度纪律（2026-10-01 11:1x–，实网单窗口）

> 实施数字与门禁计数只在 [FIX-LEDGER.md](FIX-LEDGER.md)（门槛①②③⑤、CR9-45 行、CR9-33 行）与 [PROGRESS.md](PROGRESS.md) 同日续 22；本节只放三条**论证与教训**。

**① "在飞上限"这个词有歧义，落地以口径为准。** 追加十一①写的是"看门狗加在飞上限 12"，最自然的读法是"给 `_abandoned` 加上限"——但那个计数器是**已放弃且仍存活**的线程：它们**早已离开 `join`、不再占 anyio worker**，拿它当闸门有两个后果：(a) 挡不住真正的饿死（饿死来自"当前正卡在 `join` 上的调用数"，与它不同步）；(b) 上游永久挂起时该计数永不回落 ⇒ 闸门**永久锁死外部取数**，比原缺陷更糟。所以 ② 数的是**后者**（领名额于进入 `join` 前、归还于 `join` 返回处），这也正是"40 池留 28"那句算术成立的前提。**连带结论：不需要半开/重探机制**——名额随 `join` 归还，而 `join` 至多等 `seconds` 秒，闸门必然自行打开（这条有专门用例，不靠口头推理）。登记原文不改，按本条为准。

**② 一条我自己的仪器错，顺带成了"无上限"的意外演示。** 为按 C34 证明闸门有判别力，我写了个演练：把 `MAX_INFLIGHT_WATCHDOGS` 抬到 `10**6` 再跑新套件。**错在该套件第一行就是 `cap = to.MAX_INFLIGHT_WATCHDOGS`**——我改的不只是闸门，而是**用例自己的并发数** ⇒ 它照着 10⁶ 去起 holder 线程。3 分钟内该进程涨到 **71,148 个 OS 线程**、日志从 `abandoned = 20` 一路刷到 **14,521**、输出文件 **367,034 行**。已 `taskkill //PID 20020 //F` 止血（ds 本体 PID 23292 未受影响，`/health` 仍 200、`abandonedWatchdogs:0`）。三点账：**（a）**演练设计纪律＝**被演练的量绝不能同时是用例的输入**；凡"改一个常数看断言是否变红"，必须让 holder 数与常数解耦，否则测的是自己的脚本。（b）**这条恰好是"无在飞上限"字面代价的现场演示**（原缺陷里线程就是这么涨的，只是由真实上游挂起而非我的脚本触发）——但**不把它当证据用**：触发器不同，它只说明"上限一旦不存在，增长速率由调用方决定"。（c）**C34 的反向验证其实套件内部已经有了**（🔁"12 个在飞回落后同一函数照常执行"＋"被放弃线程结束后计数精确回落"），不需要再拿常数做演练——这条纪律适用于以后所有闸门类改动。

**③ 主人的额度纪律进流程（本轮起生效）。** 本轮开工前的原话是"请求外部数据源不要太频繁，否则会被封号限流，无法验证了"。据此把"实网窗口"的排法从"缺什么补测什么"改成**先列出会出网的命令清单、一窗口每套件只跑一次**：①同步正在占东财桶 ⇒ p0/p1 与 ④ 里会真跑 pipeline 的 `test-p3` 一律排在同步结束之后，且本轮**不重跑 ④ 全套**（自 10:4x 那次全绿以来，web 侧零改动、`pipeline.py` 零改动，只有 `timeout.py`/`/health` 变 ⇒ 依赖面只覆盖 `test-p4`）；②不为"把 exit code 取准"重跑套件（本轮 p0 的字面 `15/15 通过` 来自 tail，管道吃掉了 `$?`，**记为格式欠账而非重跑理由**）；③**饥饿/熔断态不再人为制造**——② 之后 `inflightWatchdogs == cap` 本身就是现场证据，事故当时能读、事后能翻，专门挂 12+ 个无超时上游请求属于花额度买已经能拿到的东西（该改判同步记在待拍板 #17 与 CR9-45 行）。另有一条从"离线"名单里挖出来的**隐性出网口**：`test_p6_mcp.py` 收尾行带 `[网络项]`，会真打一次腾讯 `get_quote`——它跑在②里，所以**门槛② 并非完全不出网**，排额度窗口时必须算上（已写进门槛②）。


---

## CR8 · 界面语义审查（2026-09-24，开放轮次）

> **审查对象**：当前工作树（`dev`，HEAD=`3b07643`）+ **本地实跑**（`web` `npm run dev` :3000、`data-service` venv uvicorn :8000，根 `.env` 注入子进程）。
> **审查方式**：主人实操点击首页热点卡片流提出 6 项观感问题；逐条回代码取行号锚点，并用运行中的服务实测（`GET /api/hotspots?limit=30` 等）。第 7 项由讨论中"可以多源"一句引出，属取数模型候选，不是缺陷。
> **两条纪律**：① 不采信注释与文档的"已实现"，以运行行为为准；② **本轮未运行任何测试/构建，未改任何代码**。
> **去重**：CR8-3 与 CR7-3 同族（"能力已在、消费侧无出口"）但对象不同（CR7-3 是 `/quote/verified` 端点，本条是新闻来源链接）；CR8-1 与 CR7-14（文档漂移）不同层。
> **总判断**：七项中只有 CR8-7 是能力缺失，其余六项都是**能力已经在了、界面对它的表达是错的**——与 2026-09-24 文档漂移审计的结论同构（错在状态/指针层，不在代码事实层）。归并为六个根因：①一字段载多语义（CR8-1/3/7）②批次状态逐行复制（CR8-1）③UI 硬编码归属（CR8-5/6）④控件名不符行为（CR8-2）⑤缺来源/返回链（CR8-3/6）⑥failover 而非 fusion（CR8-7）。
> **实测明细**（今日 9 行 digest 批次分布、cls 批次 `sourceUrls` 为空数组、eastmoney 令牌桶单次 pipeline 三处争抢、24 个 vitest 零 UI 覆盖、env 键位核查、两侧 LLM base_url 推断）见 [history/2026-09-24-cr8-界面语义实证明细.md](history/2026-09-24-cr8-界面语义实证明细.md)。

### 处置总览

| 编号 | 严重度 | 一句话 | 关联需求/约束 | 证据 | 拍板结论 |
|---|---|---|---|---|---|
| **CR8-1** | P2 | 「降级产出」横幅把三件不相干的事 OR 成一条，且批次级 note 被逐行复制到每张卡 | R10 / R12（本轮反转其源序）/ R16 | `pipeline.py:628-629` → `web/lib/hotspots.ts:213-215` → `HotspotFeed.tsx:336-343` **→ 10-01 复测行号已漂：OR 那一行现在 `run_pipeline` 的 `:670-671`** | ⏳ **半落（10-01）**：拆 `reasons[]` ✅、③ 不再进 `degraded`/`note` ✅、逐卡横幅删除＋①② 收页头小字 ✅；**「源序改国内为主」未做**（与 fusion 同属 `OPT-2`），故 ① 目前仍会以页头小字出现一次 |
| **CR8-2** | P3 | 「深度解读」名不副实：只是跳 `related[0]` 详情页锚点，不触发分析、不带热点上下文 | M1/M3 语义；与 CR7-3 同族 | `HotspotFeed.tsx:306-312` + `ResearchPanel.tsx:66-77` | 改名「去分析 <股票名>」，不动接口 |
| **CR8-3** | P2 | 来源链接的标题在**后端最后一步被丢弃**，前端只能渲染 3 个无差别的"原文" | 界面约定「来源可追溯」 | `pipeline.py:553`（`:546-552` 手里有 `n["title"]`）**→ 10-01 复测行号已漂：`_topic_urls` 现在 `:581-600`，丢标题的是 `:595`** | ✅ **已修（10-01）**：`{url,title}` 全链路透传 + 「相关文章」独立成行 + 截断标题 + hover 全文；存量裸字符串行由读侧 `toSourceRefs` 补 `title:""`。状态以 [FIX-LEDGER.md](FIX-LEDGER.md) 看板行为准 |
| **CR8-4** | P3 | 顶部导航随页面滚动，长卡片流下失去一级入口 | 界面约定 | `layout.tsx:19`；实测 `grep -rn "sticky\|fixed\|z-[0-9]" web/app` = 0 命中 | `sticky top-0 z-40` + `#research` 的 `scroll-mt` 补偿 |
| **CR8-5** | P3 | 面包屑把"一级功能"写死，但产品详情页没有固定父级 | **反转**界面约定 `PLAN.md:289` | 4 处调用点：`search/page.tsx:9`、`search/loading.tsx:7`、`product/page.tsx:233`、`product/loading.tsx:9` | 搜索页与详情页面包屑都删；`Breadcrumbs.tsx` 零消费者即删文件 |
| **CR8-6** | P3 | 详情页无页内返回入口；删面包屑后成为唯一回指缺口 | 界面约定 `PLAN.md:287`「搜索现场保留」 | `product/page.tsx:231-239` 只有面包屑，无返回 | 「← 返回」用 `router.back()`，无历史时退化为「首页」链接 |
| **CR8-7** | 候选 | 新闻层多源**合并**（现状是"任一源成功即返回"的 failover） | R15/M8 `PLAN.md:268`；fusion 先例 R13 | `pipeline.py:207-214` + `_EM.acquire` 三处 `:159/:255/:498` | ⏳ **未拍板**，转 `OPT-2`；未查证完不升级为 PLAN 设计 |
| **CR8-8** | P2 | 热点卡片「相关产品」把**已摘牌股票**当推荐（`600200 退市苏吴`、`600086 退市金钰` 混在「创新药／黄金」板块里），且单卡数量无截断 ⇒ 一张卡 4 行、长基金名撑散版面 | 界面约定「相关产品可点」＋ R16（不该把死路包装成推荐） | `web/lib/hotspots.ts:resolveRelated`（成分股环节）＋ `web/app/HotspotFeed.tsx` 卡片装配处 | ✅ **当日发现当日修**（09-30 晚，主人定口径＝只滤退市、ST/北交所保留；前端截 6＋「+N 更多」展开）。详述见下 |
| **CR8-9** | P3 | **导航**把 `/product` 硬编码归给「搜索」（CR8-5 同一根因在导航层的残留）⇒ 首页「去分析」进产品页时顶栏亮"搜索"，被读成"跳到了搜索页"（实测 URL 正确） | CR8-5 的「UI 硬编码归属」；`PLAN.md:311` 的「导航高亮」行 | `web/app/components/Nav.tsx:13`；实测指向产品页的入口有四个、分属三个一级（`search-client.tsx:201`、`HotspotFeed.tsx:67/329`、`ChatUI.tsx:154`＋`research.ts:254`） | ✅ **已修（2026-10-01）＝来路驱动**：删前缀归属，高亮与返回都读入口带来的 `?from=`（`lib/provenance.ts` 单一来源，主人选 (i) sessionStorage 兜底）。**这条同时推翻 09-24 的"按主人要求保留"**——PLAN `:311/:435/:439` 三处明文待改写（F4 未点头，暂未动）。状态以 [FIX-LEDGER.md](FIX-LEDGER.md) CR8-9 行为准 |

### 详述 · P2

#### CR8-1（P2）· 一个布尔承载三种语义，批次状态被逐行复制

- **现象**：卡片底部琥珀色「降级产出：…」横幅，同一次抓取的每张卡显示**完全相同**的一句话。实测今日 9 行 = 2 个批次，4 张卡共享"源+引擎降级"句、5 张卡共享"6 个板块名未匹配"句。
- **根因（三层）**：① `pipeline.py:628` 把 `news["degraded"]`、`struct["engine"]=="keyword"`、`board_notes` 三个**互不相干**的条件 OR 成一个 `degraded`；② `:629` 把所有 note 拼成一条 500 字串；③ `web/lib/hotspots.ts:213-215` 把这条**批次级**字段原样写入每一行，`HotspotFeed.tsx:336-343` 逐卡渲染并截断到 60 字。
- **三类语义被混在一起**：① 新闻源降级（Tavily→国内，本机网络下是常态且产出可用）② 结构化引擎退化为关键词规则（**真实能力损失**）③ 板块名映射未命中（`pipeline.py:455`，几乎每次跑都有，**纯噪声**）。主人截图里那条红框实际只是 ③，而对应卡片本身是 Tavily+LLM 正常产出的。
- **附带**：② 的文案"LLM 未配置或不可用"（`:351-353`）合并了三种成因——未配置 / 调用失败 / **预算耗尽根本没调用**（`:322-328` 在 `remaining<=1` 时直接把 `llm` 置 None）。实测 17:06 批次 `engine=llm` 成功、17:14 批次失败 → 是瞬时网络，不是配置；但文案会引导人去翻 `.env`。
- **复现**：`curl -s "http://localhost:3000/api/hotspots?limit=30"` 后按 `(newsSource, engine, degraded)` 分组计数，并去重打印 `note`。
- **拍板做法**：源序改国内为主（消灭 ①）；`degraded` 拆成分类 `reasons[]`（② 只在页头显示一次小字、③ 不再显示）。**注意 CR8-7 的关系**：合并取数会让"某源缺失"变常态，布尔表达不了——所以 `reasons[]` 是 CR8-7 的地基，先按它做可避免返工。

#### CR8-3（P2）· 来源标题在后端最后一步被丢弃

- **现象**：详情页卡片底部 3 个都叫"原文"的链接，与「深度解读」按钮挤在同一行，无法分辨指向什么。
- **根因**：`pipeline.py:553` `return [n["url"] for _, n in picked if n.get("url")]`——上一行 `:546-552` 的相关性打分全程持有 `n["title"]`，返回时只留 URL。于是 `sourceUrls` 存成纯字符串数组（`web/lib/hotspots.ts:209`），**前端不可能**渲染出标题。
- **硬约束（决定第 3 项能否成立）**：`_cls_telegraph` 写死 `"url": ""`（`pipeline.py:146`）→ 财联社电报条目**根本没有链接**；只有 Tavily（`:100`）与东财快讯（`:178`，读 akshare 的「链接」列）提供 URL。实测今日 cls 批次前 3 行 `sourceUrls` 长度为 0。
- **与 CR8-1 的冲突**：主源若落在财联社电报，「相关文章」永久空白。**国内主源必须选东财快讯**（有链接列），cls 退为第二回退。
- **未查证项**：东财快讯的「链接」列 akshare 实际填不填值——今日 9 行全是 tavily/cls 批次，东财源**一次都没被调用过**，零证据。
- **改动面**：`_topic_urls` 返回对象 → ingest 白名单透传 → 前端渲染。`sourceUrls` 是 JSON 文本列，**不需要 Prisma migration**，但存量行是 `string[]`、新行是 `{url,title}[]`，读侧要在 `safeJson` 层归一。另：UI 截 3 条、DB 存 5 条，口径要统一。

#### CR8-8（P2 · 数据质量/展示层）· 已摘牌股票被当「相关产品」推荐，且单卡数量无截断

- **现象（主人 09-30 晚截图指出"首页完全是乱的"）**：「创新药BD出海持续兑现」一张卡里出现 `退市苏吴 600200`、`ST金花 600080`、`诺思兰德 920047` 等 16 个 chip，占 4 行；长基金名（`广发创新药ETF联接A 012737`）把版面撑散。琥珀色「降级产出：新浪板块名称未匹配…」逐卡重复那是 CR8-1，不在本条。
- **根因分两层，装配链是 `pipeline → web ingest → 前端渲染`**：
  1. **数据侧**：板块成分表（新浪/同花顺）本身含陈旧成员，摘牌股仍挂在概念板块里；`web/lib/hotspots.ts:resolveRelated` 的成分股环节只做"库内是否存在"过滤（保链接可用），**不看上市状态** ⇒ 摘牌股原样进 `relatedCodes`。`Product` 表**没有上市状态字段** ⇒ 唯一可用判据是库内权威名的「退市」前缀。
  2. **展示侧**：`resolveRelated` 末尾 `out.slice(0, 16)`（≤12 只成分股 ＋ 每板块最多 3 只名称匹配基金）是**落库上限**，而 `HotspotFeed` 一个不截全渲染 ⇒ 16 个 chip 直出。
- **归因核实（本条最要紧的一段：主人问"是什么改动导致的"，答案是没有任何改动导致）**。带 WAL 全表 41 个批次实测 `relatedCodes` 内容分布：

  | 日期 | related 总数 | 含 退市/ST/北交所 | 占比 |
  |---|---|---|---|
  | **09-13（基线日 `b22671f`）** | 578 | 60 | 10.4% |
  | 09-14 | 49 | 9 | 18.4% |
  | 09-25 | 82 | 9 | 11.0% |
  | 09-27 | 215 | 30 | 14.0% |
  | **09-30（截图这批）** | 38 | 9 | 23.7% |

  异常样本从 09-13 起就是同一批名字（`创新药|600200|退市苏吴`、`黄金|600086|退市金钰`）⇒ **09-27 的 BK 缓存（`5371494` CR9-3(a)）与 09-17 的 `HotspotFeed` 改动都不是成因**；`related` 峰值 ≥12 的批次有 **30/41**，最早可追到 09-13 00:28。今天之所以"突然"看见：① 屏上这批是我 00:24 跑门禁④ 时 `test-p3` 触发 `POST /api/hotspots/run` 产出的（`2026-09-30 00:27`，`src=tavily`），而当天 08:30 的正式盘前批次没产出（ds 00:29 起停到 19:40）；② 板块主题构成变了（09-26 前 top＝黄金/有色金属/石油；09-27 后＝创新药/锂电池/医药），卡片密度随新闻内容浮动。
- **⚠️ 仪器错（"先疑仪器"同族第六次，记下来防再犯）**：第一遍按既有配方"复制 `web/prisma/dev.db` 只读打开"查库，读到的最新批次停在 **09-29 23:43**，与 API 返回的 00:27 批次矛盾，差点上报"API 返回的批次不在库里"这个**不存在的数据完整性缺陷**。真因：**该库是 WAL 模式**，`dev.db-wal` 18 MB、mtime 09-30 00:29，而主文件 mtime 停在 09-29 23:43 ⇒ 只复制主文件＝读过期快照。**查库必须把 `dev.db` ＋ `dev.db-wal` ＋ `dev.db-shm` 三个文件一起复制到同一目录**。
- **复现/核对命令（会过期）**：`curl -s "http://localhost:3000/api/hotspots?limit=30"` 看每行 `related.length`；DB 侧按上条口径复制三件套后 `SELECT createdAt, relatedCodes FROM HotspotDigest ORDER BY createdAt DESC LIMIT 10`。
- **修法（两处，主人定口径）**：① `resolveRelated` 的成分股环节加 `isDelistedName(库内权威名)` 过滤——**只滤「退市」**，`ST`/`*ST` 与北交所**保留**（可正常交易，滤掉＝替用户判断可投资性）；判据取 `Product.name` 而非成分表回传名（后者不可信，有成对断言钉）。② 前端 `RelatedChips` 默认渲染 **6 个 ＋「+N 更多」展开/收起**——这一刀同时**治存量**：历史批次已落库的 16 个不必重写也会立刻变干净。
- **门禁**：`tsc` 0 错｜`vitest` **215/215（32 文件）**＝210＋5 条成对断言（`hotspots-ingest.test.ts`：退市被滤 ⇔ ST/*ST/北交所四条全保留 ⇔ 以库内名为准 ⇔ 库内查不到仍丢弃 ⇔ 真值表）｜集成 ④ 7 套件全 `exit=0`（09-30 20:34，`runs:0`、`abandoned` 0 条）。**「+N 更多」的交互本身无自动化覆盖**（本仓 vitest 全是 lib/API 测试，零 UI 组件覆盖）⇒ 该半条的验收＝主人浏览器实点。

### 详述 · P3

#### CR8-2（P3）· 「深度解读」名不副实

`HotspotFeed.tsx:306-312` 只是一个 `<Link>`，指向 `related[0]` 的详情页 + `#research` 锚点：不触发任何分析、不携带这条热点的任何上下文。落地页 `ResearchPanel.tsx:66-77` 也只是 `GET /api/research` 读该品种**已有**研报，没有就停在初始态，仍需手动点生成（`:125-153`）。而 `related[0]` 由板块成分返回顺序决定，与热点相关性弱（实测"畜牧业领涨"会跳去解读 600189）。**拍板：只改名，不做真解读**——真做需给 research 接口加上下文参数并决定缓存键（研报按品种缓存），另立需求。

#### CR8-4（P3）· 顶部导航不固定

`app/layout.tsx:19` 的 `<header>` 加 `sticky top-0 z-40`。实测前置条件全部干净：全仓 `web/app` 无 `sticky/fixed/z-*`（无层叠冲突）、header 祖先只有 html/body 且均无 `overflow`（`globals.css` 仅一行 `@import "tailwindcss"`）、四个页面均为文档流滚动（`ChatUI.tsx:399-400` 的 `overflow-y-auto` 是卡片内局部滚动框）。**引入的回归**：CR8-2 的 `#research` 跳转会被固定头部压住 → 同批给 `ResearchPanel.tsx:165` 加 `scroll-mt-*`。阴影：要"滚动才有阴影"需把 header 挪进客户端组件，先用 always-on `shadow-sm`。

#### CR8-5（P3）· 面包屑约定与真实来路不符

`PLAN.md:289` 现明文要求「二级及以下页面显示面包屑，路径为首页 / 一级功能 / 当前项」。但产品详情页**没有固定父级**（一只股票不隶属某个一级功能），于是 `product/page.tsx:233-239` 把中间那级**硬编码成"搜索"**——不管从首页热点还是搜索结果进来都显示"搜索"。叠加 `Nav.tsx:13` 把 `/product` 归到「搜索」高亮，构成两条谎报：主人因此判断"点股票芯片进了搜索"，而实测芯片 href 就是 `/product/{type}/{code}`（`HotspotFeed.tsx:291`），**路由从来没错**。
**拍板**：删搜索页与详情页面包屑（4 处调用点，`page` 与 `loading` **必须成对改**否则导航时闪烁）；`Nav.tsx:13` 的高亮**按主人明确要求保留**（他需要一级归属感），残留的"搜索"高亮是已知且被接受的取舍。（⚠️ **2026-10-01 主人改判**：这条"被接受的取舍"已被 **CR8-9** 推翻——`/product/**` 的高亮改由入口带来的**来路**决定，无来路不点亮；判据与实施只在 [PLAN.md](PLAN.md)「CR8 界面语义批次决策记录」的 CR8-9 行与 [FIX-LEDGER.md](FIX-LEDGER.md) CR8-9 行维护，本节按惯例只留当时的发现与拍板原文。）删完 `Breadcrumbs.tsx` 零消费者 → 删文件。蓝色板块标签跳 `/search?q=<板块>`（`HotspotFeed.tsx:273`）是设计意图，不在本条范围。

#### CR8-6（P3）· 详情页无返回入口

CR8-5 删掉面包屑后，详情页没有任何页内回指入口，故本条由"可选"变为**刚需**。语义上"上一级"不存在，只能实现为"返回来源页"：`router.back()` 是唯一能保住搜索词与列表滚动位置的做法（对齐 `PLAN.md:287`「搜索现场保留」，其现有实现是 `lib/search-cache.ts` + `next.config.ts` 的 `staleTimes`），但**无历史时是空操作**（直接敲 URL / 新标签 / 刷新后）。服务端组件拿不到 `history`，故不能条件渲染 → 做法定为**始终渲染「← 返回」，点击时 `history.length <= 1` 则跳首页**；详情页是服务端组件，需新增一个小的客户端组件。

### 候选 · CR8-7（未拍板，转 OPT-2）

`fetch_news` 现为**任一源成功即 return**（`pipeline.py:207-214`），一批数据只来自单源；`PLAN.md:268`（M8/R15）明文就是这个 failover 语义。改为"多源并集 + 去重 + 择优"可同时解掉 CR8-1 的 ① 与 CR8-3 的链接缺失（cls 供量、东财供链接，`_topic_urls:539-553` 的相关性打分本来就会挑有链接的条目），行情层已有 fusion 先例 R13。**但代价已量化**：`eastmoney` 令牌桶（`app/utils/limiter.py`：最小间隔 5s / 突发 2 / 每分钟 ≤12 / 连续失败 2 次熔断 180s→900s）在**单次 pipeline 内已有三处争抢**——`_em_global_news:159`、`_board_names:255`、`map_board_products:498`（每 topic×board 各一次，最多 10 次 acquire）。而 CR8-1 拍板的源序会让东财新闻从"仅回退时调"变成"**每次必调**"，令牌更紧 → 板块映射拿不到令牌 → 转新浪备源 → **生成更多 CR8-1 要隐藏的 ③ 噪声**。故 CR8-7 不是可选优化，它是把 ③ 从源头减少的那一步；但属数据层改动，不进本轮 UI 批次。

---

## CR7 · 第二轮·全项目（2026-09-20，开放轮次）

> **编号说明**：本轮使用命名空间 `CR7-*`——**前缀数字当初仅为避免与 CR6 的 `CR-01…CR-22` 撞号，不代表轮次**；按本文件规范，它现在恰好对应轮次 CR7。
> **审查对象**：当前工作树（`dev`，HEAD=`4905095`，75 个未提交路径）。
> **审查方式**：全量逐文件通读——data-service 27 个源文件（5.5k 行）+ `web/lib` 29 个非测试文件 + 21 个 `route.ts` + 18 个 tsx + `PLAN.md`（R1–R17 / M1–M8 / C 系列）+ 容器化与迁移。每条发现回代码用 `grep`/`sed` 取行号证据。
> **两条纪律**：① **不采信注释与文档中的"已修复"**，以当前代码实际行为为准；② **本轮未运行任何测试/构建**，故文中引用的"140/140 全绿"等是 CR6 报告记录的**文档值**，非本轮实测。
> **去重**：已显式避开 CR6 的「可优化项」与「需求交付缺口」已登记条目。
> **状态**：⏳ **开放轮次**。发布当时（2026-09-20）14 项全部未修复；**逐项最新状态只在 [FIX-LEDGER.md](FIX-LEDGER.md) 未闭环看板维护**，本文件不复述（本文件只增不改，发现原文永远停在写就的时点）。

### 处置总览

| 编号 | 严重度 | 一句话 | 关联需求/约束 | 证据 |
|---|---|---|---|---|
| **CR7-1** | P1 | 技术分析师 `dataBased` 恒真，无 K 线仍进辩论并参与评级 | M5 话语约束 / R16 / C 系列「半修复」 | `engine.py:133` vs `:154`、`:175`、`:249` |
| **CR7-2** | P1 | 研报回读 `/api/kline` 传 `YYYYMMDD`，被静默回落为默认 90 日，`days` 参数完全失效 | R11 归因同源 / 与 V1 同族 | `adapter.py:30-36,123` vs `kline.ts:90-92` |
| **CR7-3** | P2 | G3/R13 交付成「零调用方端点」，`/quote/verified` 全仓无消费点 | R13 / 批次 D「不留声明了没做的模糊态」 | `grep -rn 'quote/verified' web/` = 0 |
| **CR7-4** | P2 | G6 港股只接通取数侧，消费侧三处断链（工具枚举 / 身份画像 / 币种） | R8 / R12 / M4 | `tools.ts:35,54,73,116`、`profile.ts:58-81`、`grep currency web/` = 0 |
| **CR7-5** | P2 | ChatUI 180s deadline 静默截断，`terminated` 是死守卫 | R17 | `ChatUI.tsx:321-349` |
| **CR7-6** | P2 | 昂贵的 GET 取数端点无 code 校验，可被耗尽东财额度 | R15「用户侧永不空白」 | `CODE_SET` 仅在 `watchlist`/`research/start`；`kline/route.ts:10-13`、`quote/route.ts` |
| **CR7-7** | P2 | 启动补跑冲突：每日同步与热点 pipeline 争抢同一源族令牌桶 | R15 / R10 | `sync_scheduler.py:98-112` + `hotspot/scheduler.py:92-118` + `pipeline.py:159,255,498` |
| **CR7-8** | P2 | 场外基金净值表把「成功但空/列名变更」当有效数据缓存 30min，全量场外基金静默无值 | C11 口径不一致 | `akshare_provider.py:338-369` |
| **CR7-9** | P3 | `/api/sync` 耗时基线写错对象，且 ds 侧 `timeout=1800` 会把已成功的同步记为失败 | CR-07 后续 | `market/refresh/route.ts:7`（"stock 约 2.9 万只"实为 fund=27811，stock=5913）+ `sync_scheduler.py:67` |
| **CR7-10** | P3 | `POST /sync/run` 在请求线程内同步执行 15min+，与热点侧已修的异步口径不一致 | M4 既有修复 | `main.py:259-262` → `sync_scheduler.run_now` |
| **CR7-11** | P3 | 回归盲区恰在本轮反复修复的语义上：`llm.ts`/`tools.ts`/`hotspots.ts` 无单测，`backup_db.py`（C22 破坏性操作）无自动化回归 | R9 / C34 | `web/lib` 23 个 test 文件，缺 `llm`/`tools`/`hotspots`/`browse`/`quote-enrich` |
| **CR7-12** | P3 | `timeout.py` 的 `_abandoned` 计数有窄竞态，观测值单向漂移 | CR-22 可信度 | `timeout.py:66-70` |
| **CR7-13** | P3 | `hk_provider.list_products` 分页无上限；MCP `list_products("hk")` 无超时跑约 4 分钟 | R15 | `hk_provider.py:287`（对照 `akshare_provider.py:785` 有 `min(pages,100)`）+ `mcp_server.py:91-95` |
| **CR7-14** | P3 | 文档/注释漂移 | 文档同步纪律 | 见下「CR7-14 逐项」 |

### 详述 · P1

#### CR7-1（P1）· 技术分析师 `dataBased` 恒为真，破坏「辩论仅采信有真实数据支撑角色」

- **现象**：`engine.py:133` 为 `analysts.append({"role": "技术分析师", "dataBased": True, **r1})`——**硬编码 True**；另两个角色都有真实数据门控：`:154` `bool(r2.get("dataBased")) and fund_available`、`:175` 同理 `news_available`。
- **根因**：A 方案补基本面维度时只给 r2/r3 加了 `*_available` 门控，r1 漏了（`payload["kline"].get("ok")` 从未参与判定）。叠加两层放大：`:189` 用 `dataBased` 筛辩论输入、`:249` 归一化时 `a.get("dataBased", True)` 又对缺失字段**默认 True**。
- **影响**：K 线不可用时 `_compact_kline` 只送"（K 线不可用）"，模型仍可能给出 view → 被当作有数据支撑 → **进入多空辩论并成为 `:224` 评级依据**。直接违反 PLAN「M5 落地定稿·话语约束强化」与 R16（失败/缺口不得渲染成有据结论）。属本项目反复出现的「修复只做了一半」类（C11→CR4-4、CR4-6→CR5-3）。
- **次要问题**：`{..., "dataBased": True, **r1}` 的 spread 在最后，若模型自行返回 `dataBased` 字段会覆盖硬编码值——而该角色 prompt 并未要求输出这个字段，语义随机。
- **建议**：与 r2/r3 对称改为 `bool(r1.get("dataBased", True)) and kline_available`，并把 spread 调整为 `{...r1, dataBased: ...}`。按 C34 做反向验证（临时置 `kline` 不可用 + 断言该角色不出现在辩论输入里）。

#### CR7-2（P1）· `/api/kline` 日期格式契约不匹配 → `days` 参数静默失效

- **现象**：`adapter.py:123` 以 `start=_iso_days_ago(120)`、`end=_today_iso()` 回读 web `/api/kline`，而 `:32`/`:36` 两个函数都 `strftime("%Y%m%d")`（无连字符）。web 侧 `kline.ts:90-92` 的 `normalizeRange` 只接受 `/^\d{4}-\d{2}-\d{2}$/`，**不匹配即回落默认值**（`start=today-90`、`end=today`），既不报错也不写 `note`。
- **影响**：研报的 K 线/阶段维度**永远是 90 日口径**，`collect_kline_with_phases(days=...)` 整个参数是装饰品；「研报与详情页归因同源」这一契约在窗口长度上并不成立（详情页可切 1Y，研报恒 90d）。因两侧都有数据返回，集成测试不会失败——与 **V1 同族**（跨语言日期格式无断言守护）。
- **建议**：① `adapter` 侧改传 ISO 带连字符；② 更根本的是让 `normalizeRange` 区分「参数缺失」（回落）与「格式非法」（返回 `{error}`），否则任何调用方写错格式都是静默降级。补一条断言：研报回读请求的 `start` 必须等于 `days` 推得的日期。

### 详述 · P2

#### CR7-3（P2）· G3/R13 交付成「零调用方的端点」

`main.py:112` 定义 + `chain.py:45` 实现 + `test_g3_crosscheck.py` 8 项，但 **web 全仓 grep `quote/verified` / `verify_metric` / `crossChecked` 命中 0**：无 BFF 路由、无 UI 消费、不在 MCP 工具集、也不是 L1 工具参数。R13 原文要求「差异超阈值时**显式标注来源与偏差**」——"标注"需出现在用户可见路径。批次 D 自订原则：每项**实现**或**显式裁剪**，不留模糊态。

**需主人定调**（三选一）：接详情页现状区（低成本，但每次多一发外部请求）/ 作为 `get_quote` 的可选 `verify` 参数（仅 Agent 路径）/ 把 R13 改写为"验证能力已具备、暂不接入生产链路"并同步 PLAN 与 G3 处置标记。

> **2026-09-20 复核**：`grep -rn 'quote/verified' web/ --include=*.ts --include=*.tsx` **确认零命中**，本条成立。

#### CR7-4（P2）· 港股三处消费侧断链

| 断链点 | 证据 | 后果（4707 只新标的） |
|---|---|---|
| Agent 无法寻址 hk | `tools.ts:35,54,73` 枚举为 `stock/fund/bond/crypto`，`:116` 有 `us` 无 `hk` | 用户问"腾讯控股现在多少钱"时 schema 层不给 hk 选项 |
| 身份区无 hk/us 模板 | `profile.ts:58-81` 仅四个分支，其余落到 `:84` | 详情页「一句话画像」恒为"暂无画像数据（字段缺失）" |
| 币种从未落地 | provider 已返回 `currency`（hk=HKD / us=USD / sina-bond=CNY），但 `grep -rn currency web/app web/lib` **零命中**，`data-service.ts` 的 `Quote` 类型也没有该字段 | 港股在列表与详情页显示成无单位数字（100 实为 100 港币），与 R8/R12 的「标注来源」同级要求缺口 |

#### CR7-5（P2）· ChatUI 180s 上限静默截断（违反 R17）

`ChatUI.tsx:321` `let terminated = false;` **此后从未被赋值**（仅 `:323` 读取）——死守卫，与 CR5-1「负缓存恒假」同类。deadline 到点退出 while 后直接 `reader.cancel()` + `finally`，既不 `setError` 也不提示"回答可能不完整"，界面回到可输入态，用户看到的是一半的 assistant 回答被当作正常结束。R17 要求"长时运行态必须可退出、且如实呈现"。

#### CR7-6（P2）· GET 取数端点无 code 校验 → 可被耗尽外部额度

`CODE_SET = /^[\w.-]{1,20}$/` 目前只用在 `watchlist` 与 `research/start`。`/api/kline`（`route.ts:10-13` 只判非空）与 `/api/quote` 把任意 `code` 直传 data-service → 落到 `_em_get`/`_em_request`，**每次消耗一个 `min_interval=5s`、`rate_per_min=12` 的源族名额**。`checkRequestOrigin` 只挂在 POST 上，而用户浏览任意网页时页面内的 `<img>`/no-cors GET 即可持续消耗该额度，与 R15 的目标（用户侧永不空白）直接冲突。**建议**：GET 侧同口径校验，非法 code 在进令牌桶之前 400。

#### CR7-7（P2）· 启动补跑冲突（同步挤掉热点）

`sync_scheduler._catch_up_if_needed`（`:98-112`，sleep 8s）与 `hotspot/scheduler._catch_up_if_needed`（`:92-118`，sleep 5s）在同进程同时起跑，**共用东财一个令牌桶**。同步侧的分页取数 + 各类型快照批量会长时间占满 `min_interval=5s`，而 pipeline 的 `_EM.acquire(timeout=15)`（`:159`、`:255`、`:498`）拿不到名额即抛 `cooling down`，同时 `HOTSPOT_PIPELINE_TIMEOUT_S=300` 预算被等待吃光 → 当日热点产出为 `degraded`（板块名单/成分映射缺失）。触发条件很日常：**错过 02:00 后白天才启动服务**。建议二者串行（或热点优先、同步延后），或在同步窗口内给 pipeline 预留额度。

#### CR7-8（P2）· 场外基金净值表缓存"成功但空"

`akshare_provider.py:350-358` 只要 `_ak_request` 不抛异常就写 `_fund_nav` + `_fund_nav_ts`；`:362-369` 对 `len(df)==0` 或**定位不到"单位净值"列**时 `return {}`——无 `note`、无失败计数、不进冷却，而那份额外全市场表会在 30 分钟内让**所有场外基金静默失去净值**。与 C11（kline 的"空响应必须进失败窗口"）口径不一致；且该表列名是中文后缀匹配，正是最易被上游改列名打断的位置。**建议**：空表 / 列缺失 → 记 `_fund_nav_fail_ts` 并抛 `ProviderError`（走显式降级）。

### 详述 · P3

- **CR7-9**：`market/refresh/route.ts:7` 注释"stock 约 2.9 万只 → 单类型即数分钟"把量级安错了类型——实测 `Progress.md:195` 为 `fund 27811 / stock 5913 / bond 1052 / crypto 250`。按代码参数（`BATCH=100` + 每批 1 发 EM 令牌 + 5s 间隔）推算 5 类型串行约 15 分钟起、熔断日 40 分钟+；而路由声明 `maxDuration=800`、`sync_scheduler.py:67` 的 `requests.post(timeout=1800)` 会**把已成功的同步记为失败**（`lastDate` 仍置位故不重跑，仅状态失真）。建议实测一次总耗时再定这两个数，不要按注释 tuning。
- **CR7-10**：`main.py:259` `/sync/run` → `run_now` 在请求线程内同步跑完整同步（15min+），占 uvicorn 线程池；热点在 M4 已改成 `request_run`（认领后后台线程 + 立即返回，并修过"线程内二次 single_flight 致 running 永久卡死"）。同类操作两种口径。
- **CR7-11**：回归盲区与修复热点不重叠。`web/lib` 有 23 个 test 文件，但缺 `llm.ts`（C3 尾帧 flush、CR-02 连接/空闲双超时语义、CR4 name 仅首片）、`tools.ts`（`numOrNull` 是 C4 唯一防线、9 个工具的降级分支）、`hotspots.ts`（`(date,title)` 去重 + CR-11 的 P2002 竞态分支）、`browse.ts`/`quote-enrich.ts`。`data-service/scripts/backup_db.py` 的 **C22 三条加固（integrity_check / `-wal -shm` 还原 / 失败回滚）无任何自动化回归**，而它是全项目唯一会破坏性覆盖线上库的脚本。
- **CR7-12**：`timeout.py:66-70`——`t.is_alive()` 判定与 `box["_abandoned"] = True` 赋值之间，若采集线程刚好跑完其 `finally`（此时读不到该标志，故不递减），主线程随后 +1 → 计数**只增不减**，CR-22 的 20 阈值告警会被缓慢推高。仅影响观测，不影响降级功能。
- **CR7-13**：`hk_provider.py:287` 的 `range(2, pages + 1)` 无页数上限（对照 `akshare_provider.py:785` 有 `min(pages, 100)`），若上游把 `total` 返回成异常大值会长时间捶打源族；`mcp_server.py:91` 的 `list_products` 对 hk 会**无超时**地跑约 4 分钟（外部 MCP 客户端视角是卡死）。

#### CR7-14 逐项（文档/注释漂移，不改行为但会误导下一次改动）

1. `PLAN.md:257`「M7 已知优化点 3：进程内缓存无上限」已被 `data-service/app/utils/lru.py` + `Lru(512)/Lru(256)` 落地推翻，条目应删或改记为「已闭环」。→ **已处置**（2026-09-20 整理时改记为已闭环，见 `docs/PLAN.md` M7 节）
2. `providers/__init__.py` 注释称 openbb 为"美股 provider"，但 `us` 是经 `register_chain(position=0)` 注册的，`_QUOTE_REGISTRY` 内并无 `us`——`get_provider("us")` 会 `KeyError` 而 `get_provider_chain("us")` 正常，命名与注册表语义易误读（`_primary()` 依赖 `[0]` 即源于此）。→ **已修（09-26，CR9-8）**：注释按实测改写（`get_provider("hk")`→`akshare-hk`、只有 `us` 抛 KeyError）。
3. 上一轮读码已报、**至今未处理**的两条：`Progress.md` 完全没有 09-19/20 这一轮的记录；`PLAN.md` 工作树副本"删除了 C18–C23 / C26–C34 的完整定义（−145/+31）"。
   → **2026-09-20 复核，该指控为误报**：`git diff --stat HEAD -- PLAN.md` = **+36/−5**，`grep -cE '^\s*[-*]?\s*\**C[0-9]+' PLAN.md` = **34**，C1–C34 定义一条不少。此条**不再作为待办**。误报在 `code-review.md:402`、`code-review-fix-plan.md:217`、`:321` 三处重复出现，整理时一并清除。
   → ⚠️ **本行那条 grep 的证据已过时效（09-26 CR9-23-⑥）**：五文件拆分后 C 正文住在 `docs/CONSTRAINTS.md`（表格式 34 行），对 `docs/PLAN.md` 复跑同一命令返回 **0**。结论不变（一条没丢），**依据换成** `grep -cE '^\| \*\*C[0-9]+' docs/CONSTRAINTS.md` = 34。详见本文件末尾附录的 09-26 补记。
   → `Progress.md` 缺 09-19/20 记录这一条**成立**，已在整理时补齐（见 `docs/PROGRESS.md`）。
4. `.claude/settings.local.json` 与 `.workbuddy/memory/MEMORY.md` 属工具配置/记忆，不入审查范围。

> **建议处置顺序与修复计划见 [FIX-LEDGER.md](FIX-LEDGER.md)「CR7 · 修复计划」。**

---

## CR6 · 第一轮·全项目（2026-09-18~20，文档旧称"第一轮·全项目"）

> **审查对象**：当前工作树（含未提交改动）。
> **审查方式**：全量逐文件通读（web 服务端 lib/route、data-service 全部 py、前端组件、脚本、容器化、迁移），每条发现回到代码核对；另派三路独立复核代理交叉验证。**不采信注释中的"已修复"**——以当前代码实际行为为准。覆盖：web 服务端/前端、data-service、脚本、容器化/配置、迁移与 schema、测试（清单见 history 归档）。
> **结果**：✅ 已全部处置完毕（22 项代码风险 `CR-01..22` + 7 项需求缺口 `G1–G7`），并经双服务全量集成验收；验收中另发现并修复 `V1–V3`。
> ⚠️ **G3/G6 的 ✅ 已被 CR7 修正**：CR7-3 指出 G3 端点**零调用方**、CR7-4 指出 G6 消费侧三处断链。最终状态见 [FIX-LEDGER.md](FIX-LEDGER.md) 看板。

**处置总览表、可优化项结论、V1–V3 修复详述与验收分数已移交 [FIX-LEDGER.md](FIX-LEDGER.md)「CR6 · 执行记录」**（单一来源，此处不重复）；逐条 prose 见 [history/2026-09-18-cr6-批次ABCD执行明细.md](history/2026-09-18-cr6-批次ABCD执行明细.md)。

---

## CR1–CR5 · 更早各轮（压缩结论）

> 这五轮的完整报告不在本文件（它们写在当时的 PLAN.md 里，现按轮次归档）。此处只保留可查的结论摘要与指针。

| 轮次 | 结论摘要 | 详细记录位置 |
|---|---|---|
| **CR1**（09-13 定稿） | 三路并行 + 逐条人工验证。已修复项固化为**强制约束 C1–C17**（不得回退）；同时产生**可优化点 O 系列 12 项**（待决策）。 | 约束见 [CONSTRAINTS.md §A](CONSTRAINTS.md)；O 系列明细见 [history/2026-09-13-cr1-全项目审查与O系列明细.md](history/2026-09-13-cr1-全项目审查与O系列明细.md) |
| **CR2**（09-13，四路并行） | 修复 C1–C17 与 O 系列后的**全量复检**，确认 **12 项真实缺陷（含 1 项 P0 死锁）**，全部已修复（提交 `3bd73a1`）；新增约束 **C18–C23** 与既有约束的修订。 | 约束见 [CONSTRAINTS.md §A 第二批](CONSTRAINTS.md)；日志见 [PROGRESS.md](PROGRESS.md) 09-13 |
| **CR3**（09-14） | 8 项缺陷全修（含 1 项回归 + 1 项不完整修复，提交 `d6ac165`）。该轮当时无文档记载，已于 2026-09-20 整理时从 git 重建。 | 重建记录见 [history/2026-09-14-cr3-第三轮重建.md](history/2026-09-14-cr3-第三轮重建.md) |
| **CR4**（09-15/16，三路并行） | 共 **P1×5 + P2×12 + P3×25** 项，**全部已处理并验证**（提交 `4905095`）。可复用规则固化为 **C26–C33**。**唯一未闭环项**：C31（Dockerfile 进程降权）的镜像构建/运行验证。 | 约束见 [CONSTRAINTS.md §A 第四批](CONSTRAINTS.md)；日志见 [PROGRESS.md](PROGRESS.md) 09-15/09-16 |
| **CR5**（09-17，单路串行） | 共 **P1×2 + P2×1 + 需求缺口×3 + P3×6**。**A+B 批 8 项已实施并验证**（含反向验证 + 全量回归，提交 `4905095`）；可复用规则固化为 **C34**。**暂不处理**：CR5-P4（写接口鉴权，上云前必补）与 CR5-D1/D2/D3（R13 交叉验证 / webhook 推送 / LLM 兜底召回）——PROGRESS/PLAN 需求条目保持原样。 | 约束见 [CONSTRAINTS.md §A 第五批](CONSTRAINTS.md)；需求映射见同节 |

---

## 附录 · 已核验排除的误报（跨轮累计）

> **提新发现前先查这里**——以下各项都被怀疑过并已证伪，不要重复提。

### CR6 轮排除（9 项）

- `browse.ts` 的 `orderBy: { …, nulls: "last" }`：Prisma 6 类型支持 `SortOrderInput`，SQLite ≥3.30 支持 `NULLS LAST`——非问题。
- `sync.ts` 单飞返回同一 in-flight Promise（含 finally 清理）、`_syncTypeInner` 不 reject——正确。
- `market-snapshot.ts` 的 CASE UPDATE 绑定参数顺序与占位符逐个数对齐（2N+2N+1+N）——无错位。
- `kline.ts` 双向失败窗口判断（`lastFailed`/`lastChecked`）当前自洽（唯 CR-05 的头尾共键是新发现）。
- `chat/route.ts` 每轮重新 `trimContext`、工具循环耗尽后追加无 tools 收尾调用、assistant 单次落库——正确。
- `llm.ts` 尾帧 flush、tool_calls 按 index 拼装、name 仅首片赋值——正确（唯 CR-02 的 signal 语义是新发现）。
- `mcp.ts` 运行时挂 `globalThis`、in-flight 去重、exit hook、listTools 失败 kill 子进程——正确。
- `limiter.py`/`timeout.py`/`num.py`/`backup_db.py`——语义与单测一致，正确。
- `lru.ts`、`score.ts`、`search-text.ts`（FTS 引号转义）、`phases.ts`（脏数据过滤）、`time.ts`、`quote-enrich.ts`、`context-budget.ts` 整轮裁剪——未发现可触发缺陷。

### CR7 轮排除（8 项）

| 怀疑点 | 结论 |
|---|---|
| `docker-compose.yml` 用 `service_healthy` 却未定义 healthcheck → data-service 永不启动 | **证伪**：`web/Dockerfile:75` 与 `data-service/Dockerfile:52` 各有 `HEALTHCHECK` |
| 多 uvicorn worker 会让进程内限速器/熔断/`globalThis` 类状态翻倍 | **证伪**：`CMD` 无 `--workers`，单进程 |
| `research-target.ts` 的 `\b(\d{6})\b` 在中文语境失效 | **证伪**：CJK 非 `\w`，边界成立；7 位数字也不会误取 |
| `buildSnapshotUpdate` 的 CASE 批量 UPDATE 参数绑定顺序错位 | **证伪**：与 SQL 出现顺序一致，501 参数 < SQLite 999 上限 |
| `WatchButton` 只能加不能取消 | **证伪**：`toggle` 支持 DELETE 切换（"无自选清单页"属产品级待议，非缺陷） |
| hk 列表无备源会让主数据被降级清空 | **证伪**：C1 空载荷保护 + `sync.ts:154-168` 的 70% 缩水保护双重兜住 |
| `sync.ts` 缩水保护在首次同步（`existingCount=0`）时误拦 | **证伪**：守卫带 `existingCount > 0` 前置 |
| `mcp_server.py` 在 import 期读 `WEB_API_BASE` 早于 `load_env()` | **证伪**：`:24` 先导入 `hotspot.scheduler` → `pipeline.py:31` 已执行 `load_env()` |

### 整理期新增排除（2026-09-20）

| 怀疑点 | 结论 |
|---|---|
| `PLAN.md` 工作树副本"删除了 C18–C23 / C26–C34 完整定义（−145/+31）"（CR7-14-③ / D4-①） | **证伪**：`git diff --stat HEAD -- PLAN.md` = **+36/−5**；`grep -cE '^\s*[-*]?\s*\**C[0-9]+' PLAN.md` = **34**。C1–C34 定义一条不少。原指控在 `code-review.md:402`、`code-review-fix-plan.md:217`、`:321` 三处重复，均已按此结论清除。 |
| **上行补记（2026-09-26 CR9 复验；不改原判，只补证据时效）** | 上面那条 `grep -cE … PLAN.md = 34` 是在**五文件拆分之前**的 `PLAN.md` 上测的；今天对 `docs/PLAN.md` 重跑同一命令返回 **0**（C1–C34 正文已迁 `docs/CONSTRAINTS.md`，表格式恰 34 行，`PLAN.md:8` 已明文指针）。**结论仍成立（约束一条没丢）**，但任何人按这条证据复跑会得出相反判断 → 已在 [FIX-LEDGER.md](FIX-LEDGER.md) CR9-23-⑥ 登记为文档层待修项。 |

### CR9 轮排除与撤回（2026-09-26）

> 本轮实测后证伪或撤回的怀疑点，**不要再提**。

| 怀疑点 | 结论 |
|---|---|
| 真实密钥/凭据被提交进仓库 | **证伪**：`.env` 未被跟踪（`git ls-files` 只有两个 `.env.example`）、`git log --all -- .env web/.env` 全历史为空、两个模板密钥位全空、`git grep` 密钥形态仅命中 `package-lock.json` 里 `task-list-item` 的假阳性 |
| 「CR8 批次一代码已写但未提交，工作树有 ~242 行未提交改动」 | **撤回（本审计自身的一次误判）**：`git status --porcelain` 为空、`layout.tsx:19` 无 `sticky`、`web/app/components/PageBack.tsx` 不存在、HEAD `02f0e95` 是纯文档提交——**FIX-LEDGER 的"代码一行未动"记载是对的**。成因：并行审计代理称"改动存在但未入库"，而我未以 `git status` 复核就采信并按"已提交"口径去核对。**纪律回补：subagent 关于版本状态的结论必须由 `git status` / `git show HEAD:<file>` 复核后才可入报告** |
| 「`.claude/rules/project.md` 的文档路由表缺 `CODE-REVIEW.md` 一行」 | **证伪**：`:100` 就在表内（同一审计代理的误报，已复核原文） |
| 「`backup_db.py` 损坏源会残留空壳产物，且 D1 的清理路径不可达」 | **证伪**：`sqlite3.connect()` 不落盘，`src.backup()` 抛错时不创建文件；紧随其后的 `len(dbs)==1` 是真断言，实测 19/19 通过。该文件中真正的问题是 `:64` 的恒真断言（已记 CR9-15），不是清理路径 |
| 「集成产物 `web/verify-suites.txt` 未入库，违反 `.gitignore` 约定」 | **证伪**：该文件未被跟踪、无代码读取（写出点是 `verify-all.mjs:83`），属"一次性产物用完即无"，无需处置。**09-28 补记（本行原有两处过期，已改）**：① 写入行号是 `:83` 不是 `:26`；② "当前不存在"不实——实测同时存在**两份**：`web/verify-suites.txt`（生产者产物，4601 B）与**仓库根一份孤儿**（1626 B、7 套件全 `exit=1`、断言 `0/N`；不是本生产者所写，因为 `verify-all.mjs:14` 的 `WEB_DIR` 就是 `web/`）。根那份已按主人指令删除；`.gitignore:33` 对任意层级同名文件都生效 ⇒ 删除零 git 影响。**留它的风险是实的**：本附录「我复述出来的数字」那行记的两次误读，读的正是这类陈旧产物。 |
| 「fund K 线在 09-25 之前的实跑里已被腾讯串号数据污染」 | **证伪（目前是潜在缺陷而非既存污染）**：`dev.db` 只读核对——`type='fund'` 的 639 条非场内前缀行全为 4 位小数真净值，`fund/110022` 128 行 close=2.781/2.82/2.828，`fund/000001` 0 行。触发条件已具备（CR9-1 实测可达），但库还干净 |
| 「hk 分页上限改成截断而非抛错 → 静默缩水主数据」 | **证伪**：与 CR6 排除表同族——C1 空载荷保护 + `sync.ts` 的 70% 缩水保护双兜住；`hk_provider.py:289-291` 的截断有 `log.warning`。**09-27 追加七给这条判定补一个前提**：70% 保护要求 `existingCount > 0`（`sync.ts:160`）⇒ **首次到货那一轮没有基线可比**，真要兜住得让列表 provider 把上游声明的 `total` 带出来（CR9-31 的信封正是现成位置）。今日无实例（hk 列表没到货），故仍按原判定不入缺陷台账，只在 FIX-LEDGER 的 CR9-26 行记为**已知盲区** |
| 「`kline-range.test.ts` 有一条复现不出却恒绿的用例（CR9-32）」 | **撤回（09-27，错在测量仪器）**：文件里的实参是**斜杠分隔**的日期（字节 `2f`），断言绿得正确。回显给我的文本（`Read` / `od -c` / `JSON.stringify` / 我自己重打的探针字符串）会把日期形态的斜杠**渲染成连字符**，于是"同参探针"其实是**另一个入参**。⇒ **纪律**：凡"字面量形态本身是被告"（正则拒绝、日期格式、隐形字符、"看着一样却行为不同"），只能采信**码点/十六进制**，不采信任何渲染文本，也不采信我重打的副本 |
| 「我复述出来的输出数字，就是真实发生过的事」 | **证伪（09-27 追加七，两次踩中，错在我自己）**：同一会话里我先把 `verify-suites.txt` 的片段"读"成**全量同步 488s、hk 落库 477 行**，又把第一次 5.5s 对照"读"成 **0/20 非主源**——**前者库里 hk 仍是 0 行**（`product.groupBy` 复核：只有 crypto 从 0→250，`total=35177`），**后者实际是 20/20 全走备源**（东财仍在上一轮留下的 180s 冷却里）。两次都是我在**复述**输出而不是**引用**输出，而且都差点写进账本当"实测值"。**纪律**：凡进入结论/账本的数字，必须能指到一次字面输出行；写"实测值 X"之前把那次输出重新读一遍；读不到就写"未测"。（与 CR9-32 渲染层谎报、CR9-40 合成入参同一族——**先疑仪器，再疑代码**） |
| 「对照实验只要跑了就有判别力」 | **证伪（09-27 追加七）**：CR9-9 的第一次 5.5s 对照组跑在**上一轮把东财打进熔断之后的 180s 冷却里**，20 批全被 0.01s 即拒 ⇒ 表面上"间隔没用"，实际测的是我自己的冷却残影。重跑（服务重启、桶清零）后才拿到真值：**@1.5s 非主源 7/20、单批 2.69s** vs **@5.5s 非主源 0/20、单批 0.58s** ⇒ **结论方向恰好相反**。**规则：改限速/熔断相关参数时，对照组必须先把进程内状态清零**（重启服务，或实测确认冷却已过期），否则测的是仪器的残影；`on_failure` 类计数不会自己清零，重启是唯一可靠手段 |
| 「`test-p2.mjs:335` 断言了 HTML 字面 `>当日<`，撤「当日」档位需锁步改它」 | **证伪（09-27 19:5x，第三次踩同一族错，错在我自己）**：该行字面是 `html.includes(">近1年<")`，与「当日」无关；`grep -rn "当日\|>1D<\|fallback" web/scripts/*.mjs` 的命中全在 `test-p5` 的"当日有无研报"语义上。⇒ 批次七 (f) 的真实结论是**零锁步改动**（撤档位不破任何测试），而不是我 19:4x 报告里写的"有一处必须同批改"。**同一纪律第三次失效说明：把"我记得的断言"写进结论前，必须重跑一次 grep 并把字面行贴出来——纪律不在记忆里，在输出里。**（与 CR9-32 渲染层、CR9-40 合成入参、附录"我复述出来的数字"同一族） |
| 「给既有调用链加校验，只要测到'非法被拒'就算修好」 | **证伪（本轮由 CR9-37 实证）**：闸门初版整体回写归一化结果，把缺省 `type` 填成 `"stock"` ⇒ 研报工具按代码形态判 A股/美股的规则失效；又把 `code` 限定为 `typeof === "string"` ⇒ LLM 常见的 `{"code": 600519}`（number）从"可用"变"被拒"。⇒ **纪律**：加校验必须**同时**断言"合法形态集合没有被缩小"（数字 code、缺省可选字段、空白两侧），否则回归会藏在需求验收面而不是崩溃面 |
| 「`/tmp` 里那份 ds 日志就是运行中那个进程的」 | **证伪（09-28 00:2x，错在我自己，"先疑仪器"同族第四次）**：我按 `/tmp/ds-run.log`（mtime **09-27 10:58**）判"ds 挂了很久"，而运行中的 ds 实测起于 **`2026/9/27 15:59:20`**（`Get-CimInstance Win32_Process`），真正的活跃日志是 `ds-clean.log`（mtime 与当时同分钟）。`/tmp` 下 `ds*.log`/`dslive*.log` 共 **48 份**，其中 `ds-run*.log` 就有 **5 份**。⇒ **纪律**：引用长驻进程日志前先对号——**进程启动时刻必须 ≤ 日志 mtime**，否则读的是上一次实验的尸体；同一族还有"复述而非引用数字""合成入参当上游结论""渲染文本当文件字节"。 |

#### 追加十三 · 10-02 夜两刀（#22(b)＋#25 甲／#23）与一次全量测试：四条仪器与设计教训

> 本轮把待字五项一次落掉（#22(b) 展示半／#23／#25 甲／A5 作废／#20 残句），代码面产出 **CR9-49／CR9-50** 两行；五道门禁终态只读 [FIX-LEDGER.md](FIX-LEDGER.md)「验证门槛」。以下只收**门禁够不到、而对下一步有指导意义**的四件事。

**① 五道门禁全绿时，一个新写的纯函数仍能把真实数据藏起来（本轮唯一一处我自己造的缺陷，当场修）**：`staleNotes()` 初版在判据层 `slice(0, 2)`（照 CR8-1「一批最多两次」的设计语言抄来的上限）。离线 16 条断言全绿——其中一条就是"五类同日陈旧 ⇒ 只报前两类、按 tab 顺序"，**把缺陷钉成了契约**（C34 提醒过的形态）。打第一次真 API 才看见：`type=all` 实际有 **stock／bond／crypto 三类**同日陈旧，屏上只显示两条 ⇒ 被藏掉的那一类正是这句话要防的"看不见的降级"（R16）。**修法**：判据不截断，渲染层截断并交出 `staleMore`（`browse.ts` 一处、`search-client.tsx` 一处）＋ 断言改成"五类全报"。**教训（可复用的判据）**：**上限／截断／去重这类"少显示"的规则属于渲染层，且必须自带"被收起多少"**；写在这类规则里的数字如果只出现在被截断的那一侧，任何离线断言都无从发现它丢了东西。

**② "重启 ds ⇒ ③ 能取到主源态"这条今晨刚定的口径，本轮被证伪一半（必要不充分）**：本轮 20:0x 在**全新 PID 29352**、`10048` 计数 0、且**该进程从启动到 ③ 的第一个 `/quote` 之间只收过两次 `GET /health`**（`ds-gate1002c.log` 的请求序列可查 ⇒ 进程内没有我们自己攒下的任何冷却）的条件下跑 ③，`p1` 仍 `bond 备源态`、`p0` 仍 `kline 备源契约`。⇒ 进程内冷却清空只排除**我们自己**的桶，不排除东财当晚真的不通（16:03 的 stock `all hosts RemoteDisconnected` 是同一件事的白天空照）。**改判**：不再把"主源态"当窗口排程的目标，**由回执里那行 `[PASS] …主源态／备源态` 字面事后决定拿到了哪一档**，两档都是 CR9-31／CR9-36 的合法形态。这同时把"必须分 A/B 窗"这个说法彻底废掉（今晨已改一次，本轮改到底）。

**③ 新仪器：改 FastAPI 端点签名后，`GET /openapi.json` 就是门槛 ⑤ 的零成本探针**。本轮给 `/sync/run` 加了 `force` 布尔参数。按 CR9-24 我必须证明"新代码在跑着的那个进程里"，而传统做法要么真触发一轮同步（30–40 分钟＋额度）要么读代码（不构成"进程里生效"）。FastAPI 的参数集由**活进程的函数签名**反射生成 ⇒ 字面 `[('trigger','string'), ('force','boolean')]` 一条 curl 就够。**同族可用形态**：任何新增查询参数／响应字段，都可以拿 `openapi.json` 或响应键集当"新代码确实活着"的证据，而不必先制造一次昂贵的真实调用。

**④ 用一次最小真写入补上一整条"集成层刻意不测"的债（额度换判别力的示范）**：#23(viii) 原话是"集成层不加断言——要证明第二次没出网，必须先跑一次真同步（30 分钟＋额度），代价大于收益"。本轮发现**逐类**闸门让代价小了两个数量级：`POST /api/market/refresh?type=bond`（11 个东财批次、68.8s、`updated=315`）之后同参数复打 ⇒ 字面 `tookMs=2`、`skipped:true`、`snapshotAt` 回填**旧**时刻 ⇒ "同一天重复触发不再烧额度"自此有活体证据，而欠的只是一个小类型的额度。**教训**：遇到"这条只能靠昂贵实验证明"时，先问**有没有一个最小的同类对象**能把代价降到分钟级——这里逐类粒度（#23 的落地形态之一）正是让最小实验成立的前提。

**⑤ 两处账本自纠（不动代码，属"会误导下一步动作"那类）**：**(a)** FIX-LEDGER #20 行里残留的"①③ 仍待字"与同一行开头的"✅ ①③ 已落地"自相矛盾（10-02 落地时漏删）⇒ 删除并注明删因，避免下一次读账本的人去找一个已经不存在的待办。**(b)** 09-24「22 项文档漂移清单」按主人的字**作废**，但**编号与那条"清单实体不在仓库内"的说明保留不删行**（第 9/13/14/15 条那类按号引用的先例：删行会同时造出空号与断引用）。

#### 追加十四 · 10-03 00:0x–00:5x（刀 4 结清／刀 C／OPT-3 ①）：五条只有"人踩过"才写得下的教训

> 本轮零门禁意义上的新功能，产出是一条被实测推翻的**定案**、一次配置开关打穿测试层、以及一轮"重启服务"的权限博弈。五道门禁数字只在 [FIX-LEDGER.md](FIX-LEDGER.md)「验证门槛」。

**① 拍板"分源方案"时，我没有读过那条链路的符号映射函数——一个定案因此被证伪**：批次七 (e)「美股分维＝现价腾讯、分时 Yahoo」是 09-27 夜六个岔口之一，写进了 PLAN／账本／我的 memory，两年来没人验过"腾讯能不能给美股"。本轮做 OPT-3 前置实测 ① 才读 `tencent_provider._symbol()`（`:48-56`）——**它的 docstring 自己写着「仅用于 A股/场内基金」**，四个分支全要求数字开头，`AAPL` 落到 `return None` ⇒ `_symbol_for` 返回 None ⇒ `get_quote` 抛 `ProviderNotSupported`（`:152`）；美股实际只有 `openbb_provider.py:71 source = "yfinance"` 一家。**教训（写死成步骤）**：**凡是"用 A 源当 B 源的第二源"这类方案，拍板前必须读到那张"代码→符号"的映射函数本身**，因为域名的可达性与品种的覆盖面是两件不同的事，而后者只在映射函数里。这是"把'我记得的实现'写进结论"那族错的又一次实例（CR9-32／CR9-40／"我复述出来的数字"同族）——差别只在于这次错的不是我写的代码，是**我据此建议、他据此拍板的一条设计**。**可复用的自检问句**：这条结论里有没有一个数字或名字，是我没有在本次工具输出里见过的？

**② 开一个配置开关＝改契约；测试脚本也是这个端点的消费者**：`INGEST_TOKEN` 从空到有值，web 侧两个 ingest 端点由 fail-open 变 401，**生产链路一条都没坏**（ds 两条写回调早就带 `if INGEST_TOKEN:`），但**门禁 ④ 会被静默打穿两条**——`test-p2.mjs:438` 无头请求断言 400（现在拿到 401，而且更坏的是它从此**测不到**它声称在测的标的核验那一层），`test-p3.mjs:140` 只在 `process.env` 有值时带头、而 `verify-all.mjs` 实测**不读任何 env**。**教训**：**守卫类配置上线时，grep 的对象要包括 `web/scripts/`**（门禁也是消费者）；而修法上"**让请求带上口令**"优于"**把断言放宽成 401 也算过**"——后者是让门禁去适配缺陷形态（与"修契约前先查旧断言是否把缺陷锁成契约"互为镜像：这次是别让新开关把契约掏空）。

**③ 我把"改 env 必须重启两侧"说满了**：Next dev **会自己重载 `web/.env`**——监听 PID 14496 未变时，无头 POST 已从 400 变 **401**（23:24 实测）。真正必须重启的只有 ds（`config.py` 在进程启动时把文件灌进 `os.environ`，且 `pipeline.py:53` 是模块级求值）。**后果不是文字不准，而是动作多余**：我原本要杀掉了不起的 `next dev`，实测之后省掉了这一步，也就省掉了一次他手测现场被打断的风险。**纪律**：**涉及"改配置要不要重启"时，先做一次只读探针再决定动谁的进程**；把"必须重启两侧"当预告写出来，是一次未测先说。

**④ "重启服务／碰 .env"是这台机最难放行的一类操作，绕不过去也不该绕**：本轮四次被分类器拦下（含一次**纯只读**的 `curl /health` ＋ PID 查询，因"本轮目标是重启"被连带拦）。字面理由每次都指向同一条：进程终止属破坏性操作、`.env` 属凭据面。**我做对的**：不重试、不换个写法蒙、把每次拦截的**字面理由**原样引给他、把要执行的命令摊开让他自己跑、并用一次结构化提问把"这一夜怎么收这个口"摆成三选一。**最后是他一句「你给我重启整个项目」才解锁**。另记两条同类凭据纪律：他的 token 值**从不进账本／探针输出／memory**（只记 `configured:true` 与长度），值可猜这件事**只说一次并给更换路径**，然后照他的选择执行——判断可投资性归他，判断口令强度也归他。

**⑤ Browser 代点的三条仪器事实（＋一条表述纪律）**：**(a)** `evaluate_script` 有 **15 秒上限**，一个脚本里连打 5 次详情页 SSR 必超时（每次 SSR 含一次实时富集）⇒ 改成 `navigate_page(timeout:90000)` ＋ 一次读活 DOM；**(b)** 导航后的**第一次** `evaluate_script` 常返回空数组（客户端 fetch 还没落地，本轮 `staleNotes: []` 就是这个形态）⇒ **要重读一次**才算"屏上没有"；**(c)** 本 app 的列表行是**无 href 的 button**（`router.push`），选择器写 `a[href^="/product/"]` 会一条都找不到；**(d)** **代点 ≠ 本人点击**，而且**"我没拿到证据"要说之前先把自己上一次的输出读完**——本轮我把 CR8-8 的展开记成"无取证"，可那次返回里明写着 `74 → 79` 与按钮变「收起」，**是我没读**（01:5x 复点确认 6→9→6、增量＝标签声明的 3，该条已闭环）。真正还欠的只有 CR8-9 的诚实态：`window.open` 被弹窗拦截、改试"清 sessionStorage"被权限层按越界改状态拦下（**理由成立，该形态的定义就是"新标签页"**）⇒ 只能主人按一次 `Ctrl+T`。**教训**：写"无取证"之前先 `grep` 自己的工具输出；把已经拿到的证据写成欠账，和把欠账写成已做，是同一种账本失真。

**⑥ 一条共享兜底函数把两个市场的价格接在一起，而它是被我"顺手写的新用例"当场抓出来的**：给腾讯加 us 现价时，我最初写的是"先走 `_symbol_for`，走不通再补 us 映射"。看着无害，但 `_symbol_for` 对未知类型**一律落到 `_symbol(code)` 兜底**，而 `_symbol("1234")` 因为 `12` 前缀返回 **`sz1234`** ⇒ 一条数字形态的"美股"代码会去请求**深市**符号，并且我的 `f[2]` 一致性守卫还会判它匹配（`1234 == 1234`）⇒ 别市场的价格可以被当美股交付。**这就是 CR9-1（场外基金同码串成沪市品种）的同一个形状换了品种**，而它已在生产里躺着，只因 `Product us` 恰好没有数字码才没爆过。**教训**：加"新类型的映射"时不要假设兜底分支会返回 None——**兜底分支的返回值本身就是行为**；把"非法输入 ⇒ 零次请求"写成断言（而不是只在脑子里判断）是唯一能抓住它的东西，这次它是我自己新增用例里唯一红的一条。

**⑦ 活体探针又抓了我一次：后缀规则按"第一个点"切是错的**：`/quote?type=us&code=BRK.B` 返回 `tencent us symbol mismatch: 请求 BRK.B 返回 BRK.B.N`。腾讯美股的 `f[2]` 形态是 `<ticker>.<交易所>`，而 share class 的 ticker 本身就含点（`BRK.B.N`、`BF.A.N`）⇒ **交易所后缀是末段，不是第一个点**。守卫生效（fail-closed，没交错数据），但覆盖面错了：所有带点的美股代码永远拿不到备源。**教训（与 ⑥ 同族）**：**只用 mock 验"守卫类"逻辑是不够的**——mock 是我按自己脑子里的形态造的（我测过 `_us_quote_symbol("brk.b")`，却没测 `BRK.B` 走完整匹配路径）；一条真上游请求就能抓到，而它正好是门槛 ⑤ 存在的理由。

**⑧ 门禁工具的假绿形态有三种，第三种本轮才现形**：CR9-25 收的是"条件分支跳过 ⇒ 全绿≠全跑"，CR9-39 收的是"cwd 依赖 ⇒ 静默全 0"，本轮是第三种：**缺口被打印出来了，但没编码进退出码**——`test-p4.mjs exit=1 断言 0/23` ＋ harness 自己打了 `!!! 断言缺口（全绿不等于全跑）`，收尾仍是 `ALL DONE ＋ verify_all_exit=0`。而门槛④ 历次记录都以"`verify_all_exit=0`"为凭 ⇒ 只要没人逐行读 `exit=`，一次彻底的 0 断言就能混过去。**这次是我逐行读了才发现，不是工具告诉我的。** 推荐修法＝`gaps>0 || failedSuites>0 ⇒ process.exit(1)`（登记为待拍板 **#28**，等主人字——动门禁工具不属我自行扩权范围）。另记 p4 本身：**单跑 23/23、`exit=0`** ⇒ 序列里那次是紧邻 p3（真 pipeline＋SSE＋dev 编译同窗）的瞬态，按 CR9-47"见红先复探"处理，**没有**为了凑一次"七套同序列全绿"把 p3 再烧一遍额度。

**⑨ 自写的一致性扫描器自己是第三种假绿的来源——"0 处不一致"必须带分母**：commit 前跑竖线一致性检查，第一遍报 `0 处不一致`，我差点当成通过；实际那段脚本在循环体里把 `i` 误赋值成函数（`i=j=>j; i+=1` ⇒ `NaN`）⇒ 循环条件立即为假，**只扫到了第 1 张表**。重写后打印"扫过 3 个文件 / **40 张表**／不一致 0 处"才是可判定的读数。**口径：任何自写检查器都要同时输出"扫过多少对象"**，只有"0 不一致"而没有分母，等价于没跑（与 CR9-25「全绿≠全跑」、#28「缺口被打印但没编码」同族，这次的差别是**分母是我自己造的**）。

**⑩ 内存态观测位的"事后可读"有一个硬上限＝进程还活着；断电这一档要靠落盘，不是靠更详细的日志**：本轮 `lastRefresh.outcome`／`tookMsTotal`／`dbBackup` 全随 02:07 的断电消失，只能从 `ds-restart3.log` 的字面行序**重建**（`daily sync partially failed` 之后紧跟 60 批 `/quotes?type=stock` ⇒ 链式刷新确实触发了）。这与 #21「能做状态位就别只做日志」不矛盾，是它缺的下半句：**要跨进程死亡读的判据，得同时落一份磁盘状态**（本轮登记为 **#29**，推荐只做"备份 job 状态写 `backups/state.json`"这一件，不新增出网、不改调度）。顺带一条判据纪律：**别为"把昨晚补回来"手动 `POST /api/sync`**——那是整轮额度，而当日闸门会把它变成半轮混合态，取证价值低于今晚干净的 02:00 那轮。

#### 追加十五 · 10-03 09:3x–10:3x（#29／#27 第一步／#28 落地轮）

**① 加"观测位"必然要打穿某条旧的"目录必须为空"式断言——正确动作是收紧判据，不是放宽断言**：`state.json` 落进 `backups/` 之后，`test_backup_db.py` 原有那条 `失败轮 ⇒ os.listdir(out) == []` 当场红。它想钉的是**"没有半成品快照"**，写成"目录全空"只是当时的巧合形态。⇒ 改成按 `SNAPSHOT_NAME` 过滤 ＋ 另配一条**正面**断言（失败轮同样要有 state），判别力反而更强。**通则**：新增同目录产物时，先问"旧断言断的是集合还是命名模式"，别一上来给旧断言加 `or`。

**② 观测族必须自带"我从不拦"的证据，否则"纯观测"只是注释里的承诺**：`akshare-obs` 刻意不调 `acquire()`，而这类"这一步没改行为"的说法最容易被后人（或我自己）在第二步里顺手改掉。⇒ 钉三条成对：连记 200 次后 `granted/denied` 仍 0 且 `in_cooldown()` 恒 False、观测族与 `eastmoney` **不是同一实例**、`eastmoney` 六个参数逐项未变。**通则**：凡是"这次只加可见性、不改行为"的改动，断言面里必须有一条**行为不变**的反证，而不只是新功能在变。

**③ 数错了自己的行号：登记缺陷时要区分"我读过的"和"我推断的"**：#27 原记"`akshare_provider:348/513/744` 三处不占东财桶"，本轮 grep 才看清是**五处**（漏 `:602`、`:923`），而且 `:923` 是 sina、`:744` 的域名归属我根本没核过——把一个未核的事实写进账本，等于给后人发了一个错误的"已核实"标记。⇒ 更正已写回 FIX-LEDGER（CR9-54 行＋#27 行），并把"域名归谁"这件事交给观测计数自证。**通则**：行号级证据要么标"已读码确认"要么标"未核"，不许用统一口吻写在一起。

**④ 门禁工具的红要能自己响出来：负向探针是一类新的自证**：`verify-all.mjs` 改完之后，我用"服务全停"这个本来是不利条件的状态做了**反向取证**＝六套 `exit=1 断言 0/…` 时 `verify_all_exit=1`（改之前是 0）。**通则**：改"报错/计数"这类工具时，先想清楚有没有一个**必然失败**的场景可以免费拿到——不利场景有时正好是唯一便宜的负向对照。

#### 追加十六 · 10-03 15:2x–15:5x（#25 乙 立项并落地轮＝CR9-56）

**① "少 342 只"是一个形容词，不是一个风险**：#25 乙 立项前我对差集的全部认知就是"新浪 5571 vs 东财 5913 ⇒ 少 342"，据此把"覆盖面缩水"当成主要风险，还准备为此讨论缩表阈值。真去归因之后结论**反了**：那 343 只**全是已摘牌/退市类代码**（`PT金田A`/`国华退`/`大通退`；含「退市」61 只＝库里含「退市」的一共也就 61 只），新浪独有的反而只有 1 只（`920202`，北交所）。⇒ 同一个数字既可以是"退步"也可以是"改善"，**差别只在有没有看过"是哪一批"**。**通则**：凡是拿条数差做立项依据的，先花一次窗口把差集**按名字/代码段拆开**，再谈风险与阈值；拆完常常发现要防的东西换了（本刀真正要防的变成了名字列，见 ③）。

**② 新的"看起来绿"形态：降级代码躺在没人读的分支上**。列表链路根本没有 `register_chain` 那条链（`_CHAIN_REGISTRY` 只被 `chain_call` 用于 quote/kline），若按我上一轮写的形状实现，切换分支永远进不去，而**没有任何一条门禁会因为"备源从未被走到"而红**——上游正常时它本来就该不被走到。**通则**：新增降级路径时，"这条分支被走到过"必须有证据＝离线用 stub 让主源必失败并断到备源的 `source` 字面（🔁 另配一条"主源成功时备源调用次数为 0"，防反过来多烧上游），生产用 `/products` 响应里那句 `source`；两样都没有就别说"备源已就绪"。

**③ 上游短名字段的代价要分族，不能只报一个总条数**：两份全量同码不同名 101 行（1.81%）。若只写这一个数，读的人会觉得"1.81% 可以接受"；拆开才知道**族与族完全不同性质**＝44 行是新浪整批丢 `-U`/`-W`/`-UW` 后缀（真退化）、10 行只是全角名里空格数不同（无害）、5 行的 `ST` 标记一边有一边无（其中 1 行是 21 天的**日期差**不是源差）、其余是状态前缀归属不同。⚠️ 而且**东财和新浪都会在打 XD/DR 前缀时把名字截到 5 字符**（`XD万华化` ⇔ `万华化学`）⇒ `strip_status_prefix` 能去掉前缀、**补不回被截掉的字**，这条要明写在 docstring 里，否则后人会把"名字质量问题"当成已经被它解决了。**通则**：给主人看的风险数字必须到"族"这一级；一个总数会诱导出一个错误的接受/拒绝决定。

**④ 探针设错 env，测到的是自己的机器**：第一次拉东财报 `ProxyError`（Windows 注册表系统代理不可达），我第一反应是给探针手设 `NO_PROXY` —— 被权限层按"绕过既定配置边界"拦下，**拦得对**：`app/main.py:12-13` 本来就 `setdefault("NO_PROXY","*")`，正解是让 app 自己加载自己的配置（探针第一行 `import app.main`）。改完后错误变成 `RemoteDisconnected`＝**同一个"失败"在两处 env 下指的是两件相反的事**：前者是"我这台机的代理不通"（处置＝修 env），后者才是"上游不可用"（处置＝补备源，本刀的立项依据）。**通则**：出网探针失败先问"请求实际走了哪条路"，把 `NO_PROXY`/`HTTPS_PROXY` 的最终值随回执一起落盘；**要复现服务的出网形态就导入服务入口，不要替它设变量**（同族另案：CR9-41 的 crypto 0 行）。另记一次仪器错：同一个 akshare 版本里 `stock_zh_a_spot` 是**中文列名**且 `代码` 值带 `sh/sz/bj` 前缀，而 `bond_zh_hs_cov_spot` 是英文列名——按包名推列名 ⇒ 5571 行拿到手却一个 code 都没存下，白烧 70 页。**第一次调用某个上游封装，先把 `df.columns` 落盘再写解析。**

#### 追加十七 · 10-03 22:0x–23:2x（F5 上屏／F6 探测限时／F1 美股探针／F4 排期，四件同轮）

**① 「怕说谎所以沉默」是一个正确的保守判断被当成了唯一的解**：#25 甲 落地时那条 `snapshotAt` 为 null ⇒ 不报快照说明，理由写得没问题（"从未刷过"与"刚换完列表、刷新腿还没跑到"同形，报"未更新"＝谎称陈旧）。但 10-03 22:20 读库撞出来的形态是：`bond` **1059 行／有价 0**、`fund` **28015 行／有价 0**，两类 `updatedAt`＝今天 02:00、`snapshotAt`＝NULL，**这个"一整列空价格＋一句话都没有"已经挂了约 20 小时**。修它的动作**不是推翻那条判断**（"不许谎称陈旧"这半原样保留，措辞里也不许出现"未更新"），而是补第三种成因 `pending` ⇒ **以后碰到"因为怕说错而不说"，先问"有没有一种说法是不说谎也能说的"，再问"要不要说"**。取证命令（会老化）：`SELECT type,COUNT(*),SUM(lastPrice IS NOT NULL),MAX(updatedAt),MAX(snapshotAt) FROM Product GROUP BY type`。

**② 代理指标必须先拿反例验一次，否则会把假话上线**：我原本打算用 `MAX(snapshotAt) IS NULL` 代表"这一类没有价格"。同一次查询里 `crypto` 是 **250 行有价／`snapshotAt` 仍为 NULL**（那批行 09-27 由当时的列表阶段直接把价写进 `lastPrice`，而 `snapshotAt` 这列是刀 1 之后才加的，此后 crypto 没再被整表替换）⇒ 只看那一列会让虚拟币那一屏明明满是价格、屏上却说"价格还没跟上"。**形态：写"用 A 列代表 B 语义"的判断前，先在库里找"A 为空而 B 存在"的行**；这类行通常真实存在，只是没人查过。

**③ 给观测加时限，要同时问"这个时限会不会变成一次判定"**：M7 优化点 2 最省事的写法是"探测超时 ⇒ 标 degraded"，那样实现出来是**把一个慢但可用的 server 踢进 `RETRY_COOLDOWN_MS`（60s）冷却**，比面板多等几秒糟得多。落地按另一条线做：`Promise.race` 只限制**调用方等多久**，不取消连接、不改 `state`（仍 `idle`），只在 `reason` 写明"未据此判降级"。🔁 回退探针＝把 race 换回无条件 `await` ⇒ 那条用例**在 5000ms 处超时红**，而两条对照用例（及时应答⇒connected、connect=false⇒零次 fetch）照绿：**原来的 20s 阻塞不是缺陷的根源，"把等待当结论"才是**。

**④ 改一条被测试钉住的旧断言时，回退要能只红在"该改的那几条"上**：CR9-57 的两轮回退各自精确——R1 摘掉 `pending` 分支 ⇒ **3 条红**（报 pending／since＝名单换过那天／三种成因混在一晚），其余 16 条一字未动；R2 把判据退回只看 `snapshotAt` ⇒ **恰好 1 条红**（crypto 那条反证）。这两次红的集合不同，正说明"新增的成因"和"补的代理指标防线"是两件独立的事，不是一团一起亮的灯。

**⑤ 探针要有界：别用整表拉取去回答"有多少"**：`ak.stock_us_spot()` **没有"只取一页"的参数**，直接调用它＝**913 次请求**。我从它的实现里读出它打的接口，自己只发 7 次就拿到立项需要的四条结论——`count`＝**18,241**、`num` 被服务端**硬截到 20**（100／500 都只回 20 行）、`market` 参数**不生效**（传 NASDAQ 仍返回 NASDAQ＋NYSE 且 `count` 一字未变）、尾部混着 `TILC`(ETF)／`PRB`(LP)／`ZZZTX`（`name`==`symbol`、price 500、`category` null）。**"num 会被截"这件事，只有"换个 num 再打一次"的探针能看见，能跑通的探针永远看不见。**

**⑥ "两个源＝两次请求"在降级链上是错的估算**：`/api/quote/verify` 一次 BFF 请求今天实际打了 **3 次上游**——东财主源失败 → 腾讯成功 → 交叉验证时**又把失败的那个主源重打一次**。字面回执：`source=tencent`、`crossChecked=true`、`verifyVerdict=no_second_source`、note 里两句 `RemoteDisconnected` 并存。⇒ 以后凡按"源数"估额度，都要乘上**链层重打失败源**这一项。同一条也解释了为什么"不跟 02:00 那轮抢桶"的判据要写成**不与 02:00–02:45 那条链重叠**，而不是"今晚之前不跑"——后者会把 20:00 的窗口也误禁掉。
