# 代码审查发现记录（CODE-REVIEW）

> **职责**：记录**各轮审查发现了什么**。本文件只增不改——已发布的发现不因后续修复而删除或改写，
> 状态变化记在 [FIX-LEDGER.md](FIX-LEDGER.md)。
> 需求与设计见 [PLAN.md](PLAN.md)，约束见 [CONSTRAINTS.md](CONSTRAINTS.md)。
>
> **提新发现前先查**文末「附录 · 已核验排除的误报（跨轮累计）」，避免重复提已证伪项。

> **速览**：这里只记"各轮审查**发现了什么**"，修没修、怎么修、按什么顺序修都看 [FIX-LEDGER.md](FIX-LEDGER.md)。**当前轮次是 CR8（2026-09-24 界面语义审查，7 项发现：CR8-1…6 已拍板待实施，CR8-7 转 OPT-2 候选）**；**CR7（2026-09-20 第二轮·全项目审查，14 项发现）仍开放**，两轮并行。已闭环轮次（CR1–CR6）只留压缩结论+指针。编号黑话（CRn / CR-xx / G / V）先查下方「轮次对照表」。

---

## 轮次 ↔ 编号 ↔ commit 对照表

> 本项目历史上并行存在过四套编号，这是唯一对照表。**规范轮次为连续的 CR1…CR7。**

| 轮次 | 日期 | commit | 当时的文档称谓 | 编号前缀 | 状态 |
|---|---|---|---|---|---|
| **CR1** | 09-13 | `b22671f` / `f5656d7` ⏳ | "全项目代码审查（2026-09-13 定稿）" | C1–C17 + O 系列 | 已闭环 |
| **CR2** | 09-13 | `3bd73a1` | "第二轮审查（四路并行）" | C18–C23（12 项真实缺陷） | 已闭环 |
| **CR3** | 09-14 | `d6ac165` | **无任何文档记载**（已从 git 重建） | ？（8 项） | 已闭环；记录已重建 |
| **CR4** | 09-15/16 | `4905095` | "第四轮审查（CR4）" | C26–C33（P1×5 + P2×12 + P3×25） | 已闭环；C31 验证未做 |
| **CR5** | 09-17 | `4905095` | "第五轮审查（CR5）" | C34（P1×2 + P2×1 + 缺口×3 + P3×6） | 已闭环；3 项暂不处理 |
| **CR6** | 09-18~20 | `2efda87` | "第一轮·全项目"（**误名**） | `CR-01..22` + `G1–G7` + `V1–V3` | 已处置；遗留 G3/G6/G7 |
| **CR7** | 09-20 | `2efda87`（被审代码） | "第二轮·全项目"（**误名**） | `CR7-1..14` | 开放；逐项状态见 FIX-LEDGER 看板 |
| **CR8** | 09-24 | `3b07643`（被审代码） | 界面语义审查（主人本地实跑点击驱动） | `CR8-1..7` | 开放；6 项已拍板待实施，CR8-7 转 OPT-2 |

**为什么 CR6/CR7 会"误名"**：git 用的是连续"第 N 轮"（CR2–CR5），而 09-18 起文档重新从"第一轮"计数，测试文件却延续内部编号 `test_cr6_*.py`，PLAN 又并行维护 C/O/R 系列——四套编号各说各话。

**命名规则（今后固定）**：
1. 文档层把"第一轮/第二轮·全项目"改标为 CR6/CR7，**保留旧称别名**以免既有引用断链。
2. **不重命名** `test_cr6_*.py` 与既有 id（`CR-01..22`、`G1–G7`、`V1–V3`）——引用稳定性 > 名称纯度，只在对照表注明前缀归属。
3. 今后每轮固定 `CRn` + 编号前缀 `CRn-xx`，轮次与编号前缀数字对齐。
4. 表中带 ⏳ 的格子**必须先取证再填，不允许猜**。取证手段：`git show <commit> --stat`、`git show <commit> -m`、代码注释里的 `CRn-` 标记、测试文件名。

**CR3 的重建**：`d6ac165`（2026-09-14）"fix: 第三轮 code review——8 项缺陷全修（含 1 项回归 + 1 项不完整修复）"。该轮在 PLAN.md / Progress.md / code-review.md 中**均无记载**，已于 2026-09-20 整理时从 `git show d6ac165` 重建，见 [history/2026-09-14-cr3-第三轮重建.md](history/2026-09-14-cr3-第三轮重建.md)。注意其"1 项不完整修复"很可能就是后来 CR4/CR5 反复出现的"修复只做了一半"模式的源头（C11→CR4-4、CR4-6→CR5-3、CR7-1）。

---

## CR8 · 界面语义审查（2026-09-24，当前轮）

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
| `PLAN.md` 工作树副本"删除了 C18–C23 / C26–C34 完整定义（−145/+31）"（CR7-14-③ / D4-①） | **证伪**：`git diff --stat HEAD -- PLAN.md` = **+36/−5**；`grep -cE '^\s*[-*]?\s*\**C[0-9]+' PLAN.md` = **34**。C1–C34 定义一条不少。原指控在 `code-review.md:402`、`code-review-fix-plan.md:217`、`:321` 三处重复，均已按此结论清除 |
