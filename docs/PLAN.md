# 投资理财助手（Invest Manager）落地方案

> **文档约定**：本文件是项目**唯一**的需求与设计来源（single source of truth）。需求变更、方案调整只改本文件。
> 任务执行进度记入 [PROGRESS.md](PROGRESS.md)；"不得回退"的约束与数据源事实见 [CONSTRAINTS.md](CONSTRAINTS.md)；
> 代码审查发现见 [CODE-REVIEW.md](CODE-REVIEW.md)，修复状态见 [FIX-LEDGER.md](FIX-LEDGER.md)。

## Context

从零构建一个个人投资理财辅助 Agent 应用。**原始需求（保持不变）**：

1. **市场热点推送**：通过 web search 抓取当前市场热点，并关联推荐基金、股票、虚拟币、债券等理财产品
2. **智能搜索**：按类别 / 名称 / 代码 / 标签搜索理财产品，结果以列表展示，排序贴合用户意图
3. **产品详情页**：单产品页面，用 K 线图、折线图、饼图、数据表等多种图表展示指定时间区间的行情与数据
4. **金融分析 Agent**：可单独对话的 AI 助手，工具调用能力偏向金融分析

### 需求补充记录（讨论中确认，随阶段累加）

| 编号 | 需求 | 确认阶段 | 落地位置 |
|---|---|---|---|
| R5 | **加载反馈**：任何等待场景必须有可见加载态（骨架屏 / 路由 loading / 行内 pending），不允许空白等待 | P1 | `app/components/Skeleton.tsx` 等 |
| R6 | **搜索现场保留**：从结果进详情后返回，结果与查询条件不丢失 | P1 | `lib/search-cache.ts`、`staleTimes` |
| R7 | **导航高亮 + 面包屑**：一级导航按路径高亮；二级页面显示面包屑（首页 / 一级功能 / 当前项） | P1 | `Nav.tsx`、`Breadcrumbs.tsx` |
| R8 | **搜索结果行情覆盖**：各品种展示较前日涨跌（股票/场内基金/可转债实时，场外基金每日净值） | P1 | `akshare_provider.get_quotes` |
| R9 | **测试纪律**：测试失败最多重试 **3** 次（2026-09-12 用户由 2 上调），仍失败即停止并沟通，不无限重试 | P1 | 见 PROGRESS.md 执行约定 |
| R10 | **外部数据源不可达时必须优雅降级**（标注来源/留空），不阻塞其余功能 | P1 | provider 降级 + `inconclusive` 标注 |
| R11 | **变化归因两阶段策略**：P2 详情页做算法阶段划分（时长/幅度）+ 大波动日事件标注（一律标"可能相关"，不做因果断言）；完整多因素归因归 P5 深度研报 | P2 设计定稿 | 详情页 ③④ 区 |
| R12 | **海外数据源自动降级**：海外源（Tavily/OpenBB/CoinGecko）经用户本地代理优先尝试；不可达时自动切换国内源（东财/新浪）并在界面与产出中显式标注降级状态 | P3–P5 评估定稿 | 各 provider 降级链 + 前端降级标注 |
| R13 | **多源数据对比验证**：关键行情指标（收盘价、净值等）在数据源允许时做双源交叉验证，差异超阈值时显式标注来源与偏差，不做静默取舍；各数据源可用性验证推迟到对应阶段落地时进行 | 规划期补充 | **已实现，未接入消费链**（2026-09-19）：`/quote/verified` 端点 + `providers/chain.py` 的 `verify_metric`（按需，不叠加普通 /quote）+ 测试断言。⚠️ 端点当前**零调用方**（见 CR7-3） |
| R14 | **分类浏览**：搜索页选中类型标签即浏览该类全部产品（无需关键词），支持按涨幅/名称/代码排序与分页；全局排序基于行情快照列（同步/刷新任务写入），列表展示仍为实时富集 | P2 | `/api/search` 浏览分支 + `lib/browse.ts` + `lib/market-snapshot.ts` |
| R15 | **多源自动降级 + 请求频率控制**：同类数据源主备链（主源失败/熔断 → 自动切备源，响应标注来源与降级状态）；按"源族"令牌桶限速（东财多域名共享额度，因封禁为 IP 级）+ 连续失败熔断冷却；**目标是用户侧永不空白**，无可用备源时显式缺口说明 | P2 收尾（2026-09-12 批准） | provider 主备链 + `app/utils/limiter.py` + 腾讯/新浪备源 provider |
| R16 | **异常/失败终态必须如实呈现**：服务端失败必须以失败形态呈现，**不得回落为"成功/中性"等假象**（如研报失败不得渲染成"已完成·中性评级"）；降级与数据缺口一律显式标注，不粉饰 | CR5 审查（2026-09-17） | 各前端消费点（`ChatUI` 研报推送、`ResearchPanel` 等） |
| R17 | **长时运行态必须可退出**：异步任务/轮询在到达上限或判定陈旧（执行方疑似重启）时，必须给出**可操作出口**（重新发起/重试入口），不允许用户停留在无出口的等待态 | CR5 审查（2026-09-17） | `ResearchPanel` 轮询 + `lib/research-stale.ts` |

> R16/R17 是 R5（加载反馈）的收尾对应项：R5 管"等待开始时必须有反馈"，R16/R17 管"等待结束时必须如实、且有出口"。三条共同构成完整的加载/等待体验约定。

### 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 市场范围 | 全部：A股 + 国内基金/债券 + 加密货币 + 美股/港股 |
| 技术栈 | Next.js 全栈（App Router + TypeScript）+ Python FastAPI data-service |
| 数据库 | SQLite + Prisma（本地单文件，Docker 挂卷持久化） |
| LLM | OpenAI 兼容接口（base_url / api_key / model 可配置）；目标选型**暂定 DeepSeek + GLM**（2026-09-12，P4 启动时双家 FC spike） |
| Agent harness | TradingAgents（104k★，多智能体深度研报）+ OpenBB（73k★，美股/加密/宏观数据 SDK） |
| 部署 | 先本地单机，预留 Docker 化（Dockerfile + docker-compose） |
| 对话称呼 | 用户已定称呼其为"主人"（2026-09-12） |

## v2 整合设计思路（相对 v1 的三处重构）

