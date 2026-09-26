# 代码审查发现记录（CODE-REVIEW）

> **职责**：记录**各轮审查发现了什么**。本文件只增不改——已发布的发现不因后续修复而删除或改写，
> 状态变化记在 [FIX-LEDGER.md](FIX-LEDGER.md)。
> 需求与设计见 [PLAN.md](PLAN.md)，约束见 [CONSTRAINTS.md](CONSTRAINTS.md)。
>
> **提新发现前先查**文末「附录 · 已核验排除的误报（跨轮累计）」，避免重复提已证伪项。

> **速览**：这里只记"各轮审查**发现了什么**"，修没修、怎么修、按什么顺序修都看 [FIX-LEDGER.md](FIX-LEDGER.md)。**当前轮次是 CR9（2026-09-26 全项目审查，合计 27 项发现：P1×1 + P2×7 + P3×19；CR9-1 已修 `7edc9ef` 并过实网验收，其余 26 项等主人拍板）**；CR8 开放（6 项已拍板待实施，实测确认代码一行未动）；**CR7 代码闭环 14+1、验收 1 项受阻转 CR9-26**（状态只在 [FIX-LEDGER.md](FIX-LEDGER.md) 看板维护，本行只给指针）。已闭环轮次（CR1–CR6）只留压缩结论+指针。编号黑话（CRn / CR-xx / G / V）先查下方「轮次对照表」。

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
| **CR8** | 09-24 | `3b07643`（被审代码） | 界面语义审查（主人本地实跑点击驱动） | `CR8-1..7` | 开放；6 项已拍板待实施（09-26 实测确认代码一行未动），CR8-7 转 OPT-2 |
| **CR9** | 09-26 | `02f0e95`（被审代码，工作树干净） | 全项目审查（CR7 闭环复核 + 两路并行审计 + 实时接口/DB 探针） | `CR9-1..23` | 开放；**23 项全部未处置，等主人拍板** |

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

> **CR9 合计（09-26 收尾口径）**：**27 项 = P1×1 + P2×7 + P3×19**（上表 23 项 + 追加 4 项：CR9-24/25/26/27；其中 CR9-5 降为 P3、CR9-7 升为 P2）。状态与批次只在 [FIX-LEDGER.md](FIX-LEDGER.md) 看板维护。



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
| **CR8-1** | P2 | 「降级产出」横幅把三件不相干的事 OR 成一条，且批次级 note 被逐行复制到每张卡 | R10 / R12（本轮反转其源序）/ R16 | `pipeline.py:628-629` → `web/lib/hotspots.ts:213-215` → `HotspotFeed.tsx:336-343` | 源序改国内为主（可多源，按数据丰富度排序）；拆 `reasons[]`；③ 不显示、② 收页头小字 |
| **CR8-2** | P3 | 「深度解读」名不副实：只是跳 `related[0]` 详情页锚点，不触发分析、不带热点上下文 | M1/M3 语义；与 CR7-3 同族 | `HotspotFeed.tsx:306-312` + `ResearchPanel.tsx:66-77` | 改名「去分析 <股票名>」，不动接口 |
| **CR8-3** | P2 | 来源链接的标题在**后端最后一步被丢弃**，前端只能渲染 3 个无差别的"原文" | 界面约定「来源可追溯」 | `pipeline.py:553`（`:546-552` 手里有 `n["title"]`） | 改 `{url,title}` 全链路透传 + 「相关文章」独立成行 + 截断标题 + hover 全文 |
| **CR8-4** | P3 | 顶部导航随页面滚动，长卡片流下失去一级入口 | 界面约定 | `layout.tsx:19`；实测 `grep -rn "sticky\|fixed\|z-[0-9]" web/app` = 0 命中 | `sticky top-0 z-40` + `#research` 的 `scroll-mt` 补偿 |
| **CR8-5** | P3 | 面包屑把"一级功能"写死，但产品详情页没有固定父级 | **反转**界面约定 `PLAN.md:289` | 4 处调用点：`search/page.tsx:9`、`search/loading.tsx:7`、`product/page.tsx:233`、`product/loading.tsx:9` | 搜索页与详情页面包屑都删；`Breadcrumbs.tsx` 零消费者即删文件 |
| **CR8-6** | P3 | 详情页无页内返回入口；删面包屑后成为唯一回指缺口 | 界面约定 `PLAN.md:287`「搜索现场保留」 | `product/page.tsx:231-239` 只有面包屑，无返回 | 「← 返回」用 `router.back()`，无历史时退化为「首页」链接 |
| **CR8-7** | 候选 | 新闻层多源**合并**（现状是"任一源成功即返回"的 failover） | R15/M8 `PLAN.md:268`；fusion 先例 R13 | `pipeline.py:207-214` + `_EM.acquire` 三处 `:159/:255/:498` | ⏳ **未拍板**，转 `OPT-2`；未查证完不升级为 PLAN 设计 |

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

