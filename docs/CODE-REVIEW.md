# 代码审查发现记录（CODE-REVIEW）

> **职责**：记录**各轮审查发现了什么**。本文件只增不改——已发布的发现不因后续修复而删除或改写，
> 状态变化记在 [FIX-LEDGER.md](FIX-LEDGER.md)。
> 需求与设计见 [PLAN.md](PLAN.md)，约束见 [CONSTRAINTS.md](CONSTRAINTS.md)。
>
> **提新发现前先查**文末「附录 · 已核验排除的误报（跨轮累计）」，避免重复提已证伪项。

> **速览**：这里只记"各轮审查**发现了什么**"，修没修、怎么修、按什么顺序修都看 [FIX-LEDGER.md](FIX-LEDGER.md)。**当前轮次是 CR9**（2026-09-26 全项目审查，编号**已排到 CR9-47**（09-27 批次七排到 44；**09-28 死项清理轮占 45/46/47**，批次七那条前置实测债按占号规则顺延；前向引用不构成预留）；**合计/已修/余项的权威计数只在 FIX-LEDGER 速览一行维护，本行不复述**——09-26 的 CR9-23 教训：同一数字抄两处必然失同步，本行此前就落后了两批）；CR8 开放（6 项已拍板待实施，实测确认代码一行未动；**09-30 晚主人实跑首页时另发现 CR8-8 并当日修毕——但"首页乱"经 41 批次实测判定为非回归，无改动导致，详见该条归因段**）；**CR7 代码闭环 14+1、验收 1 项受阻转 CR9-26**。已闭环轮次（CR1–CR6）只留压缩结论+指针。编号黑话（CRn / CR-xx / G / V）先查下方「轮次对照表」。

> **⚠️ 10-11 18:1x 追加更正（原句不动、立对照）**：上面那句「编号已排到 CR9-47」是 09-27 时点——实际最后一枚被取走的是 CR9-86（`cdb46c8`，出处＝FIX-LEDGER 第 60 项末）⇒ 下一可用＝**CR9-87**；本行不再充当取号权威，权威住在 FIX-LEDGER 状态卡「下一可用编号」那一格。

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