1. **统一 Agent 层**：不再有"轻量聊天"和"TradingAgents 深度分析"两套系统。用户只有一个对话入口；Agent 的工具分两档——L1 实时工具（毫秒级：搜索/行情/K线/热点）与 L2 深度研究工具（分钟级：触发 TradingAgents 异步研报）。对话中识别"深度分析 XX"意图时自动升档，详情页按钮是同一工具的另一种触发方式
2. **TradingAgents 消费统一数据层**：不直接接 AkShare/任何外部源，而是实现一个 vendor 适配器（实现其 data-access contract），**回读我们 data-service 的统一行情 API**。一个适配器即让它的基本面/情绪/新闻/技术分析师同时获得 A股 + 美股 + 加密的数据能力，provider 路由逻辑只有一份
3. **OpenBB 归位数据层**：作为非 A 股市场的统一数据 SDK 进入 provider 层，与 AkShare 平级，字段映射到同一内部 schema

## 总体架构

```
┌─────────────────────────────────────────────────────┐
│  Next.js (App Router)                               │
│  ├─ 页面：dashboard(热点) / search /                │
│  │   product/[type]/[code](图表) / chat(统一Agent)  │
│  ├─ BFF API：/api/search /api/quote /api/hotspots   │
│  │   /api/chat(流式) /api/reports                   │
│  ├─ Tool Gateway：内置工具 + Skills + MCP client    │
│  └─ Prisma → SQLite（单文件 dev.db，Docker 挂卷）   │
├─────────────────────────────────────────────────────┤
│  data-service（Python FastAPI，无状态）             │
│  ├─ Provider 层（统一行情 API：/quote /kline /list）│
│  │   ├─ akshare_provider  → A股/基金/债券/港股      │
│  │   ├─ openbb_provider   → 美股/加密/宏观          │
│  │   └─ coingecko_provider→ 加密兜底                │
│  ├─ Agent 层                                        │
│  │   └─ TradingAgents 引擎（LangGraph 多智能体）    │
│  │       通过 vendor_adapter 回读本服务统一行情 API │
│  ├─ MCP Server（fastmcp 暴露统一行情 API，供外部    │
│  │   agent 如 Claude Code 调用）                    │
│  └─ 内存缓存（TTL 分钟级，无文件）                  │
├─────────────────────────────────────────────────────┤
│  LLM（OpenAI 兼容端点）+ 搜索 API（Tavily 等）      │
└─────────────────────────────────────────────────────┘
```

**为什么 data-service 不需要任何数据库配置**：它是无状态适配/计算层，只调外部数据源与 LLM，不建库、不写盘；全部持久化在 Next.js 侧 SQLite 单文件（`prisma migrate dev` 一键建表）。data-service 唯一需要的是 Python 3.12 虚拟环境 + `requirements.txt`，全部在项目目录内。

**产出落库的统一模式**：data-service 的一切持久化产出（产品列表同步、热点 digest、深度研报）都**不直连数据库**，而是通过内部 HTTP 回调 Next.js 的 ingest 接口（`/api/*/ingest`）由 BFF 统一落库；异步任务状态由 data-service 内存任务注册表维护（task_id → status/result），BFF 轮询后更新 `ResearchReport.status`。

**数据库选型评估（维持）**：SQLite + Prisma——单机零运维、Docker 挂一个 volume 即持久化；自带 FTS5 支撑中文搜索；未来上云改 provider 为 PostgreSQL 成本低。

## 数据库 Schema 要点（Prisma）

- `Product`：统一产品主表（id, type[stock/fund/bond/crypto/hk/us], code, name, pinyin, exchange, tags JSON, sector, updatedAt）
- `Product_fts`：FTS5 虚表（`$executeRaw` 建），索引 name + code + tags
- `HotspotDigest`：热点摘要（id, date, title, summary, sourceUrls JSON, relatedCodes JSON）
- `ResearchReport`：深度研报（id, **type**, code, date, rating, summary, fullReport JSON, status[running/done/failed]）——按 **type+code+date** 去重（C26）
- `ChatSession` / `ChatMessage`：统一 Agent 对话历史（含工具调用记录）
- `Watchlist`：自选产品（搜索排序加权）
- `SearchClickLog`：搜索点击日志（query, code, ts）——点击率进入搜索排序分
- `KlineDaily`：日 K 增量缓存（code, date, ohlcv, source）——由 Next.js BFF 维护（miss 时回源 data-service 再 upsert），历史日 K 不变只拉增量，详情页秒开；分钟级实时数据仍走内存缓存，不落库。data-service 保持无状态

## 分模块设计

### M1 热点抓取与推送（需求 1）

- **定时任务统一在 data-service（APScheduler）**：每日盘前/盘后 2 次（产品列表同步等同框架调度，Next.js 侧不跑 cron）
- 流程：搜索 API（Tavily）抓财经新闻 → LLM 把热点**结构化为板块/概念标签** → 走 AkShare 板块成分接口（`stock_board_concept_cons_em` / 行业板块）取**成分股 + 主题基金** → 产出 digest 后**回调 `/api/hotspots/ingest` 落库** `HotspotDigest`（data-service 不直连数据库）
  - 相比关键词模糊匹配，板块映射的关联精度与可解释性显著提升（"光伏热点 → 光伏板块 N 只成分股"）
- **推送为正式交付项**：① 站内 dashboard 热点卡片流 + SSE 实时推送（任务完成即推到前端）；② ~~webhook 通道（企业微信/邮件，可配置开关）~~ → **2026-09-19 显式裁剪**（G1，见文末决策记录）
- 热点卡片下挂"相关产品"（点击进详情页）+"深度解读"入口（调统一 Agent 的 L2 工具出研报）
- 搜索 API 无 key 时降级为"仅站内数据"，标注 `inconclusive`
- **G2 落地（2026-09-19）**：产品主数据每日自动同步——data-service `app/sync_scheduler.py`（APScheduler，默认 02:00 Asia/Shanghai，`SYNC_HOUR`/`SYNC_MINUTE` 可覆盖）+ 启动补跑，回调 web `POST /api/sync`；状态端点 `/sync/status`、手动触发 `/sync/run`。此前仅手动触发。

- **P3 补强（2026-09-12 评估定稿）**：
  - **新闻双源 + 自动降级（R12）**：Tavily（经本地代理）优先；不可达时自动切换东财/新浪新闻源（AkShare，国内可达），digest 与界面显式标注降级状态——原"仅站内数据"降级无热点可发，替换为国内源降级；启动第一步做连通性 spike
  - **复用 P2 新闻/公告 provider**：热点发酵验证与相关个股事件交叉直接调用，不另写新闻抓取
  - **SSE 做成通用基础设施**（连接管理/心跳/断线重连），P4 流式对话直接复用
  - **APScheduler 启动补跑**：重启后发现当日 digest 缺失且已过调度时间则立即补跑，避免热点整天空白