### 详述 · P3

#### CR8-2（P3）· 「深度解读」名不副实

`HotspotFeed.tsx:306-312` 只是一个 `<Link>`，指向 `related[0]` 的详情页 + `#research` 锚点：不触发任何分析、不携带这条热点的任何上下文。落地页 `ResearchPanel.tsx:66-77` 也只是 `GET /api/research` 读该品种**已有**研报，没有就停在初始态，仍需手动点生成（`:125-153`）。而 `related[0]` 由板块成分返回顺序决定，与热点相关性弱（实测"畜牧业领涨"会跳去解读 600189）。**拍板：只改名，不做真解读**——真做需给 research 接口加上下文参数并决定缓存键（研报按品种缓存），另立需求。

#### CR8-4（P3）· 顶部导航不固定

`app/layout.tsx:19` 的 `<header>` 加 `sticky top-0 z-40`。实测前置条件全部干净：全仓 `web/app` 无 `sticky/fixed/z-*`（无层叠冲突）、header 祖先只有 html/body 且均无 `overflow`（`globals.css` 仅一行 `@import "tailwindcss"`）、四个页面均为文档流滚动（`ChatUI.tsx:399-400` 的 `overflow-y-auto` 是卡片内局部滚动框）。**引入的回归**：CR8-2 的 `#research` 跳转会被固定头部压住 → 同批给 `ResearchPanel.tsx:165` 加 `scroll-mt-*`。阴影：要"滚动才有阴影"需把 header 挪进客户端组件，先用 always-on `shadow-sm`。

#### CR8-5（P3）· 面包屑约定与真实来路不符

`PLAN.md:289` 现明文要求「二级及以下页面显示面包屑，路径为首页 / 一级功能 / 当前项」。但产品详情页**没有固定父级**（一只股票不隶属某个一级功能），于是 `product/page.tsx:233-239` 把中间那级**硬编码成"搜索"**——不管从首页热点还是搜索结果进来都显示"搜索"。叠加 `Nav.tsx:13` 把 `/product` 归到「搜索」高亮，构成两条谎报：主人因此判断"点股票芯片进了搜索"，而实测芯片 href 就是 `/product/{type}/{code}`（`HotspotFeed.tsx:291`），**路由从来没错**。
**拍板**：删搜索页与详情页面包屑（4 处调用点，`page` 与 `loading` **必须成对改**否则导航时闪烁）；`Nav.tsx:13` 的高亮**按主人明确要求保留**（他需要一级归属感），残留的"搜索"高亮是已知且被接受的取舍。删完 `Breadcrumbs.tsx` 零消费者 → 删文件。蓝色板块标签跳 `/search?q=<板块>`（`HotspotFeed.tsx:273`）是设计意图，不在本条范围。

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
2. `providers/__init__.py` 注释称 openbb 为"美股 provider"，但 `us` 是经 `register_chain(position=0)` 注册的，`_QUOTE_REGISTRY` 内并无 `us`——`get_provider("us")` 会 `KeyError` 而 `get_provider_chain("us")` 正常，命名与注册表语义易误读（`_primary()` 依赖 `[0]` 即源于此）。→ **待办**
3. 上一轮读码已报、**至今未处理**的两条：`Progress.md` 完全没有 09-19/20 这一轮的记录；`PLAN.md` 工作树副本"删除了 C18–C23 / C26–C34 的完整定义（−145/+31）"。
   → **2026-09-20 复核，该指控为误报**：`git diff --stat HEAD -- PLAN.md` = **+36/−5**，`grep -cE '^\s*[-*]?\s*\**C[0-9]+' PLAN.md` = **34**，C1–C34 定义一条不少。此条**不再作为待办**。误报在 `code-review.md:402`、`code-review-fix-plan.md:217`、`:321` 三处重复出现，整理时一并清除。
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
| `PLAN.md` 工作树副本"删除了 C18–C23 / C26–C34 完整定义（−145/+31）"（CR7-14-③ / D4-①） | **证伪**：`git diff --stat HEAD -- PLAN.md` = **+36/−5**；`grep -cE '^\s*[-*]?\s*\**C[0-9]+' PLAN.md` = **34**。C1–C34 定义一条不少。原指控在 `code-review.md:402`、`code-review-fix-plan.md:217`、`:321` 三处重复，均已按此结论清除。
  > **⚠️ 2026-09-26 CR9 复验补记（不改原判，只补证据时效）**：上面那条 `grep -cE … PLAN.md = 34` 是在**五文件拆分之前**的 `PLAN.md` 上测的；今天对 `docs/PLAN.md` 重跑同一命令返回 **0**（C1–C34 正文已迁 `docs/CONSTRAINTS.md`，表格式恰 34 行，`PLAN.md:8` 已明文指针）。**结论仍成立（约束一条没丢）**，但任何人按这条证据复跑会得出相反判断 → 已在 [FIX-LEDGER.md](FIX-LEDGER.md) CR9-23-⑥ 登记为文档层待修项。