> **【已搬归档】** 追加十 · 死项清理轮（2026-09-28 00:0x–00:3x）：CR9-45/46/47 —— 正文见 [2026-10-11-code-review-追加节归档.md](history/2026-10-11-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
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

> **【已搬归档】** 追加二十三 · 10-05 00:4x–15:5x（屏幕上那句是他画的线；缩水闸挡死了一个已批的方案） —— 正文见 [2026-10-11-code-review-追加节归档.md](history/2026-10-11-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加二十九 · 10-06 18:2x（#41 登记：我把"等一周计数"当成了可执行的前提，而那个数住在内存里） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十 · 10-06 19:0x–19:31（CR9-68 四枚实钻＋CR9-69 落地：同一把尺第一次量到我自己当天新写的那把刀） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十一 · 10-06 20:3x–20:5x（CR9-70 丙＝读数面的"最近 N 日汇总"：把上一轮换来的两条尺提前用在自己刀上） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十二 · 10-07 00:2x–00:5x（CR9-71＝#43 乙：样本采集这一刀，第一枚红的钻是它自己的排序） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十三 · 10-07 01:2x–01:4x（CR9-72＝#44：一条被我自己捆错的窗口归属，加上四枚钻的"红法不同"） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十四 · 10-07 08:2x–09:0x（六件拍板执行轮：阈值第一次真校准、代理这条前提从没被检验、"代点能不能取证"要按谓词判） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十五 · 10-07 13:1x–13:4x（两刀落地轮：能力要声明不能／判据不吃包装／不可见字符不许进源码） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十六 · 10-07 14:0x–14:1x（三问一轮：第三本账读到／"开一个入口"的代价怎么算） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十七 · 10-07 15:3x–15:5x（重启自证＋代做点击：一轮里三次问"我的手段能证到哪一层"） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十八 · 10-07 16:0x–17:0x（#49 落地一轮：三条"我的证据其实来自别处"） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加三十九 · 10-07 18:5x–19:1x（两条拍板落成排程：一轮里两次"我的证据来自读回，不是来自我发出"） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十 · 10-07 19:4x–19:5x（「剩余的也按计划推进」＝窗口开成之前，先把任务书里会误导人的字面改掉） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十一 · 10-08 09:4x–10:2x（机器重启吃掉两枚自动化⇒刀 5 ①③④ 人工跑：一处"客户端 bug 也按发数计价"的实测，和一处必须写成负结果的读数） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十二 · 10-08 21:1x–21:5x（docs 矫正批的执行轮：六条都落在"我的工具"与"我的归类"上，其中三条是同一形制第二次以上） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十二·附 · docs 行号锚点复扫（10-08 21:3x，主人 21:0x 的字＝「Q3 走甲→丙」） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十三 · 10-08 21:5x–22:0x（主人手测 CR8-9 报回两件事＋④ 最贵档实跑：一枚我自己的探针参数错、两条真发现、一格 #51 的读数） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十四 · 10-08 22:5x–23:1x（#55 甲 落地＝CR9-78 ＋ #56「先乙后甲」评估 ＋ ④③ 两格排程评估） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十五 · 10-08 23:2x–10-09 00:1x（#56 甲＝CR9-79 ＋ #54 乙＝CR9-80 ＋ #52 乙 升格 ＋ 两枚探针 ＋ 四枚自动化） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十六 · 10-09 11:4x–12:3x（#55 乙 落码＝CR9-81 ＋ #53 丙 落笔 ＋ #52 到场补跑取证 ＋ 两侧服务按字新起） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十七 · 10-09 13:1x–13:4x（#56 第二轮手测修复＝CR9-82 ＋ #52 甲 定档 ＋ us 备源 note 定为不改 ＋ 178 只 us 码新浪覆盖率补测） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十八 · 10-09 15:0x–15:3x（#56 收口三个字 ＋ F 那一格的时区诊断 ＋ 代点被水合挡住 ＋ 零生产码改动的一轮） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加四十九 · 10-09 17:2x–17:4x（#57 甲+乙／#58 甲＋语义标注／#59 他否掉甲改成「这一类」的处置 ＝ CR9-83／84／85） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十 · 10-09 21:2x–22:2x（他给字的那一发＋一串错误体把孤例升成日常态＋「从屏上读 note」根本不成立＋他提的那把 500 行尺量错了文件） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十一 · 10-09 23:3x–23:5x（他一句「我选丁＋乙」→ 一张表多带一个字段＋一枚会自己红的顺序判据） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十二 · 10-09 23:4x–23:5x（他把两处决定写在同一条消息里，我只答了一处＋规则本体的落笔形状） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十三 · 10-09 23:5x–10-10 00:0x（首搬那一节的字节流比对／新建闸的第一版基本都是尺错／我抄来的那句假读数） —— 正文见 [2026-10-12-code-review-追加节归档.md](history/2026-10-12-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十四 · 10-10 09:4x–09:5x（主人否掉首搬并要求恢复／我造的动作件没按规则里那句「节」的定义写） —— 正文见 [2026-10-15-code-review-追加节归档.md](history/2026-10-15-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十五 · 10-11 19:2x–19:5x（④ 的失败名被包装层吞掉／CR9-87） —— 正文见 [2026-10-15-code-review-追加节归档.md](history/2026-10-15-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十六 · 10-12 17:5x–19:1x（全项目重读／OPT-3 三条前提被自家注册面推翻／10-13 窗口准备件 P1–P5＝`ec7f235`） —— 正文见 [2026-10-15-code-review-追加节归档.md](history/2026-10-15-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十七 · 10-12 20:0x–21:2x（E-3 刀 A＋刀 C＝CR9-89／闸1·闸2 落地＝CR9-90／闸1 首跑被自家 ANSI 解析假红） —— 正文见 [2026-10-15-code-review-追加节归档.md](history/2026-10-15-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十八 · 10-12 23:2x–23:5x（主人四项拍板落地／闸2 现场腿补上保险丝与分母口径／两处账上数字更正） —— 正文见 [2026-10-15-code-review-追加节归档.md](history/2026-10-15-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加五十九 · 10-13 00:1x–00:3x（旧账逐条清：5 条结清／两条前提被实测证伪／#66 带着原料登记） —— 正文见 [2026-10-15-code-review-追加节归档.md](history/2026-10-15-code-review-追加节归档.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加六十 · 10-13 09:3x–09:5x（OPT-3 第一批 1a 落地＝CR9-92：三条红线各做成一枚断言／定案 (e) 的 us 分时被现查证伪／闸2 L3 那把尺此前看不见"已改未提交"） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加六十二 · 10-13 19:0x–19:2x（B 窗 B2＝④ 七件套全绿⇒④ 现值换档／重启踩到"启动补跑会重买一整轮全量同步"那枚坑，代价 47 发／diverged 那一支实机验不成的原因是两道闸） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加六十五 · 10-14 14:1x–18:2x（批次①＝docs 对账轮：五处"账对不上现值"逐条改掉；主人的字＝「先 push 19 笔」→「重启之后再看看还有哪些没做完」→「启动 web 和 ds…按优先级排序」→「这些都是在目前计划内，但是还没有做的吗？」→「先做批次1」） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加六十六 · 10-14 18:3x–18:4x（批次② 前置轮：这一批的真前置不是"等到 02:00"而是"web 那一棵得活着"；上一轮那枚存疑读数零成本闭掉，并新登记 #69） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加六十八 · 10-15 00:3x–01:5x（起服务轮：两侧复起＋装载态复读成立；新登记 #72＝`sync-state.json` 落点与 docstring 不符且落进未 gitignore 的仓库根 `runtime/`；docs 治理 15 项已闭环条目搬 history） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十 · 10-15 09:5x–10:0x（批次②读数轮：三枚落痕取齐——marker ✓／Q2-1 随机器重启丢失（durable 兜底）／Product ✓；链式刷新腿被机器入睡中断在 fund；重启装载新码） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十一 · 10-15 10:0x–11:3x（W2 上午场＋"现在批"：③ 主源档读数／B1 六跑与 `29.push2` 两枚新事实／CR9-96 首读／#65 屏验 ✓／#31 残差结案 ✓／闸1 全绿；同轮搬 7 枚追加节） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十二 · 10-15 13:0x–14:2x（盘中三件续做：B1 第七跑仍不通⇒本会话判不可达／bond 整条实时腿失败（归因更正）／实时条数据路径复核；机器 12:51 二次重启＋两侧复起；闸1 全绿） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十三 · 10-15 18:2x（当日项目状况总结；盘后刷新腿被机器反复休眠打断在 fund、ds 挂死；给后续窗口的理由与重建路径） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十四 · 10-15 19:0x–20:2x（「启动ds和web」→「跑一下全量刷新」→「先启动web和ds，然后继续执行没做完的任务」：机器两次入睡带走两侧、ds 重建两棵＋第一次起错的解释器钉住＝venv（#73 已按甲落）＋刷新腿第三次重发收官 626s＋别家 18:3x 稿逐条复核） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十五 · 10-15 22:3x–22:5x（「执行剩余两项，注意保持机器激活」＝过夜防睡持有者（第一枚脚本自己写错判据、起手即释放）＋ ⑤ p0/p1 双绿 15/15·14/14，但这两枚结构上答不了 ③ 那一格） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十六 · 10-16 00:0x–00:2x（处理方案重做轮：上一版"24 枚分 5 桶"错在三类混装＋我自己两处读错；三句批字＝A 立刻全落／D1 ≤16 发全批／D2 排 D1 之后） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十七 · 10-16 09:2x–10:2x（到场轮：昨夜机器睡了带走三条腿，重排后 D1 的 2 发由我打；bond 主源格成立、us 连续两天落备源⇒归因换到 yfinance 侧；新登记 #76） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十八 · 10-16 15:05–15:14（D2＝④ 集成七件套到场跑完：七套全 `exit=0` 且断言缺口 0；本场出网全对得上进程内零基线；定性＝降级档⇒不填主源格） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加七十九 · 10-16 15:3x–16:0x（「搬」＋「写」两批落地：CODE-REVIEW 余量 490→3,829；#76 甲／#78 甲 落码；顺带纠一枚死字面） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加八十 · 10-16 16:4x（「跑」＝CR9-3 的 BK 成分等价性结案：两路打到同一枚端点、成分整集相等；顺带读到两条新形） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加八十一 · 10-16 16:1x–16:2x（全量体检＝盘点题：回归面 0 红，问题全在"节奏与说话"这一侧） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
> **【已搬归档】** 追加八十二 · 10-16 16:3x（三句批字：push／#22(b) 定档乙／防睡已起；＋本节起 CODE-REVIEW 写不下一节了） —— 正文见 [2026-10-17-code-review-追加节归档-1017.md](history/2026-10-17-code-review-追加节归档-1017.md)（体量治理：整块搬迁，原地只留指针）。
#### 追加八十三 · 10-17 16:1x–17:0x（**docs 体量治理三刀＝「搬」字动到边界**：CODE-REVIEW 118,754→73,278／FIX-LEDGER 233,587→101,406⇒FILE 转绿；一把被否证的切法＋一枚 `--go` 漏写自纠）

> **本节按主人的第 6 条字分三段写**（需求／经过／结果）。阶段 3–5 的读数与方案续在本节末，不另起节次。

- **需求（六条字原样引，10-17 16:1x）**＝①「先把 docs 目录下文件文本量过大的问题处理掉，我允许你严格遵循项目规则，搬运压缩文件内容，add和commit」②「处理完docs的问题之后，再把code-review剩余字符写完，add和commit」③「把 两处"账自己跟自己对不上"，零出网就能改准 的问题处理掉，add和commit」④「做完上面几点之后，再检测一次整个项目，给待排版的几项思考处理方案，add和commit」⑤「OPT-3 是不是还没做完，没做完就思考一个落地方案，add和commit」⑥「做完上面几点之后，严格遵循项目规则，把任务执行的需求、经过、结果分类整合到docs目录下，然后add和commit」。**本轮范围内没有「跑」字**⇒③④ 两道实网门槛一项没跑；没有「改」字⇒不动一行生产码、不改 `.claude/rules/*`、不登记基线。
- **开工时的真实堵点**＝CODE-REVIEW 118,754 字符／距 `MAX_FILE_CHARS` 120,000 只剩 **1,246**⇒第 2 条字（写本节）在搬之前**物理写不下**；这不是"要不要搬"的岔口，是"不搬就没有载体"的事实。
- **刀 1＝CODE-REVIEW 搬 18 枚已闭环追加节**（`64aae10`）＝追加六十／六十二／六十五／六十六／六十八／七十／七十一／七十二／七十三／七十四／七十五／七十六／七十七／七十八／七十九／八十／八十一／八十二；六十一／六十三／六十四 早在 10-14 23:2x 搬走⇒**号次有空位是历史事实、不是漏搬**。判据＝`--appendix-candidates` 那把尺自己的口径「该节引用的『待你拍板』编号有没有仍是活口」（`scripts/docs-scan.py:676` 的 `open_nums`＝FIX-LEDGER 里编号行不含 ✅ 者），本轮 18 枚全读＝**活引用=无**、累计 50,484。
- **刀 2＝FIX-LEDGER 搬 14 块**（`14866d8`）＝整节两枚（`### 批次划分` CR9 那枚 15,582＝批次〇–八全 ✅／`## CR8 · 实施计划`整块 2,646＝CR8 已收尾）＋待拍板已闭三条（`--item 74,79,80`＝6,598）＋门槛区里**已被后续现值行取代**的旧行 9 组（27,150）。**留在原地、不许空的东西写在刀 3 那段**。
- **刀 3＝门槛①–⑤ 定义行的"同行沿革"整段搬出**（`326ee9a`）＝① L164 7,871→本体 6,119／搬 1,752｜② L166 17,653→4,759／12,894｜③ L168 5,482→4,368／1,114｜④ L170 15,701→7,648／8,053｜⑤ L176 61,788→2,117／59,671＝**83,484 字符**，归档件 84,020。
- **一把被否证的切法（记下来免得下一轮再试）**＝我想把定义行按 `(?=\*\*10-)` 再细切，好把那五枚 LINE 红一起消掉；实测①那枚的第一个 `**10-` 落在 `**307/307（38 文件）**（**10-06 00:0x CR9-64 …` 这个**未闭合括号**内部⇒切了就是**改写句子**而不是搬运段落⇒放弃，只用 `<br>`／`｜<br>` 这类真实结构边界。代价如实认＝五枚定义行本体仍 >1,500⇒那 5 枚 LINE 报警留着。
- **一枚仪器自纠**＝第一条 `--move` 命令**漏写 `--go`**而 `exit=0` 一样成立⇒"写盘没发生"在退出码上完全读不出来；判据要读输出尾部那行 `（dry-run：加 --go 才写盘……）`＋`git status --porcelain`。这条与 10-11 那轮「恒 `return 0` 的闸＝清单为空也算绿」同族＝**退出码不是产物**。
- **「哪枚现值是最新」用机器判**＝逐道门槛把 `> ✅／⚠️` 行按行内 `10-XX`＋`HH:` 取 max，max 之下才进块；**判据本体、`④「最近一次全序列」现值`、`③ 主源档现值`、两枚机制读数、`⑤ 装载态对账`作废标注、以及 10-16／10-17 全部当日轮明细行一律留着**（＝现值载体，状态卡编号格的「当日指针」指的就是它们）。这是 10-10 那轮"目测 5 错 4"的同族防线。
- **无损证明（逐块双证，不整文件 sha）**＝刀 1＝18/18 块「`git show HEAD:` 的字节在归档内=True 且已从活跃文件消失=True」（`runtime/move-1017-cr-proof.out`）；刀 2＝14/14（`runtime/move-1017-ledger-proof.out`，搬出字节 51,967）；刀 3＝5/5（`runtime/move-1017-seg-after.out`）。差额逐处归因＝归档字符 − 搬出字符 ＝ 文件头 195／210／84,020−83,484＝536。
- **结果读数（体量现算，三闸复跑为凭）**＝CODE-REVIEW **73,278**（行数 954→679，距阈余 **46,722**）｜FIX-LEDGER **101,406**（行数 337→240）⇒ **FILE 报警转绿**｜PLAN 42,824（max_line 1,129）｜CONSTRAINTS 26,619｜README 25,018（max_line 499）｜PROGRESS 3,449（max_line 671）。三闸逐刀复跑＝**断链 0**／表格 **40 表·418 行·错位 0**／`--baseline` **NEW=0／KNOWN 11/13**（**消失锚点 2 枚**＝`FILE:docs/FIX-LEDGER.md`＋批次划分表那枚 LINE 巨行；`run_baseline` 明写"不报警、不影响退出码"⇒**不重登记基线、不动 `scripts/docs-scan-baseline.json`**）。
- **「搬」字动作集到此已尽；余下 11 枚报警不是漏跑，是边界**＝SECTION×1＝门槛区 61,545＞30,000＝**结构性**（判据本体 25,011＋当日轮明细 ≈30,000，再搬就要动现值载体）；LINE×9＝五枚定义行本体（切点粒度所限）＋四枚**活表格巨行**（L27／L32＝未闭环看板，L137／L138＝OPT 表；`table_guard` 拒搬活表单行＝守卫生效，与 10-11 那条同形）；SPEED×1＝`docs/PROGRESS.md:12` 那 671 字符住在表格里（同形）。⇒ 剩下只有两条路，都要主人另给一句字：**接受为常态**，或给「改」字（拆巨行；或把门槛①–⑤ 从一枚叶节改成五枚同级子节以各自过 SECTION——按 10-10 那条实测「容器跨度恒等于子节之和」，拆子节能消 SECTION 红，但那是**改结构**）。

- **阶段 4 复测（10-17 16:32，`gate1-104-1017-163x.out`／`gate1-1035-1017-1632.out`）**＝闸1 对着 `dev 1683218 dirty=0` **全绿**（用时 51s）＝`tsc` 0 错｜① **449/449（49 文件）**｜② **24 套 959/959**｜docs 基线 **NEW=0／KNOWN 11/13**｜`--selftest` 样本断链在位｜断链 **0**。③④ 没跑（本轮无「跑」字＝打上游＝花钱）。
- **⚠️ 一处对上一轮说法的更正（仪器面，不是码面）**＝「三本 limiter 账前后逐数相同」这句**证不了 ② 那条真报价没发出**：`data-service/tests/test_p6_mcp.py:22-25` 在 import app 之前就把 `LIMITER_STATE_FILE` 指进 `tempfile.mkdtemp(prefix="cr9100-limiter-")`（CR9-100／#70 的落点隔离＝设计如此），所以该套件的 `get_quote 600519` 那一条**不进服务的进程内账、也不进 durable／7 日窗**。⇒ 正确口径回到 10-14／10-15 那两轮的写法＝**「除闸1 的 ② 自带那一条既有真报价 attempt 外零出网」**；本轮实测三本账 10 个键 pre=post（`mem.akshare-obs 9/0/9`｜`mem.eastmoney 7/73/0`｜`dur 10-17 akshare-obs 23/0`、`eastmoney 50/216`｜`win akshare-obs 408/0`、`eastmoney 435/495`、`realtime-obs 0/0`、`coveredDays 7`）证的是**服务这一侧与那四本账没有增量**，不是"整个闸零出网"。下一轮别再拿它当后者。
- **进程态复测（16:33，全部现查、不引用本轮开头的读数）**＝ds `:8000`→**8108 @13:09:05**／web `:3000`→**9880 @11:01:25**（两棵都没换）；`/health` 200＝`ingestTokenConfigured=true`、`dbBackup.nextRun=2026-10-18 03:30`、`staleCheckNextRun=2026-10-17 17:09:05`；`/sync/status` 的 `jobs[0].nextRun=2026-10-18 02:00`、`skippedReason=catchup: SYNC_CATCHUP=off（每日 cron 不受影响）`、`lastAttempt.at=2026-10-17T02:02:22`⇒**今晚两条腿 armed 成立**；防睡在位到 10-18 09:40（上一格实测字面 `holding until 2026-10-18T09:40`）。

##### 待排期项的处置方案（10-17 16:3x 按"谁能动"分五桶；本轮**零推进、零落码**，第 4 条字要的就是这张表）

> 分桶口径＝**谁能动**（我可动／等主人字／等到场窗口／归他人工／结构性只能接受）。每条给「本体／卡点／代价／推荐」；数字全部本轮现查，出处跟在后面。合计＝A 4 ＋ B 6 ＋ C 5 ＋ D 1 ＋ E 11 枚报警＝**16 枚事项＋11 枚尺的余数**。

- **库与进程的今日免费读数（只读 SQL＋`/health`，零出网）**＝`Product` 现值＝fund **28,086**／stock **5,576**／bond **1,062**／crypto **250**／us **177**／**hk 根本没有那一类行** ⇒ 总 **35,151**；`MAX(snapshotAt)`＝**2026-10-17T02:29:07.473+08:00** ⇒ 10-16 那轮列的"库里没有今天的快照"这一条**已随今晨 02:02 那轮自动结清**（列表腿 `partial_failed`、刷新腿写到 02:29:07，两腿的账都在门槛区 10:2x 那行）；`Watchlist`＝**0 行**（替他做手测预案前先把分母数出来＝这条一直为 0）。
- **A 桶＝我可动、只差一句字（4 枚）**：**A1** OPT-3 第二批（＝本轮立案 **#81**，四刀方案见下节）——前置「新区域必须已能出真数据」已成立（1a＝`CR9-92`／1b＝`CR9-96` 都在 13:09 那棵里、那一屏 10-13 14:0x 首次实机出过块），代价＝① 免费＋④ 必须重跑（≈87 发）＋撤掉主人屏上「当日」那个入口；**推荐＝先批方案，落码与④ 排在同一个交易日窗口**，不要在没有验收窗口的一天里连切四刀。**A2** durable 跨午夜归因 ≈6 行——卡点现查＝`app/utils/limiter.py:396` 那句「存储形状、写路径、节流、留存上限一律不动；要更长的历史只改 `KEEP_DAYS` 这一个常数」；强杀丢 ≤60s 尾巴**不可修**（`taskkill //F` 不走 atexit），跨午夜只影响归因；**推荐＝不批**。**A3** ④ 重跑换档——尺已改正（`PLANNED["test-p5.mjs"]=[18,21,22]` 入库于 `2c72cf4`）⇒ 下一次必绿，代价 ≈87 发；**推荐＝与 ③ 主源档同场跑，别为换档单独买一轮**。**A4** #25 乙（A股名单补新浪备源）——10-13 探针字面＝56 页／20 字段可行、与库内差 **342** 只未查；**推荐＝先做那一件不花钱的**（差集核对只需盘上那两份探针回执＋只读 SQL，动手前先 `ls` 证明回执还在），有差异归因了再谈那 56 发。
- **B 桶＝只有主人能给字或给口径（6 枚）**：**B1** 美股「乙」＝全量名单 **913 次请求**（新浪美股盘 18,241 只 ÷ 服务端硬截 20 行/页）⇔ 库里 us **177** 只 ⇒ 甲的覆盖面现算 **0.97%**；原料钉在未闭环看板那行。**B2** #27 第二步／#51 乙（现价与批量分桶）＝东财 TTL 下界 5s、N 只同窗 ⇒ TTL≥5×N，要交易日读数。**B3** 场外基金长尾净值要不要覆盖（那 28,086 只里的长尾）＝产品口径，不是缺陷。**B4** `POST /api/sync` 上不上 token＝现只有 `checkRequestOrigin`，**推荐不动**（要动＝三处同改，属新岔口）。**B5** 屏上字面＝#74(b) 那句「这批数据的快照截至 X（覆盖 N/M 条）」＋那六串 `REALTIME_TEXT`（都已上屏；句 B 从没实机看过＝开 `/search` 要约 4 批真报价；比率类读数已按 10-05 那条口径挪进机器可读位）。**B6** C31 Docker 验证／G7 完整身份鉴权＝**维持暂缓**（上云或 `WEB_PORT` 对外前必补；当前单机无暴露面）。
- **C 桶＝等到场窗口，不是"没做"（5 枚）**：**C1** ③ 主源档那一格（要开盘且价在动；备源档已两次拿到、bond 格 10-16 已填、us 连续落备源⇒归因在 yfinance 侧）。**C2** #79 的真上游 `boardPaths.legs.byClass`＝**10-19（周四）08:30 那轮自然热点自带、零成本等**（11:08 那轮的形状读数 `{"attempts":0,"byClass":{}}` 已两次同形＝名单腿当时不通）。**C3** #80 的实机一眼＝需要一份 **<3 位分析师**的真研报（缺席才点亮），**不可按需制造**；离线侧已由摘刀钻证过（`missing_roles=[]` ⇒ 恰 4 枚红）。**C4** `diverged` 那一屏＝需要两源**真分歧**，同样不可按需制造（10-13 19:1x 拿到的是整块不渲染的负对照）。**C5** hk 列表到货＝CR9-26② 上游态，可复跑判据＝工作日早上 `curl :8000/products?type=hk` 期望 200＋~4700 行，通了顺手做 CR7-4 的 00700 手测。
- **D 桶＝归他人工（1 枚）**：**D1** 重启服务＝装载判据的载体是进程；本轮零生产码⇒不需要。下一轮若落 A1 的码，重启那一句仍归主人。
- **E 桶＝docs 尺的余数（11 枚报警，见上面刀 3 那段）**＝本轮「搬」字已动到动作集边界；只有"接受为常态"或给「改」字两条路。
- **时间轴（把上面 16 枚排到日历上）**＝今天 16:4x＝落 #81 方案＋状态卡／门槛区／README 换值（第 5、6 条字）｜今晚 **02:00 `/sync`** ＋ **03:30 `dbBackup`**（两腿 armed，明早读 `snapshotAt` 逐类与 `legs`）｜**10-18（周六）＝无窗口**（热点 cron 写死 mon–fri）｜**10-19（周四）08:30＝C2 免费到手**｜下一个交易日窗口＝C1＋A3（④ 换档）＋B2 的读数，同场跑、一次买额度；B1／A4 那两笔名单扇出（913 发／56 发）另排，不并进上面那场。
- **OPT-3 第二批可行性核查（10-17 17:0x，字＝「run OPT-3 feasibility check」；零出网、未落码、开工工作树干净）**＝四刀逐条对着码面验，**判定＝可行，方案改三处**：①**刀 4 摘出本批**＝那两处要改注释的文件都在闸2 构造面清单 `DS_RESPONSE_FILES` 里，而 `ds-contract.test.ts:114-118` 把脏／新提交的构造面时间拧成"现在"⇒**只改注释也会点亮 L3 陈旧闸**（快照停在 10-16 那批），换来的判别力是 0；②**刀 2 删面补六处 `1m` 分支**（`ProductCharts.tsx:92`／`:120`／`:145-146`／`:195`／`:223`／`:576`＝撤 1D 后结构上不可达），同时**实测排除掉我原以为的最大风险**＝`/api/kline?interval=1m` 这条链不受撤档影响（BFF 白名单 `route.ts:22` 仍放行、`test-p2.mjs:281-291` 第 [5] 段直连 BFF）；③**刀 3 的分母换档给得出静态数**＝第 [12] 段 5 条 `ok(` ⇒ 60→55、建议 `[54,55]`，闸2 两处硬编码（`:172` 的 `分母: 11` 与 `:175` 用例名）＋`:149` 的死字面必须同批改。**三枚正向证据**＝默认档 `useState("3M")` 不是 1D／两枚 `data-testid` 无人断言／`scannedWebFiles` 84（要求 >40）⇒ 删两枚余量 43。**前置「已能出真数据」成立但凭据是历史读数**（10-13 14:0x 出块、覆盖面 10/11）⇒ 周六收盘不能免费复现，实机那一眼等交易日。**落码仍等三个字**＝「改」（刀 1＋2＋3 同一笔，刀 3 的对称性不许拆）／「跑」（④≈87 发并与 ③ 主源档同场）／刀 4 走甲乙丙。修订同步进待拍板 #81 条目尾那两行。
- **可行性复核（10-17 18:3x，字＝「另外这些点，请你再评估下你推荐方案的可行性」）第一枚产物＝我自己上一轮写错的 A4，撤案**。上一轮 A 桶那句「**A4＝#25 乙 先做那件不花钱的差集核对（342 只那笔）**」**根本不存在**：`docs/history/2026-10-08-code-review-早期追加归档.md:58` 的节次标题就写着「追加十六 · 10-03 15:2x–15:5x（**#25 乙 立项并落地轮＝CR9-56**）」，同节 ① 段已经把差集归因做完、而且**结论反了**＝那 343 只**全是已摘牌/退市类**（`PT金田A`／`国华退`／`大通退`，含「退市」61 只），新浪独有的只有 1 只（`920202`，北交所）；码面也在＝`akshare_provider.py:1043` 的 `_ak_request(ak.stock_zh_a_spot, 120.0, "ak.stock_zh_a_spot")`＝A 股名单早已换新浪上游。我引的是**同一天凌晨 00:5x 那条过期读数**（「56 页／与库内差 342 未查／立项与否仍待字」），而它住的载体＝FIX-LEDGER 批次划分表、本轮又被我自己搬进了 history ⇒ 过期句在归档里、活跃文件此前没有更正＝本轮补两行（作废标注＋B1 硬约束），原句一律不回改。
- **同形第二次，机制值得单独记**＝10-16 那轮我栽在「grep 截断 ⇒ 把早已裁掉的计划复述成闸门开着等你批」，这轮栽在「**编号还开着吗**查了、**它是什么时候被谁关掉的**没查」。⇒ 新通则：**立"某件仍待字"之前，除了码面／测试／docs 三侧各 grep 一遍，还要把该编号在所有文件里出现的位置按行内时间戳排序、取最新那条为准**；同一件事在同一天里被"凌晨登记／午后落地"是本项目常见的形状（#25 乙、#67、#80 都是这形）。
- **另两条硬条件（不是撤案，是加条件）**：**A3＋C1 的"同场"是顺序问题**——账上自己就记着（README 10-16 15:1x 行）④ 那跑「denied 占 42.5％，桶被自己打满 ⇒ ③ 的 us／hk 主源格照旧空」⇒ 必须 **③ 在前、④ 收尾**，且 ④ 之后当天不要再指望读到主源档（冷却封顶 900s）；**B1 的 913 发是"钱＋时间＋同族连坐"三件事**——`sina.us-list` 走 `_ak_request`（`akshare_provider.py:1318` → `:142 observe()` → `:143 acquire(timeout)` → 超时 `:144 raise ProviderError("… rate-limited (akshare family gate)")`），而 `akshare-obs`＝`min_interval=1.0`／`burst=4`／`rate_per_min=30`（`app/utils/limiter.py:500-506`）⇒ **≥30 分钟独占这一族**、期间基金定期报告／转债名单／A 股名单同走这一族会被连坐拒 ⇒ 不与 02:00 夜跑同晚、不与 ③④ 同场；顺带把 **#27 第二步／#51 乙 改判为独立立项**（同一枚闸约束＋"实时链不打东财"红线仍在，不属任何一批的顺带件）。
- **库里覆盖现算（18:2x 只读 SQL、零出网）＝给 B3 与 B5 那两枚口径决定配免费原料**：stock **5,575／5,576**｜fund **23,856／28,086**（长尾缺 **4,230**）｜bond **314／1,062**（缺 **748**＝覆盖 29.6%）｜crypto 250／250｜us 177／177｜**hk 库里根本没有那一类行** ⇒ 合计 **30,172／35,151＝85.8%**。这三组数正是屏上那句「这批数据的快照截至 X（**覆盖 N／M 条**）」要显示的东西＝**主人不必开 `/search`（那一屏要约 4 批真报价）也能定稿文案**；而"场外基金长尾要不要覆盖"这句也因此有了具体形状＝真正的缺口是 **fund 的 4,230 只长尾＋bond 的 748 只**，代价不是"一句话"而是刷新腿的一次整批（10-15 实测 fund 整批 626s）。
- **需求（10-17 18:5x 的字，原样引）**＝「A语句定稿就保持现在这个，A2 确认不批，然后推九笔。做完了之后进行全量测试，测试完了没问题把任务操作整合到docs目录下文件，如果有记录就更新对应位置。做完了之后add和commit」⇒**这一句里三件事给字、一件事没给**＝句 A 定稿／A2 定档＝不批／push 九笔都动了；**句 B 那六串没给字＝继续挂着**——我没替主人改 `REALTIME_TEXT` 的任何字面，也没为“实机看一眼”开 `/search`（＝约 4 批真报价＝要「跑」字）。生产码一行没动⇒不需要重启服务⇒⑤ 那一格本轮只换读数、不换进程。
- **经过（18:50–18:56，全部现查）**＝`date`＝**18:50:04**、开工 `git status --porcelain`＝**0 行**、`git rev-list --count origin/dev..HEAD`＝**9** ⇒ `git push origin dev` 单次、非 force＝`1c500cd..5c48213  dev -> dev`、EXIT=0，复量＝**0**。全量测试＝`node scripts/gate.mjs --offline` **exit=0**、抬头 `dev 5c48213 dirty=0`、用时 53s＝tsc 0 错｜① **449/449（49 文件）**｜② 24 套 **959/959**｜docs 基线 **NEW=0／KNOWN 11/13**｜`--selftest` 样本断链在位｜断链 **0**；③④ 没跑。零出网自证按 18:3x 那轮改好的口径写＝前后两本 `/health` **十键逐字相同**（`runtime/ledgers-1017-185x-diff.txt` 全列 SAME）＋明说那条 `test_p6_mcp` attempt 住在第四本账、这两本读不到。进程态复测＝8000→8108 @13:09:05／3000→9880 @11:01:25 两棵都没换；`/sync/status` `nextRun=2026-10-18 02:00`＋`/health` 的 `dbBackup nextRun=2026-10-18 03:30` ⇒今晚两条腿仍 armed；防睡在位到 10-18 09:40。
- **结果①＝⑤ 那枚「装载」读数与盘上相反（本轮最值钱的一条，未立案）**＝`_live_stamp.py` 现打 `树戳：HEAD=5c48213 dirty=0/0 ds=2026-10-17T13:09:05 appCommit=2026-10-17T13:28:21 装载=旧码`；第二枚仪器＝`app` 全部 `.py` 的 mtime **max＝`engine.py` 13:04:13＜StartTime**，且 `git status --porcelain -- data-service/app`＝**空**（⇒盘上内容==HEAD，且启动后没有任何文件再变过）⇒进程里那份就是 HEAD 那份＝**成立**。机制读得出＝`tests/_live_stamp.py:67-70` 的 `load_verdict()` 用 `git log -1 --format=%ct -- data-service/app`（**提交**时刻）比进程 StartTime，而本项目顺序是“改码→重启验证→再提交”⇒**提交时刻晚于重启时这枚判定必然假阴**；`2c72cf4` 的 `%ad` 与 `%ct` 同值＝换作者日期也救不了，能救的只有 mtime 或内容哈希。⇒状态卡那格按“成立”写、冲突与机制写进门槛区，**要不要立案＝等主人一句字（我没自行占 #82）**。与 10-15 那轮“装载态的载体是进程⇒两枚相反读数可同时作废”同族，但本轮不同＝其中一枚有确定的假阴机制、另一枚能给出正证，所以不该作废、该修仪器。
- **结果②＝两枚定档＋清单换值＋仍欠的字**＝**A2 durable 跨午夜＝定档不批**（闭；卡点＝`limiter.py:293→:296`／`:396` 那条写在注释里的保留决定／`:339-340`“治正常退出、不治被杀”）；**B5 句 A＝定稿＝现文案一字不改**（`search-client.tsx:310-316`，零代码零断言）⇒**待字 15→14 枚**＝A 桶只剩 A1（#81 第二批）＋A3（④ 换档）、B 6（B5 只剩句 B）、C 5、D 1，E 桶 11 枚报警不变。docs 三件已同步＝门槛区「10-17 18:5x」两行＋「本轮不做／不重开」两行＋README 现值换档。**仍等主人的字**＝句 B 六串要不要改字面；交易日窗口那句「跑」（顺序 **③ 主源档 → ④ 换档 ≈87 发 → 收尾**，B1 那 913 发另排一晚）；第二批「改」字＋刀 4 走甲乙丙（甲＝那两处注释不动）；docs 余下 11 枚报警＝“接受为常态”或给「改」；以及⑤ 那枚冲突要不要占 **#82**。