### M2 智能搜索（需求 2）

- 每日全量同步产品列表到 `Product`（走 data-service provider 层，A股/基金走 AkShare，加密走 OpenBB/CoinGecko）——**自动调度见 M1「G2 落地」**
- FTS5 匹配（名称/拼音/标签）+ 代码前缀精确匹配加权 → 组合打分；自选/近期查看/**历史点击率**（`SearchClickLog`）加权
- 兜底：FTS 无结果时 LLM 提取意图关键词再查（**G4 落地 2026-09-19**：`lib/search.ts` 的 `llmFallback` + `lib/llm.ts` 的 `chatJson`；失败静默降级不阻塞搜索）
- UI：搜索框 + 类别 Tab + 结果列表（代码、名称、最新价、涨跌幅、标签），点击进详情（点击行为落 `SearchClickLog`）
- **自选（Watchlist）可写（G5 落地 2026-09-19）**：`/api/watchlist`（GET/POST/DELETE）+ 详情页「加自选」按钮；此前该表只被搜索加权**读取**、无写入入口
- **分类浏览（R14，2026-09-12）**：空关键词 + 分类标签 → 浏览模式（20 条/页，覆盖全部 3.4 万产品）；排序支持涨幅（快照列全局排序 + 当前页实时富集展示）/名称（拼音序）/代码；行情快照随每日同步自动刷新，亦可 `POST /api/market/refresh` 手动触发；快照缺失时退化为代码序并在行情列显示实时值
- **结果价格富集（覆盖全部产品类型，单次批量请求）**：
  - 股票 / 场内基金（ETF、LOF）/ 可转债 → 东财实时行情（`ulist.np` 批量接口）
  - 场外基金 → 每日净值表（全市场单请求 + 内存缓存 30 分钟，含日增长率）
  - 加密货币 → CoinGecko 批量行情；**港股（hk）→ 东财 `stock_hk_spot_em` 快照（G6 落地 2026-09-19）**
  - 无报价品种（如已退市转债）显示 `--` 优雅降级，不阻塞结果展示

### M3 产品详情页（需求 3）

- 路由 `/product/[type]/[code]`，图表库 ECharts
  - 股票/虚拟币：K线图 + 成交量；基金：净值折线 + 资产配置饼图 + 重仓持股列表；债券：可转债 K 线 + 国债收益率曲线
  - 通用：关键指标 stat 卡 + 明细数据表 + 数据来源与时间标注
- **时间区间：预设档位（1D/1W/1M/3M/1Y）+ 自定义起止日期选择器**（回应"指定时间内"）
- **多标的叠加对比**：详情页可加对比标的，归一化收益率曲线同图展示（"变化情况"需要参照系）
- 数据：日 K 走 `KlineDaily` 增量缓存，分钟级实时数据走内存缓存
- **"深度分析"按钮**：触发 L2 工具 → 轮询 `ResearchReport.status` → 渲染研报视图（评级、四位分析师观点、多空辩论摘要、风控结论）
- 债券范围界定：MVP = 可转债（行情全）+ 国债收益率曲线；信用债个券数据源受限，页面上明确标注
- **页面六区结构（2026-09-12 定稿，自上而下、一屏一答）**：
  1. **身份区**：名称/代码/类型标签 + 一句话特点画像——**规则模板生成**（如"跟踪中证新能源指数的大型 ETF，费率 0.5%"），不用 LLM，零延迟、可单测、无幻觉风险
  2. **现状区**：大字号最新价/涨跌幅 + 按类型定制的关键指标卡
  3. **主图区**：时间档位 + K线/净值 + 多标的对比 + 阶段背景带 + 事件标记
  4. **变化解读区**：阶段列表（时段 + 幅度 + 天数 + 可能相关事件），与主图阶段联动
  5. **明细区**：按类型槽位填充（基金持仓饼图/重仓、转债条款、国债收益率曲线、数据表），**长页全展开不折叠**（用户确认）
  6. **深度分析入口**：触发 L2 工具 → 研报视图（P5）
- **变化归因轻量版（R11 第一阶段）**：
  - **阶段划分**：摆动点检测（ZigZag）纯本地算法，基于 `KlineDaily` 数据把选定区间切分为上涨/回调/震荡阶段，标注各段幅度与天数——零外部依赖
  - **事件标注**：阶段转折点 + 大波动日（单日 |涨跌|>3%）按日期挂接当日新闻/公告标题；股票/转债走 AkShare 东财源，基金仅标注季报/分红节点（从轻），加密无免费新闻源降级为仅阶段划分并标注数据缺口
  - **归因克制**：一律标注"可能相关"，不做因果断言（新闻与涨跌同日出现 ≠ 因果），与全局免责声明一致
  - **完整多因素归因**（资金面/情绪/宏观交叉验证）明确归 P5 深度研报，P2 不做
- **身份区/明细区按类型槽位**：

  | 类型 | 特点字段（画像素材） | 归因事件源 |
  |---|---|---|
  | 股票 | 行业/概念标签、市值、PE 及历史分位 | 个股新闻、公告（东财）|
  | 场内基金 | 跟踪指数、规模、费率、折溢价 | 跟踪指数异动（间接）|
  | 场外基金 | 类型/风险等级、经理、规模、重仓行业 | 季报披露、分红节点 |
  | 可转债 | 正股、转股溢价率、评级、强赎/下修状态 | 正股事件 + 强赎/下修公告 |
  | 加密 | 市值排名、24h 量（数据源待决策） | 无 → 仅阶段划分，标注缺口 |

### M4 统一金融分析 Agent（需求 4，v2 核心）

- 单一会话入口 `/chat`，流式输出（SSE）；后端经 OpenAI 兼容端点 function calling
- **工具注册表（分层）**：
  - **L1 实时工具**（毫秒级）：`search_products` / `get_quote` / `get_kline` / `get_hotspots` / `get_fund_holdings`
  - **L2 深度工具**（分钟级）：`deep_research(code)` → 提交 TradingAgents 异步任务；`get_research_report(code)` → 读取落库研报
- 对话行为：常规问题走 L1 即时回答；识别"深度分析/研报/全面评估 XX"意图时，先回复"已启动深度研究（约 2~5 分钟）"，任务完成后在同一会话推送研报摘要与完整报告链接
- System prompt：金融分析助手定位，附免责声明，不做确定性买卖指令

- **P4 补强（2026-09-12 评估定稿）**：
  - **L1 工具 = 已有 API 薄封装**（search/quote/kline/hotspots 在 P1–P3 已存在，工具层只写 schema 描述与调用，不写新数据逻辑）；L1 清单增加 `get_phase_analysis`（复用 P2 阶段划分与事件归因，回答"最近为什么涨"类问题）
  - **意图升档先用关键词规则**（"深度分析/研报/全面评估"），简单可控可单测；详情页按钮为第二触发路径兜底
  - **工具调用过程 UI 透明化**（"正在查询行情…"等可见状态，R5 加载反馈在对话场景的延伸）
  - 会话持久化复用 P0 已建的 `ChatSession`/`ChatMessage` 表，无新增库表

### M5 深度研究引擎（TradingAgents 集成，支撑 M3/M4）

- **vendor_adapter**（本模块主要开发量，约 150~250 行）：实现 TradingAgents 的 data-access contract（行情、基本面、新闻、指标四类接口），内部全部回读 data-service 统一行情 API → A股/美股/加密一套代码全覆盖
- 新闻/情绪类接口：A股接东财/新浪新闻源（AkShare），美股接其原生 vendor（Alpha Vantage，无 key 降级 yfinance）
- **异步任务队列**：FastAPI BackgroundTasks + 内存任务注册表（task_id → status/result，单机够用，不上 Celery/Redis）；BFF 提交任务时先建 `ResearchReport(status=running)`，轮询 data-service `/tasks/{id}` 完成后取回结果落库
- **成本管控**：单次分析十几次 LLM 调用、分钟级耗时 → code+date 去重，每日每标的限 1 次，前端展示进度
- LLM 配置复用全局 `LLM_*`（TradingAgents 原生支持 DeepSeek/Qwen/GLM 及任意 OpenAI 兼容端点）

- **P5 补强（2026-09-12 评估定稿）**：
  - **spike 先行 + 版本冻结**：正式开发前在隔离环境安装依赖并用原生 vendor 跑通最小 demo；spike 失败则启动 B 计划（自研简化多智能体或单 LLM 深度 prompt），不阻塞 P5 其余部分
  - **vendor_adapter 复用链**：A股新闻接口复用 P2 新闻/公告 provider；技术指标接口纳入 P2 阶段划分输出，研报与详情页归因同源
  - **任务熔断**：在 code+date 去重之外，增加单次任务 LLM 调用次数上限与超时自动标记 failed，防止任务挂死
  - **话语体系一致**：研报输出沿用"可能相关"标注 + 免责声明（R11 第二阶段），并引用/扩展 P2 阶段结果而非另起炉灶

- **P5 落地定稿（2026-09-13，A/B 方案执行后同步）**：
  - **引擎采用 B 计划为主力**（`custom-multichar`：技术/基本面/新闻情绪分析师 → 多空辩论 → 研究经理，5 次 LLM 调用/篇）；TradingAgents spike 安装+导入通过（`.venv-spike` 版本冻结），native 后端留作后续增强
  - **新闻备源定版**：A股个股新闻 = 东财 `stock_news_em`（R15 限速/熔断）→ **巨潮公告 cninfo（官方披露，非东财域名）** → 缺口标注；美股 = yfinance news
  - **基本面维度定版**：同花顺财务摘要 `stock_financial_abstract_ths`（主，非东财）→ 东财 `stock_financial_abstract`（备）；取**最新 4 期**（接口按报告期升序，注意排序）；喂入基本面分析师角色
  - **话语约束强化**：缺口角色 view="无法判断"（禁方向性结论）；分析师输出带 `dataBased` 标志，辩论**仅采信有真实数据支撑的角色**；`/api/kline` 响应新增 `phases` 字段（研报与详情页归因同源的契约）
  - **熔断阈值 env 可覆盖**：`RESEARCH_MAX_LLM_CALLS`（默认 12）/ `RESEARCH_TASK_TIMEOUT_S`（默认 480）——超限/超时自动标记 failed，可测
  - 已知限制：研报的财务数据非实时行情口径（报告期滞后）；美股 yfinance 依赖用户网络环境（沙箱内 Yahoo 限流，降级已验证）

### M6 OpenBB 数据 provider（支撑 M2/M3/M5）

- OpenBB Platform SDK 封装为 `openbb_provider`：美股行情/K线/基本面、加密行情、宏观指标（FRED）
- 字段映射到与 AkShare 相同的内部 schema，上层（搜索/图表/TradingAgents）无感知
- vendor 可插拔：yfinance 免费档起步，可选配 Alpha Vantage/FMP key 增强

### M7 扩展机制：Skills + MCP（支撑 M4，v2 预留挂点）

统一 Agent 的工具注册表升级为 **Tool Gateway**，三类工具源聚合后统一命名空间（如 `builtin:search_products`、`mcp:tavily:search`、`skill:valuation:run`），对 LLM 透明：

**① Skills（技能系统，自研轻加载器）**

- 目录约定沿用 Anthropic Agent Skills 开放格式：`skills/<name>/SKILL.md`（frontmatter 声明 name/description/触发条件 + 正文指令 + 可选 scripts/resources 子文件）
- 加载器行为：启动时扫描 `skills/` 仅注入元信息（name+description）到 system prompt；对话命中某技能时按需注入该技能正文与其声明的工具——控制上下文成本
- 与 Claude 生态**双向可移植**：在 Claude Code 里调试好的金融技能（如"财报分析""估值建模""热点日报生成"）拷入 `skills/` 即用，反之亦然
- 首批内置技能（**2026-09-13 二轮定稿按稳定性重排**）：`hotspot-daily`（热点日报生成，复用 M1 pipeline）→ `tech-indicators`（技术指标解读）→ `fund-report-analysis`（基金定期报告解读，spike 先行）

**② MCP client（接入第三方 MCP server）**

- **实现方式定稿（2026-09-13）**：改用**自研轻量 MCP client**（`web/lib/mcp.ts`，约 200 行，**不引入 `@modelcontextprotocol/sdk`**）——协议即标准 JSON-RPC 2.0 + 换行分隔帧，与官方实现互通；自研的理由：零新依赖（P6 已因依赖升级踩坑）、可完全掌控降级与超时行为、可离线单测。配置文件 `mcp.json` 声明 server 列表（stdio / HTTP(streamable) 两种传输；`sse` 为旧协议，明确拒绝并标注原因）
- 候选第三方 server：Tavily 搜索 MCP（替代/增强 M1 的裸 API 调用）、OpenBB 官方 MCP server、SEC 财报类 MCP（如 Equibles）
- 生命周期：server 连接失败不阻塞主流程，降级为"该源工具不可用"并标注

**③ MCP server（对外暴露自身能力）**

- data-service 用 `fastmcp` 把统一行情 API 暴露为 MCP server
- **暴露范围限定（2026-09-13 二轮定稿）**：只暴露 data-service **自有只读能力**（quote / kline / products / news / research 任务查询）；search 依赖 web 侧 Prisma FTS5，经 MCP 工具**回调 web `/api/search`** 实现——**"data-service 不直连库"铁律不破**
- 价值：未来 Claude Code、其他 agent 或第三方客户端可直接把本项目当"投资数据工具箱"调用，无需另写集成

**M7 二轮补强（2026-09-13 评估定稿，基于 P0–P5 落地事实）**

- **Tool Gateway 轻重构**：现工具注册表为单层平铺（`AGENT_TOOLS = L1+L2`），P6 引入**内部命名空间**（`builtin:` / `skill:` / `mcp:`）做来源管理；**发给 LLM 的工具名保持不变**，验收红线 = test-p4 19/19 回归不破
- **Skills 加载器细则**：mtime 热加载免重启；技能正文 token 上限 + 同时激活数上限（防 system prompt 失控）；**技能只允许编排既有 L1/L2 工具，不引入新数据逻辑**（技能 = prompt 指令包 + 工具选择，不是新数据源）
- **首批技能按稳定性重排**：① `hotspot-daily`（读库 digest 生成日报，零新数据逻辑，最稳）→ ② `tech-indicators`（复用 P2 phases 阶段划分）→ ③ `fund-report-analysis` **spike 先行**（基金公告/定期报告数据源未验证，先验证再开发；失败则改做"基金持仓与净值解读"技能）
  - **spike 结论（2026-09-13 已执行）**：✅ **通过**——`fund_announcement_report_em(code)` 返回定期报告披露清单（含季度/半年度/年度报告，按日期**升序**需倒序取最新）、`fund_portfolio_industry_allocation_em(code, year)` 返回行业配置占比；两者均为东财域名（受 R15 限速/熔断约束，暂无备源，冷却期降级为显式缺口）。**按原型开发**，并为技能新增 L1 工具 `get_fund_report`（data-service 端点 `/fund/report`，内存缓存 6h）——技能本身仍只编排工具，不引入新数据逻辑
- **MCP client 务实化**：白名单 `mcp.json`；MVP 只接 **1 个 stdio server**（候选 Tavily MCP，现实形态为 npx stdio）跑通"连接失败 → 降级 → 不阻塞对话"全生命周期；HTTP（streamable）传输保留配置支持但不强制接入

**M7 落地定稿与实现约束（2026-09-13 P6 完成后固化，不得回退）**

- **网关分派**：`web/lib/gateway.ts` 为统一入口；内置工具走 `executeTool`、`mcp_*` 前缀走 MCP 客户端、未知名称返回结构化失败；**内置工具对 LLM 的可见名永不改变**（P4 兼容红线，回归 `test-p4.mjs` 19/19）
- **MCP 运行时注册表必须挂 `globalThis`**（`Symbol.for` 键）：Next.js dev HMR 会重建模块作用域，若存模块级变量则每次热重载都会丢失连接并**重复 spawn stdio 子进程（孤儿进程泄漏）**；配套 `process.once("exit")` 统一清理子进程
- **连接过程必须做 in-flight 去重**：运行时持 `connecting` Promise，并发请求共享同一连接过程，避免并发 spawn 多个子进程
- **传输实测覆盖**：stdio（本地 server 真实握手/调用）与 HTTP streamable（127.0.0.1:8765，10 工具可调）均已实测；`sse` 拒绝并给出原因
- **MCP 客户端进程需能直连本机**：客户端所在进程若被代理环境接管（沙箱/系统代理），访问 127.0.0.1 会被代理拦截（观测为 502）→ 需 `NO_PROXY=*`（排障沉淀）
- **技能加载语义**：frontmatter 解析 → 元信息常驻注入、正文命中注入；mtime 热加载免重启；正文 2400 字符上限 / 同时激活 ≤3（env 可覆盖）；未命中不占上下文
- **`/api/tools/status` 为探测式**：如实反映 connected / degraded / disabled 与降级原因；技能只回传元信息，不回传正文；探测结果缓存 30s（防高频轮询反复 spawn）
- **O 系列新增公共模块（2026-09-13）**：
  - `web/lib/context-budget.ts`：聊天历史按字符预算裁剪（默认 24K 可配 `CHAT_CONTEXT_BUDGET`），从最早整轮丢弃、不切断 tool_calls 配对
  - `web/lib/lru.ts`：微型 LRU（容量上限 + 访问提升），kline `lastChecked/lastFailed`、events 缓存已换用
  - `web/lib/time.ts`：北京时间工具（`beijingToday()` / `beijingShiftDays()`），替换此前 kline/research/tools/ProductCharts 四处手写 `Date.now()+8*3600_000`
  - `web/lib/quote-enrich.ts`：行情富集公共实现（合并 search.ts / browse.ts 的重复代码）
  - `data-service/app/utils/timeout.py`：外部调用看门狗（守护线程 + join 超时）
  - `data-service/app/utils/num.py`：防御式数值转换（NaN≡缺失，akshare/tencent 共用）
  - `data-service/app/providers/chain.py`：主备源链调用收敛（main.py / mcp_server.py 共用）
- **MCP server 只读**：暴露工具集受"无写/交易类工具"约束（测试断言强制）

**M7 已知优化点（非阻塞，低优先，2026-09-13 体检记录）**

1. **技能触发词为子串匹配**，存在误命中可能（如"日报""季报"出现在无关语境也会激活）；当前影响可控（正文注入上限 2400 字符），后续可加词边界匹配或更特化的触发词。**2026-09-20 复核：仍未修复**，`web/lib/skills.ts:175` 依旧为 `text.includes(t.toLowerCase())`。**2026-09-22 已拍板并落地**：走「路线 C」——注册内置工具 `load_skill` 由主 LLM 自主加载技能正文，废除子串匹配路由（`SKILL_ROUTER` 三档开关，`keyword` 档保留作 env 回滚）；TypeSafe/Jev（境外 SaaS）与 Laya（自托管）两条候选路线评估后均未采纳。评估证据与实施要点见 [FIX-LEDGER.md](FIX-LEDGER.md) OPT-1（当日实施并验收达标：加载率 100% / 误加载率 0%，commit `10745ff`）。**
2. **状态面板探测超时边界**：探测模式下若某 server 挂起，接口最长阻塞一个 `timeoutMs`（默认 20s）；后续可加探测专用短超时。**2026-09-20 复核：未见修复**
3. ~~**进程内缓存无上限**：技能缓存、provider 的 `_news_cache` / `_fund_report_cache` 等为无界 Map~~ —— **已闭环（2026-09-19）**：`data-service/app/utils/lru.py` 落地，`akshare_provider` 的 `_news_cache`（`Lru(512)`）/ `_fund_report_cache`（`Lru(256)`）与 `sina_provider._cache` 均已换用

### M8 多源降级与频率控制（横向能力，R15，P2 收尾新增）

- **问题背景（2026-09-12 实测）**：东财为 **IP 级滚动窗口限流**——空闲后单次请求可通过，连续 2+ 请求立即触发惩罚（连正常可用的股票 K 线也一起失败，akshare 官方封装同样失败）；惩罚窗口可达数十分钟。缓存命中的请求不受影响
- **主备源链（自动降级）**：同类数据注册有序 provider 链，按序尝试；任一成功即返回并标注来源；全部失败时显式缺口说明（R10），**用户侧永不空白**
  - 完整主备源矩阵（含各类别实测结论、港股三行）见 [CONSTRAINTS.md §C-4](CONSTRAINTS.md)
- **港股接入的实测认知与工程约束（2026-09-20 实测，不得回退）**：见 [CONSTRAINTS.md §C-3](CONSTRAINTS.md)
- **转债标的甄别（2026-09-13 重要认知）**：见 [CONSTRAINTS.md §C-1](CONSTRAINTS.md)

- **频率控制（防 ban）**：
  1. **按源族限速**：同一集团多域名（如 *.eastmoney.com）共用一个令牌桶——封禁是 IP 级，按域名分别限速无效
  2. **参数**：最小请求间隔 5s、突发容量 2、稳定速率 每分钟 ≤12 次；超出排队等待，等待超时（默认 20s）直接走备源，不硬等
  3. **熔断冷却**：连续失败 2 次 → 该源进入冷却（起始 180s，指数递增至上限 900s），冷却期内一律走备源
  4. **缓存前置**：KlineDaily 增量缓存 + 内存 TTL（已有）让重复访问零外部请求；R14 快照列避免浏览页全量实时拉取；批量同步（每日低频）沿用自身 0.8s 间隔不受此限速约束
  5. **可观测**：响应携带 `source` 与降级 `note`（如"主源限流，已降级至 tencent"），页面「备注」区展示

## 界面与交互约定（贯穿所有页面，P1 期间新增）

以下为讨论中确认的通用交互要求，适用于后续所有页面（P2 起的图表页、P3 热点页、P4 对话页均须遵守）：

| 约定 | 要求 | 已落地实现 |
|---|---|---|
| **加载反馈** | 任何需要等待的操作必须有可见加载态，不允许出现"空白等待"：列表用骨架屏（skeleton）、路由切换用 `loading.tsx`、行内操作（如打开详情）用 pending 文案（如"打开中…"） | `app/components/Skeleton.tsx`、`/search` 与 `/product/[type]/[code]` 的 `loading.tsx` |
| **搜索现场保留** | 从搜索结果进入详情后返回，结果与查询条件必须保留（主流搜索体验）：结果缓存（内存 + sessionStorage，60s 内直接复用、过期后台刷新）+ 最近搜索条件恢复 + 路由缓存复用 | `lib/search-cache.ts`、`next.config.ts` 的 `experimental.staleTimes` |
| **导航高亮** | 顶部一级导航按当前路径高亮；子页面归属其所属一级功能（如产品详情页高亮"搜索"） | `app/components/Nav.tsx`（`aria-current="page"`） |
| **面包屑** | 二级及以下页面显示面包屑，路径为「首页 / 一级功能 / 当前项」，末项不可点击 | `app/components/Breadcrumbs.tsx`，已用于搜索页与产品详情页 |

## 实施阶段

P0–P7 **全部完成**（基线提交 `b22671f`，2026-09-13）。

| 阶段 | 内容（对应模块） | 状态 |
|---|---|---|
| P0 脚手架 | Next.js + TS + Tailwind + Prisma/SQLite 初始化；FastAPI data-service 骨架 + AkShare provider 打通 | ✅ |
| P1 产品主数据 + 搜索 | M2：全量同步、FTS5、搜索 API 与页面 | ✅ |
| P2 详情页 | M3：行情接口 + ECharts 各图表 | ✅ |
| P3 热点 pipeline | M1：搜索 API + LLM 摘要 + dashboard | ✅ |
| P4 统一 Agent | M4：function calling + L1 工具 + 流式 UI + 会话持久化（工具注册表按 Tool Gateway 结构实现，为 M7 留接口） | ✅ |
| P5 Harness 整合 | M5/M6：OpenBB provider → vendor_adapter → 异步研报 → L2 工具接入 + 详情页研报视图 | ✅ |
| P6 扩展机制 | M7：Skills 加载器 + 首批技能 → MCP client 接入第三方 server → fastmcp 暴露行情 API | ✅ |
| P7 Docker 化 | 双服务 Dockerfile + docker-compose + `.env.example` | ✅ |

> **P7 的构建/部署细节与"不得回退"约束**见 [CONSTRAINTS.md §D](CONSTRAINTS.md)；三轮补强的完整评估记录见 [history/2026-09-14-ops-容器化记录.md](history/2026-09-14-ops-容器化记录.md)。

## 配置项（.env）

```
# ---- 基础 ----
DATABASE_URL=file:./dev.db
DATA_SERVICE_URL=http://localhost:8000

# ---- LLM（OpenAI 兼容；DeepSeek/GLM 可按 LLM_MODEL 推断 base_url） ----
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=

# ---- 搜索（P3 热点 pipeline；SEARCH_API_KEY 为 TAVILY_API_KEY 的别名） ----
TAVILY_API_KEY=

# ---- P6 扩展机制 ----
SKILLS_DIR=./skills              # 技能目录（默认 ./skills）
MCP_CONFIG=./mcp.json            # 第三方 MCP server 白名单（可空）
SKILL_MAX_BODY_CHARS=2400        # 技能正文注入上限（字符，可覆盖）
SKILL_MAX_ACTIVE=3               # 单轮同时激活技能数上限（可覆盖）
MCP_TIMEOUT_MS=20000             # MCP 握手/调用超时
MCP_RETRY_COOLDOWN_MS=60000      # MCP 连接失败后的重试冷却（防 spawn 风暴）

# ---- 落库回调鉴权（P3 起可选；P7 容器化时强制） ----
INGEST_TOKEN=

# ---- 聊天与 LLM（O 系列新增） ----
CHAT_CONTEXT_BUDGET=24000       # 聊天历史上下文字符预算（lib/context-budget.ts）
LLM_DEBUG=                      # 设 1 时输出 LLM 请求日志（默认静默）

# ---- P7 预留 ----
ALPHA_VANTAGE_API_KEY=           # 可选：TradingAgents/OpenBB 增强数据源，无 key 走 yfinance
HTTP_PROXY=                      # 容器经 host.docker.internal 走宿主机代理（R12 海外源）
NO_PROXY=

# ---- data-service 侧 ----
WEB_API_BASE=http://localhost:3000   # MCP search_products 回调 web BFF 的地址
MCP_HTTP_HOST=127.0.0.1              # MCP HTTP 仅绑本机
MCP_HTTP_PORT=8765
RESEARCH_MAX_COLLECT_THREADS=4       # 研报采集并发线程上限（utils/timeout.py 信号量）
```

> 完整模板见 `web/.env.example`（P6 已补全为全量清单）。

## 验证方式

- P1：搜索"贵州茅台"/"600519"/"新能源"均返回合理列表；打分排序（含点击率加权）有单测
- P2：股票/基金/虚拟币各验一个标的，**自定义起止日期**与多标的对比下图表数据正确，页面标注来源与时间；日 K 二次访问命中 `KlineDaily` 缓存（日志可证）；阶段划分的时长/幅度可用 K 线数据复算，大波动日事件标注命中已知事件（如分红除权日），归因文案全部含"可能相关"标注；加密标的降级为仅阶段划分且有缺口说明
- P3：手动触发热点任务，digest 落库且相关产品来自**板块成分映射**而非模糊匹配；SSE 实时推送到达前端；无搜索 key 时降级并标注 `inconclusive`
- P4：问"最近光伏板块有什么热点，相关基金有哪些"，L1 工具链完整、回答含真实行情
- P5：① 聊天中说"深度分析 600519"，验证意图升档 → 异步任务 → 研报落库 → 会话内推送；② 详情页按钮对 AAPL 触发同一链路；③ 确认 TradingAgents 全程只走 vendor_adapter（可断外网数据源验证 A股链路）；④ 无 Alpha Vantage key 时自动降级且响应标注来源
- P6：① `skills/` 放入一个示例技能，对话命中后确认正文按需注入且未命中时不占上下文；② 接入一个第三方 MCP server（如 Tavily），其工具出现在 Tool Gateway 且可被 Agent 调用，server 挂掉时降级不阻塞对话；③ 用 MCP inspector 连接本项目的 fastmcp server，验证 quote/kline 工具可调
- P7：`docker compose up` 一键起，数据卷持久化验证

**P3–P5 验证增补（2026-09-12）**：

- P3 增补：海外源不可达时自动切换国内新闻源且界面有显式降级标注（R12）；服务重启后缺失 digest 自动补跑
- P4 增补："最近为什么涨"类问题命中 `get_phase_analysis` 工具；工具调用过程有可见状态
- P5 增补：任务熔断生效（LLM 调用超限/超时自动标记 failed）；spike 验证记录归档
- P6 增补：技能正文 token 上限与同时激活数上限生效（可测）；技能热加载免重启；`/api/tools/status` 可见 MCP 连接/降级状态；stdio server 不参与容器化部署（HTTP 优先）
- **P6 二轮增补（2026-09-13）**：Tool Gateway 重构后 test-p4 19/19 回归不破（LLM 侧工具名不变）；技能只编排既有工具、不引入新数据逻辑（代码评审项）；fund-report-analysis 的 spike 结论（数据源可用性）归档后再开发；MCP client 对所接 server 断开时的降级行为有断言
- **P6 三轮增补（2026-09-13 体检）**：MCP **HTTP(streamable) 传输实测**（tools/list 10 工具 + 工具可调）；**并发连接去重**有单测（并发触发生成单一连接）；MCP server 工具集**只读约束**由断言强制；`/api/tools/status` 探测式状态（connected/degraded/disabled + 原因）可测；技能正文不经接口泄漏
- P7 增补：P2 后骨架验证通过（双镜像 build + 卷持久化 + 容器互通）；容器内 TZ 为北京时间（调度时刻正确）；冒烟脚本全绿；ingest 无共享密钥请求被拒
- **P7 二轮增补（2026-09-13）**：requirements.txt 全量锁版本且镜像内不含 tradingagents/OpenBB SDK；备份脚本导出 dev.db 后可恢复到新卷验证；compose 缺 `INGEST_TOKEN` 时服务拒绝启动
- **P7 三轮增补（2026-09-13 体检）**：① 容器内 `WEB_BASE_URL=http://web:3000` 接线验证（hotspot/research ingest 回调与 MCP search 回调在容器网络下可用）；② `/api/health` 重建且 web `service_healthy` 生效（data-service 等 web 就绪）；③ mcp profile 可选启动时宿主机 `127.0.0.1:8765` 可达、默认不启动时不占端口；④ `.dockerignore` 红线核查（镜像内无 `.env`/`dev.db`/`node_modules`）；⑤ 备份脚本产出可恢复到全新卷并冒烟通过

## 风险与备注

- **AkShare/OpenBB 免费接口稳定性**：provider 层隔离 + 异常降级 + `source` 标注；**provider 输出加 schema 契约测试**（快照校验字段），上游接口变字段时 CI 即时暴露；关键行情指标按 R13 做双源交叉验证，差异超阈值显式标注
- **债券数据受限**：信用债个券的公开免费数据源稀缺，MVP 仅承诺可转债 + 国债收益率曲线，后续视数据源情况扩展
- **TradingAgents 成本与延迟**：分钟级 + 十几次 LLM 调用 → 研报落库去重 + 每日限额 + 异步推送，不阻塞对话
- **A股深度分析数据质量**：依赖 vendor_adapter 回读的统一数据层，新闻/基本面覆盖度弱于美股，研报中需标注数据缺口
- **第三方 MCP server 不可信**：其工具描述与返回内容按不可信数据处理，不参与权限扩大；敏感操作（如下单类工具）默认不接入，仅接只读数据类 server
- **Skills 上下文膨胀**：仅注入元信息、命中时才加载正文的机制必须先行，防止技能增多后 system prompt 失控
- **行情实时性**：免费源延迟约 15 分钟级，页面标注数据时间
- **海外 API 可达性（Tavily/OpenBB/CoinGecko）**：已实测 CoinGecko 在当前网络不可达，同类海外源大概率同命运；对策见 R12（本地代理优先 + 自动降级国内源并显式提示），P3/P5 启动第一步做连通性 spike
- **LLM function calling 兼容性**：目标暂定 DeepSeek + GLM（均支持原生 FC）；P4 启动时做双家 FC spike 验证，工具抽象预留"原生 FC / prompt 工具模式"双模式兜底
- **TradingAgents 集成不确定性**：依赖重、data-access contract 可能随版本变、分钟级高成本——spike 先行 + 版本冻结 + B 计划（见 M5 补强），为全项目技术风险最高点
- **东财反爬限流被放大**：P3 板块成分批量调用与 P5 vendor_adapter 回读会放大请求量，P2 的 `KlineDaily` 缓存是前置依赖，必须先行做扎实；**已落地对策（R15/M8）**：按源族限速（东财 IP 级封禁 → 多域名共享令牌桶）+ 连续失败熔断冷却 + 主备源自动降级
- **第三方 MCP server 供应链**：配置白名单制（`mcp.json` 以外一律不连）、不自动安装、仅接只读数据类 server
- **Docker 镜像体积失控**：openbb 依赖树大，若实测 >3GB 拆"核心镜像 + 分析镜像"双 tag；日常开发保持 Windows 原生，Docker 仅用于部署验证。**实测已闭环**：1.62GB → 1.25GB（见 CONSTRAINTS §D）
- **Python 依赖兼容性（2026-09-13 P6 实测教训）**：`fastmcp 4.x` 与 `fastapi<0.126` 要求的 `starlette<0.51` **硬冲突**，装上后 data-service 直接无法启动。完整定版与理由见 [CONSTRAINTS.md §C-2](CONSTRAINTS.md)
- **合规**：所有 Agent 输出与研报附"仅供参考，不构成投资建议"；TradingAgents 官方声明仅用于研究目的

## 决策记录

> 讨论中已定稿、且不属于需求条目的决策集中在此。逐轮代码审查的发现与修复状态不在这里（见 [CODE-REVIEW.md](CODE-REVIEW.md) / [FIX-LEDGER.md](FIX-LEDGER.md)）。

### 批次 D 决策记录（2026-09-19，CR6 需求交付缺口处置）

> 第一轮全项目审查（CR6，见 `CODE-REVIEW.md`）列出 7 项需求交付缺口 G1–G7，经主人决策如下。

| 编号 | 缺口 | 决策 | 落地/说明 |
|---|---|---|---|
| **G1** | M1 webhook 推送（企业微信/邮件）未实现 | **显式裁剪** | 站内 dashboard + SSE 实时推送已覆盖核心需求；webhook 与"本地单机"定位不匹配。**需求条目已在上文 M1 划除**；未来如需，重新立项 |
| **G2** | 产品主数据无自动同步 | **实现**（已闭环） | `data-service/app/sync_scheduler.py` + `/sync/status`、`/sync/run`；默认每日 02:00（北京时间），含启动补跑 |
| **G3** | R13 双源交叉验证未落地 | **实现端点，未接入消费链** ⚠️ | `providers/chain.py#verify_metric` + `/quote/verified`（按需端点，不叠加普通 /quote，避免放大外部请求）；差异超阈值在 `note` 显式标注。**但端点当前零调用方**（CR7-3），R13 的"已交付"判定待重新拍板 |
| **G4** | M2 FTS 无结果时 LLM 兜底召回未实现 | **实现** | `lib/search.ts#llmFallback` + `lib/llm.ts#chatJson`；LLM 未配置/失败时静默降级 |
| **G5** | Watchlist 只读不通写 | **实现** | `/api/watchlist`（GET/POST/DELETE）+ `app/components/WatchButton.tsx`（详情页） |
| **G6** | `hk` 类型无 provider | **取数侧实现 + 补备源**；消费侧部分闭环 ⚠️ | ① `data-service/app/providers/hk_provider.py`（东财直连 + **多 host 降级**，非 akshare 封装）；② **腾讯港股备源**（扩展 `tencent_provider`：`_hk_symbol`/`_symbol_for` + `register_chain(["hk"], …, position=1)`）；③ web 侧 `SYNC_TYPES`、搜索 Tab、行情富集、快照白名单纳入 hk。**消费侧仍有断链**（CR7-4） |
| **G7** | 写接口无鉴权 | **部分实现** ⚠️ | B4 已加 Origin/Referer 校验（拦浏览器跨站简单表单）；**完整身份鉴权留待上云前**补齐 |

**G6 追加记录（2026-09-20，本地连通性排查后）**：本地 `POST /api/sync?type=hk` 首次失败（`RemoteDisconnected`），排查确认**根因非"港股被封"，而是 akshare `stock_hk_spot_em` 硬编码的 `72.push2` 节点不可达**（同族 `push2delay` / `7.push2` 返回 200 真实数据）。据此重写 `hk_provider` 为直连 + 多 host 降级，并补腾讯备源。**故 hk 实际为「东财多 host 主源 + 腾讯备源」双层防线**，而非单点。详细约束见 [CONSTRAINTS.md §C-3](CONSTRAINTS.md)。

### 其他已定稿决策

- **O 系列优化 12 项**（2026-09-13 批准并全部执行完成）——明细见 [history/2026-09-13-cr1-全项目审查与O系列明细.md](history/2026-09-13-cr1-全项目审查与O系列明细.md)
- **P5 引擎选型**：B 计划 `custom-multichar` 为主力（见 M5 落地定稿）
- **MCP client 自研**（不引入官方 SDK）：理由见 M7 ②