### CR9 轮排除与撤回（2026-09-26）

> 本轮实测后证伪或撤回的怀疑点，**不要再提**。

| 怀疑点 | 结论 |
|---|---|
| 真实密钥/凭据被提交进仓库 | **证伪**：`.env` 未被跟踪（`git ls-files` 只有两个 `.env.example`）、`git log --all -- .env web/.env` 全历史为空、两个模板密钥位全空、`git grep` 密钥形态仅命中 `package-lock.json` 里 `task-list-item` 的假阳性 |
| 「CR8 批次一代码已写但未提交，工作树有 ~242 行未提交改动」 | **撤回（本审计自身的一次误判）**：`git status --porcelain` 为空、`layout.tsx:19` 无 `sticky`、`web/app/components/PageBack.tsx` 不存在、HEAD `02f0e95` 是纯文档提交——**FIX-LEDGER 的"代码一行未动"记载是对的**。成因：并行审计代理称"改动存在但未入库"，而我未以 `git status` 复核就采信并按"已提交"口径去核对。**纪律回补：subagent 关于版本状态的结论必须由 `git status` / `git show HEAD:<file>` 复核后才可入报告** |
| 「`.claude/rules/project.md` 的文档路由表缺 `CODE-REVIEW.md` 一行」 | **证伪**：`:100` 就在表内（同一审计代理的误报，已复核原文） |
| 「`backup_db.py` 损坏源会残留空壳产物，且 D1 的清理路径不可达」 | **证伪**：`sqlite3.connect()` 不落盘，`src.backup()` 抛错时不创建文件；紧随其后的 `len(dbs)==1` 是真断言，实测 19/19 通过。该文件中真正的问题是 `:64` 的恒真断言（已记 CR9-15），不是清理路径 |
| 「集成产物 `web/verify-suites.txt` 未入库，违反 `.gitignore` 约定」 | **证伪**：该文件当前不存在（`verify-all.mjs:26` 每次写出、无代码读取、未被跟踪），属"一次性产物用完即无"，无需处置 |
| 「fund K 线在 09-25 之前的实跑里已被腾讯串号数据污染」 | **证伪（目前是潜在缺陷而非既存污染）**：`dev.db` 只读核对——`type='fund'` 的 639 条非场内前缀行全为 4 位小数真净值，`fund/110022` 128 行 close=2.781/2.82/2.828，`fund/000001` 0 行。触发条件已具备（CR9-1 实测可达），但库还干净 |
| 「hk 分页上限改成截断而非抛错 → 静默缩水主数据」 | **证伪**：与 CR6 排除表同族——C1 空载荷保护 + `sync.ts` 的 70% 缩水保护双兜住；`hk_provider.py:289-291` 的截断有 `log.warning` | |
