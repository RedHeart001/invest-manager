# 投资理财助手（Invest Manager）落地方案

> **文档约定**：本文件是项目**唯一**的需求与执行计划来源（single source of truth）。需求变更、方案调整只改本文件；任务执行进度一律记录到 [Progress.md](Progress.md)，本文件不记进度。

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
| R9 | **测试纪律**：测试失败最多重试 3 次（2026-09-12 用户由 2 上调），仍失败即停止并沟通，不无限重试 | P1 | 见 Progress.md 执行约定 |
| R10 | **外部数据源不可达时必须优雅降级**（标注来源/留空），不阻塞其余功能 | P1 | provider 降级 + `inconclusive` 标注 |
| R11 | **变化归因两阶段策略**：P2 详情页做算法阶段划分（时长/幅度）+ 大波动日事件标注（一律标"可能相关"，不做因果断言）；完整多因素归因归 P5 深度研报 | P2 设计定稿 | 详情页 ③④ 区 |
| R12 | **海外数据源自动降级**：海外源（Tavily/OpenBB/CoinGecko）经用户本地代理优先尝试；不可达时自动切换国内源（东财/新浪）并在界面与产出中显式标注降级状态 | P3–P5 评估定稿 | 各 provider 降级链 + 前端降级标注 |
| R13 | **多源数据对比验证**：关键行情指标（收盘价、净值等）在数据源允许时做双源交叉验证，差异超阈值时显式标注来源与偏差，不做静默取舍；各数据源可用性验证推迟到对应阶段落地时进行 | 规划期补充 | **G3 落地 2026-09-19**：`/quote/verified` 端点 + `providers/chain.py` 的 `verify_metric`（按需，不叠加普通 /quote）+ 测试断言 |
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

**为什么 data-service 不需要任何数据库配置**：它是无状态适配/计算层，只调外部数据源与 LLM，不建库、不写盘；全部持久化在 Next.js 侧 SQLite 单文件（`prisma migrate dev` 一键建表）。data-service 唯一需要的是 Python 3.11+ 虚拟环境 + `requirements.txt`（含 akshare、openbb、tradingagents），全部在项目目录内。

**产出落库的统一模式**：data-service 的一切持久化产出（产品列表同步、热点 digest、深度研报）都**不直连数据库**，而是通过内部 HTTP 回调 Next.js 的 ingest 接口（`/api/*/ingest`）由 BFF 统一落库；异步任务状态由 data-service 内存任务注册表维护（task_id → status/result），BFF 轮询后更新 `ResearchReport.status`。

**数据库选型评估（维持）**：SQLite + Prisma——单机零运维、Docker 挂一个 volume 即持久化；自带 FTS5 支撑中文搜索；未来上云改 provider 为 PostgreSQL 成本低。

## 数据库 Schema 要点（Prisma）

- `Product`：统一产品主表（id, type[stock/fund/bond/crypto/hk/us], code, name, pinyin, exchange, tags JSON, sector, updatedAt）
- `Product_fts`：FTS5 虚表（`$executeRaw` 建），索引 name + code + tags
- `HotspotDigest`：热点摘要（id, date, title, summary, sourceUrls JSON, relatedCodes JSON）
- `ResearchReport`：深度研报（id, code, date, rating, summary, fullReport JSON, status[running/done/failed]）——按 code+date 去重
- `ChatSession` / `ChatMessage`：统一 Agent 对话历史（含工具调用记录）
- `Watchlist`：自选产品（搜索排序加权）
- `SearchClickLog`：搜索点击日志（query, code, ts）——点击率进入搜索排序分
- `KlineDaily`：日 K 增量缓存（code, date, ohlcv, source）——由 Next.js BFF 维护（miss 时回源 data-service 再 upsert），历史日 K 不变只拉增量，详情页秒开；分钟级实时数据仍走内存缓存，不落库。data-service 保持无状态

## 分模块设计

### M1 热点抓取与推送（需求 1）

- **定时任务统一在 data-service（APScheduler）**：每日盘前/盘后 2 次（产品列表同步等同框架调度，Next.js 侧不跑 cron）
- 流程：搜索 API（Tavily）抓财经新闻 → LLM 把热点**结构化为板块/概念标签** → 走 AkShare 板块成分接口（`stock_board_concept_cons_em` / 行业板块）取**成分股 + 主题基金** → 产出 digest 后**回调 `/api/hotspots/ingest` 落库** `HotspotDigest`（data-service 不直连数据库）
  - 相比关键词模糊匹配，板块映射的关联精度与可解释性显著提升（"光伏热点 → 光伏板块 N 只成分股"）
- **推送为正式交付项**：① 站内 dashboard 热点卡片流 + SSE 实时推送（任务完成即推到前端）；② ~~webhook 通道（企业微信/邮件，可配置开关）~~ → **2026-09-19 显式裁剪**（见文末「批次 D 决策记录」）
- 热点卡片下挂"相关产品"（点击进详情页）+"深度解读"入口（调统一 Agent 的 L2 工具出研报）
- 搜索 API 无 key 时降级为"仅站内数据"，标注 `inconclusive`
- **G2 落地（2026-09-19）**：产品主数据每日自动同步——data-service `app/sync_scheduler.py`（APScheduler，默认 02:00 Asia/Shanghai，`SYNC_HOUR`/`SYNC_MINUTE` 可覆盖）+ 启动补跑，回调 web `POST /api/sync`；状态端点 `/sync/status`、手动触发 `/sync/run`。此前仅手动触发（需求"每日全量同步"未自动落地）。

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
  - **引擎采用 B 计划为主力**（`custom-multichar`：技术/基本面/新闻情绪分析师 → 多空辩论 → 研究经理，5 次 LLM 调用/篇）；TradingAgents spike 安装+导入通过（.venv-spike 版本冻结），native 后端留作后续增强
  - **新闻备源定版**：A股个股新闻 = 东财 stock_news_em（R15 限速/熔断）→ **巨潮公告 cninfo（官方披露，非东财域名）** → 缺口标注；美股 = yfinance news
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
- 首批内置技能（**2026-09-13 二轮定稿按稳定性重排**，详见下方 M7 二轮补强）：`hotspot-daily`（热点日报生成，复用 M1 pipeline）→ `tech-indicators`（技术指标解读）→ `fund-report-analysis`（基金定期报告解读，spike 先行）

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

**M7 落地定稿与实现约束（2026-09-13 P6 完成后固化，后续修改不得回退）**

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

1. **技能触发词为子串匹配**，存在误命中可能（如"日报""季报"出现在无关语境也会激活）；当前影响可控（正文注入上限 2400 字符），后续可加词边界匹配或更特化的触发词
2. **状态面板探测超时边界**：探测模式下若某 server 挂起，接口最长阻塞一个 `timeoutMs`（默认 20s）；后续可加探测专用短超时
3. **进程内缓存无上限**：技能缓存、provider 的 `_news_cache` / `_fund_report_cache` 等为无界 Map；单机场景可接受，上云前应加 LRU 上限

### M8 多源降级与频率控制（横向能力，R15，P2 收尾新增）
- **问题背景（2026-09-12 实测）**：东财为 **IP 级滚动窗口限流**——空闲后单次请求可通过，连续 2+ 请求立即触发惩罚（连正常可用的股票 K 线也一起失败，akshare 官方封装同样失败）；惩罚窗口可达数十分钟。缓存命中的请求不受影响
- **主备源链（自动降级）**：同类数据注册有序 provider 链，按序尝试；任一成功即返回并标注来源；全部失败时显式缺口说明（R10），**用户侧永不空白**

  | 数据类别 | 主源 | 备源（已实测） |
  |---|---|---|
  | A股/场内基金 行情 | 东财 ulist | 腾讯 `qt.gtimg.cn`（✅ 实测 200） |
  | A股/场内基金 日K | 东财 push2his | 腾讯 `web.ifzq.gtimg.cn/fqkline`（✅ 43 行）；场内基金再备新浪 `fund_etf_hist_sina`（✅ 3584 行） |
  | 板块成分（概念/行业） | 东财 cons_em | **新浪 `stock_sector_spot/detail`（✅ 实测：84 行业+175 概念，成分股可得）**；同花顺成分接口当前 akshare 版本不存在 |
  | 财经新闻 | Tavily（key 已配置 ✅） | 财联社电报（✅）/ 东财快讯 |
  | 可转债 行情 | 东财 | **新浪 `bond_zh_hs_cov_spot`（✅ 2026-09-13 实测：实时全量约 320 只，含真实成交；非东财域名，绕开限流）**——新增 `sina_bond_provider`（快照缓存 60s + 锁内双检 + 看门狗），注册为 bond 备源 |
  | 可转债 日K | 东财 | **确认无可用备源**（2026-09-13 系统性排除：腾讯 `fqkline`/`kline` 转债 `day` 恒空、`ak.bond_zh_hs_cov_daily` 返回空（JS 解码后无数据，接口已废弃）、新浪通用 K 线 `CN_MarketData.getKLineData` 对转债返回 null、网易 chddata 沙箱 502 待本机复测）→ **限流时降级为显式缺口说明**（R10 语义：可用或显式降级，均属正确行为） |
  | 可转债 列表 | 东财 `bond_zh_cov`（1052 只，含未上市） | **新浪 cov_spot（约 320 只在交易标的）**——东财限流时不再返回空列表（覆盖度较低属降级可用） |
  | 场外基金净值 | 东财天天基金（独立域名族，限流期间实测可用） | 待补（蛋卷/新浪需验证） |
  | 加密 | CoinGecko（R12 代理优先） | 待补（OKX/币安经代理） |
  | 港股 行情 | 东财 `push2` 系（`clist/get` 多 host 降级） | **腾讯 `qt.gtimg.cn`（✅ 2026-09-20 实测：`hk00700` HTTP 200 / 78 字段，字段位置与 A 股一致）**——扩展 `tencent_provider`，注册为 hk 备源（position=1） |
  | 港股 日K | 东财 `push2his` 系（多 host 降级） | **腾讯 `web.ifzq.gtimg.cn/fqkline`（✅ 2026-09-20 实测：`hk00700,day,...` 返回 day 数组，行格式与 A 股同，`qfqday or day` 回退已覆盖）**——同一 provider 覆盖；复权口径与主源一致（均前复权） |
  | 港股 列表 | 东财 `clist/get`（多 host 降级） | **确认无可用备源**（腾讯无全量港股列表接口）→ 显式降级：已有数据保留（C1 空载荷保护 + 降级缩水保护）+ 同步显式报错（R10 语义） |

- **港股接入的实测认知与工程约束（2026-09-20 实测，不得回退）**：
  - **东财 CDN 节点可用性因网络而异，禁止依赖单一节点**：实测 `72.push2.eastmoney.com`（akshare `stock_hk_spot_em` **硬编码**的节点）返回 `RemoteDisconnected`，而 `push2delay.eastmoney.com` / `7.push2.eastmoney.com` 返回 200 真实数据（`89988 阿里巴巴-WR`）。故 `hk_provider` **不套用 akshare 封装**，改为直连东财 + 多 host 按序降级（`HK_SPOT_HOSTS` = push2 / push2delay / 7.push2 / 72.push2；`HK_HIST_HOSTS` = push2his / 33.push2his / 63.push2his），走同一源族限速器（与 A 股共享东财额度）+ 看门狗，全失败才抛 `ProviderError`。**同理适用于任何复用 akshare 封装的路径**：akshare 硬编码单节点 = 绕过本项目的多 host 降级能力。
  - **港股代码为 5 位数字，与 A 股/基金的 6 位不同 → 腾讯符号映射必须按类型显式分派**：新增 `_hk_symbol(code)`（5 位补零 → `hkXXXXX`；非数字或 >5 位返回 `None`）与 `_symbol_for(type_, code)`（`type_=="hk"` 走港股映射，否则走原 `_symbol`）。**禁止复用 A 股的 `_symbol`**——其前缀规则会把 `00700` 误判为 `sz00700`、`89988` 误判为 `sh89988`。**禁止改用"按长度猜类型"的隐式约定**（与 CR-17 同类反模式）。
  - **东财港股列表必须分页，且列表接口禁止用于行情路径（2026-09-20 实测）**：
    - 东财 `clist/get` 对港股**忽略大分页参数**：`pz` 给 100/1000/10000 均只返回 **100 条**；港股 `total≈4707` → 必须按 `total` 分页遍历（约 48 页）。
    - **接口分工红线**：单股行情用 `/api/qt/stock/get`（1 次请求）、批量行情用 `/api/qt/ulist.np/get`（1 次请求）、**全量列表才用 `clist/get` 分页**。**行情路径严禁触发列表分页**——早期版本让 `get_quote` 复用列表快照，实测查询单个港股需拉取 4700 条、耗时约 4 分钟，属设计缺陷（已修正，并由单测 `test_quote_does_not_trigger_list_paging` 锁定）。
    - **同步耗时与其对 BFF 超时的要求**：48 页经源族限速器（最小间隔 5s）→ 实测约 **236s**。故 BFF `lib/sync.ts` 拉取 `/products` 的超时由 180s 放宽至 **600s**（`/api/sync` 的 `maxDuration=800` 覆盖）；**同步期间的其它东财请求会排队**（共享源族额度），属 R15 有意设计，凌晨低峰执行影响可控。

- **转债标的甄别（2026-09-13 重要认知）**：**未上市/已退市转债不在实时行情列表内**（如 113710 四方转债、123285 润禾转02）——其 K 线与行情**本就不可得**，取数时报明确错误而非静默缺失。此前 P2 遗留的"转债 K 线 2 项失败"即因**测试动态选中了此类未上市标的**，被长期误归因为东财限流
- **活跃代码段（K 线口径参考）**：沪 111/113/118、深 123/127/128；`110xxx` 多为沪市老债/已到期段，通常无行情

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

## 实施阶段（建议顺序）

1. **P0 脚手架**：Next.js + TS + Tailwind + Prisma/SQLite 初始化；FastAPI data-service 骨架 + AkShare provider 打通 1~2 个接口
2. **P1 产品主数据 + 搜索**（M2）：全量同步、FTS5、搜索 API 与页面
3. **P2 详情页**（M3）：行情接口 + ECharts 各图表
4. **P3 热点 pipeline**（M1）：搜索 API + LLM 摘要 + dashboard
5. **P4 统一 Agent**（M4）：function calling + L1 工具 + 流式 UI + 会话持久化（工具注册表按 Tool Gateway 结构实现，为 M7 留接口）
6. **P5 Harness 整合**（M5/M6）：OpenBB provider → vendor_adapter → TradingAgents 异步研报 → L2 工具接入统一 Agent + 详情页研报视图
7. **P6 扩展机制**（M7）：Skills 加载器 + 首批内置技能 → MCP client 接入 1~2 个第三方 server → fastmcp 暴露统一行情 API
8. **P7 Docker 化**：双服务 Dockerfile + docker-compose + `.env.example`
   - **骨架提前验证（2026-09-12 定）**：P2 验收后先做最小验证（双镜像可 build、SQLite 卷持久化、容器互通，约半小时），环境坑不积压到 P7——**已于 2026-09-12 五项全过**（构建参数对策沉淀在 Progress.md 当日日志，P7 照单重建）
   - **P7 补强**：SQLite 用 named volume（Windows 不用 bind mount）+ 脚本锁 LF（`.gitattributes`）；web entrypoint 自动 `prisma migrate deploy` + 双服务健康检查 `depends_on: service_healthy`；TZ=Asia/Shanghai（APScheduler 盘前/盘后不错时）；ingest 回调共享密钥 + 仅 web:3000 对外；`python:3.11-slim` 多阶段构建 + 依赖锁版本（openbb 体积预期文档化）；`.env.example` 含 `HTTP(S)_PROXY/NO_PROXY` 代理透传（容器经 `host.docker.internal` 走宿主机代理）；`compose up` 后一键冒烟脚本（quote/kline/search）
   - **P7 二轮补强（2026-09-13 评估定稿，基于骨架验证与 P5 落地事实）**：
     - **requirements.txt 全量 freeze**：锁 akshare / fastapi / apscheduler / yfinance 等版本；**不含 tradingagents / OpenBB SDK**（TradingAgents 仅存于 `.venv-spike` 隔离环境，openbb_provider 实际只用 yfinance）——镜像体积风险解除（akshare 全依赖实测 641MB），**放弃"核心+分析双 tag"预案，单镜像策略**
     - **SQLite 备份机制**：named volume 持久化之外，提供 dev.db 导出/恢复脚本与说明
     - **安全收敛**：compose 中强制配置 `INGEST_TOKEN`（缺省不起服务）；密钥一律经 .env 注入，不写进镜像/库
     - **P6 产物随镜像分发（2026-09-13 评估补充）**：web 镜像必须包含 `skills/`（技能目录）与 `mcp.json`（MCP 白名单），`.dockerignore` 不得排除这两项；stdio 型第三方 MCP server 不参与容器化（`mcp.json` 中默认仅 `local-util` 以 stdio 形式存在于镜像内，`tavily` 等外部 stdio server 保持 disabled）
     - **冒烟脚本扩展为五项**：quote / kline / search / hotspots 状态 / research 状态
   - **P7 三轮补强（2026-09-13 评估定稿，基于 P6 落地事实）**：
     - **容器内服务互访接线（P6 新增依赖，必须接线，否则回调全挂）**：data-service 容器须设 `WEB_BASE_URL=http://web:3000`（hotspot ingest 回调、research ingest 回调、vendor_adapter 回读 web `/api/kline` 三处共用，默认 `http://localhost:3000` 在容器内指向自身必挂）；web 容器须设 `DATA_SERVICE_URL=http://data-service:8000`；**已知小缺陷：回调变量名不统一**（`WEB_BASE_URL`（hotspot/research）vs `WEB_API_BASE`（mcp_server search 回调））——P7 实施时顺手兼容：compose 两值同设 + `mcp_server` 读 `WEB_BASE_URL` 兜底
     - **MCP server 容器化策略**：**默认不进容器**（宿主侧按需 `python -m app.mcp_server --http` 运行即可）；如需容器化，用 compose **profile `mcp`** 做可选服务——**容器内必须绑 `0.0.0.0`**（绑 127.0.0.1 时宿主机经端口映射也访问不到，易踩坑），宿主机映射 `127.0.0.1:8765:8765` 保持仅本机暴露；`WEB_API_BASE=http://web:3000`
     - **healthcheck 约束**：slim 镜像无 curl——web 用 `node -e`、data-service 用 `python -c urllib` 探活；web 的 `/api/health` 端点（骨架验证时建过、已随清理删除）**P7 需重建**（校验 DB 连通，供 `depends_on: service_healthy`）
     - **web 镜像补装 `openssl` + `ca-certificates`**（骨架验证实测：Prisma 引擎在 slim 镜像的 openssl 探测告警，补装即消——此前仅在日志，未入 PLAN）
     - **依赖锁版本具体化**：构建期先 `pip freeze > requirements-lock.txt`，Dockerfile 使用 lock 文件安装（可复现构建）；web 侧 `npm ci` + 既有 `package-lock.json`（已有）
     - **备份脚本具体化**：`data-service/scripts/backup_db.py`——用 Python stdlib sqlite3 **在线备份 API**（WAL 安全，无需停服）——在 data-service 容器执行（`python -m scripts.backup_db`），dev 数据卷以 rw 挂载进 data-service，备份目录用宿主机 bind mount（`./backups`）；支持 `--list` / `--restore FILE` 子命令；恢复 = `compose stop web` → restore → `compose start web` → 冒烟
     - **冒烟脚本修正**：data-service 端口不对外 → 宿主机无法直接打 hotspots/research 状态端点；五项改为：BFF `/api/quote`、`/api/kline`、`/api/search`、`/api/tools/status`（网关+MCP 可视）+ `compose exec data-service` 容器内 `/health`
     - **`.dockerignore` 红线**：必须排除 `.env`、`prisma/dev.db`、`node_modules`、`.next`、`.venv*`、`__pycache__`；必须包含 `skills/`、`mcp.json`
     - **运行策略**：`restart: unless-stopped`；TZ=Asia/Shanghai；备份走在线 API 无需停服
   - **P7 落地定稿与实现约束（2026-09-13 P7 完成后固化，后续修改不得回退）**：
     - **Python 版本必须与锁文件一致**：镜像用 `python:3.12-slim`（对齐开发 venv）。实测教训：曾用 Windows/py3.12 venv 的 freeze 结果去装 3.11 镜像 → `numpy==2.5.3` 要求 Python ≥3.12 → 安装失败。**规则：`requirements-lock.txt` 必须在目标镜像内生成**（`docker run <image> pip install -r requirements.txt && pip freeze`），且不得混入 Windows 专属包（pywin32 等）
     - **web 镜像的 base 阶段禁止设 `NODE_ENV=production`**：会使 `npm ci` 跳过 devDependencies，而 `@tailwindcss/postcss`（构建必需）与 `prisma` CLI（运行时 `migrate deploy` 必需）都是 devDependency → 构建/启动失败。`NODE_ENV` 只在 runner 阶段设置
     - **docker.io 直连在当前网络被拦截（auth 502）→ 基础镜像走 `docker.m.daocloud.io` 前缀**，经 `NODE_IMAGE` / `PY_IMAGE` build args 可覆盖；npm 走 npmmirror + 长超时；pip 走阿里源 + `--timeout 120 --retries 10`
     - **数据卷必须 rw 挂载进 data-service**（备份用只读 URI 读取，恢复需写入）——恢复前必须 `docker compose stop web`
     - **全新数据卷只有表结构、无业务数据**：首次部署需 `POST /api/sync` 同步产品主数据（冒烟脚本会区分"未初始化"与"检索故障"）
     - **启动顺序**：`data-service depends_on web: service_healthy`（其启动补跑与落库回调需要 web 就绪）；web 不反向依赖（避免依赖环）
     - **镜像体积（O8/L2 于 2026-09-14 实测闭环）**：`docker images` 口径 **1.62GB → 1.25GB（-23%）**；容器内实际文件系统占用 **1.29GB → 0.89GB**；精确 `.Size`（压缩后）279MB。**重要认知：devDependencies 不是体积大头**——裁剪后 `node_modules` 仍 833MB，主体是运行时依赖（`@next` SWC 273MB、`next` 156MB、`@prisma` 112MB、`prisma` CLI 67MB、`echarts` 62MB、`@img/sharp` 46MB）；因此"预期 ~0.9GB"的原估算口径有误（0.89GB 是容器内占用而非 `docker images` 口径）
     - **C24 依赖归属变更必须同步锁文件**：把包在 `dependencies` / `devDependencies` 之间移动后，**必须重跑 `npm install --package-lock-only`**——`npm ci` 与 `npm prune` 以锁文件为准，仅改 `package.json` 会导致 `--omit=dev` 把运行时必需的包（本次是 `prisma` CLI）裁掉，容器启动时 `migrate deploy` 直接失败
     - **C25 裁剪必须在独立 stage 完成**：`npm prune` / `rm -rf` **不能在 runner 内"先 COPY 全量再删除"**——被删文件仍留在更早的层里，镜像体积不会下降（实测：仍 1.62GB）。正确做法：`FROM build AS prod-deps` 内裁剪 → runner 只 `COPY --from=prod-deps` 裁剪结果
     - **可选进一步瘦身（未做，评估记录）**：① 把 `prisma migrate deploy` 拆成独立 one-shot 服务，web 镜像可再省 67MB；② 项目未使用 `next/image`，`@img/sharp` 46MB 理论上可去（需验证 `next start` 不强制加载）；③ musl/wasm 平台变体已在本轮裁剪（省 165MB）

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
- **P3–P5 验证增补（2026-09-12）**：
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
- **Docker 镜像体积失控**：openbb 依赖树大，若实测 >3GB 拆"核心镜像 + 分析镜像"双 tag；日常开发保持 Windows 原生，Docker 仅用于部署验证
- **Python 依赖兼容性（2026-09-13 P6 实测教训）**：`fastmcp 4.x` 依赖 `starlette>=1.0.1`（该版本移除了 `Router(on_startup=...)`），与 `fastapi<0.126` 要求的 `starlette<0.51` **硬冲突**，装上后 data-service 直接无法启动。**对策：requirements 锁 `fastmcp>=2.0,<3` + `starlette>=0.40,<0.51`**，P7 构建镜像时沿用同一约束；另：`yfinance`（美股 provider 依赖）此前漏写进 requirements，全新环境会缺——已补齐（P7 镜像构建前须再次核对 requirements 完整性）。**P6 体检补充**：`requests` / `pandas` 此前仅靠 akshare 传递依赖（重建 venv 时暴露脆弱点）→ 已在 requirements 中显式声明
- **合规**：所有 Agent 输出与研报附"仅供参考，不构成投资建议"；TradingAgents 官方声明仅用于研究目的

## 全项目代码审查（2026-09-13 定稿）

> 范围：web 路由/页面层、web lib 层、data-service 全部源码（三路并行审查 + 逐条人工验证）。
> 已修复项视为**新增强制约束**（不得回退）；可优化点（O 系列）待主人逐条决策后实施。
>
> **第二轮审查（2026-09-13 17:00，四路并行）**：修复 C1–C17 与 O 系列后的**全量复检**，
> 共确认 12 项真实缺陷（其中 1 项 P0 死锁），全部已修复（见 Progress.md 当日日志），
> 并新增约束 C18–C21 与既有约束的修订。
>
> **第四轮审查（2026-09-15/16，CR4，三路并行）**：共 P1×5 + P2×12 + P3×25 项，
> **全部已处理并验证**（详细清单与逐条证据/方案见仓库根 `code-review.md`；
> 进度见 Progress.md 09-15/09-16 日志）；本轮可复用规则固化为 **C26–C33**（见下）。
> **唯一未闭环项**：C31（Dockerfile 进程降权）的镜像构建/运行验证——按主人指示暂不推进 Docker。
>
> **第五轮审查（2026-09-17，CR5，单路串行）**：共 P1×2 + P2×1 + 需求交付缺口×3 + P3×6，
> **A+B 批 8 项已实施并验证**（反向验证 + 全量回归，见 Progress.md 09-17 日志与 `code-review.md` CR5 节）；
> 可复用规则固化为 **C34**（见下）。**暂不处理**：CR5-P4（写接口鉴权，上云前必补）与
> CR5-D1/D2/D3（R13 交叉验证 / webhook 推送 / LLM 兜底召回）——PLAN 需求条目保持原样，边界见 `code-review.md`。

### 已修复并固化的约束（C 系列，不得回退）

- **C1 空载荷保护**：`syncType` 全量替换（先删后插）前必须判空——上游返回空列表时**保留旧数据并返回 error**，禁止静默清库（数据丢失风险）
- **C2 会话上下文取最近 200 条**：`getMessages` 必须 desc 取再反转时间序；asc+take 会静默丢弃最新对话
- **C3 LLM 流必须 flush 尾帧**：最后一帧常无换行结尾（可能携带 finish_reason/tool_calls 分片）；且工具调用产出**只看累积结果**，不强依赖 `finish==="tool_calls"`
- **C4 行情数值缺失一律 null**：禁止 `Number(null)===0` 式转换把"缺价"上报成"现价 0 元"
- **C5 provider.get_news 契约 = list[dict]**：研报采集链对 dict/list 双兼容（此前东财主源一旦真正返回新闻就 AttributeError 打挂整条研报任务，巨潮备源成死代码）
- **C6 限速器成功回报时机**：HTTP 状态码校验与 JSON 解析必须在 `_em_request` 闭包**内**完成——5xx/非 JSON 不得清零熔断计数（否则熔断形同虚设）
- **C7 akshare 调用统一看门狗**：新增 `app/utils/timeout.py`（守护线程 + join 超时），所有 provider 内 akshare 调用经 `_em_ak_request` / `_ak_request` 包装（上游挂死时调用方按时返回降级，不再永久占住线程池 worker）
- **C8 研报完成推送带会话归属**：启动时登记发起会话（`watchResearch`），完成时 ① 提示落库到发起会话 ② 广播携带 `sessionIds`，前端按当前会话过滤——兑现"任务完成后在同一会话推送"且杜绝跨会话串消息
- **C9 浏览器只与 web 通信**：新增 `POST /api/hotspots/run` BFF 代理；禁止前端直连 data-service（P7 容器化后 data-service 不发布端口）
- **C10 ingest 结果必须可观测**：research 落库回调失败写回任务状态（`ingestOk`/`ingestNote`），禁止"任务显示成功但研报未落库"的静默丢失
- **C11 K 线增量缓存防重复回源**：头部缺口回源失败同样进入失败窗口（30 分钟）；并发写入唯一约束冲突（P2002）按"已写入"处理
- **C12 快照刷新失败必须显式**：整批无可用报价计入 `failedBatches`，禁止"0 更新 0 失败"伪装成功
- **C13 界面细节**：热点时间用北京时间（Intl timeZone）；SSE updater 内禁止副作用；ECharts 卸载必须 dispose；搜索 loading 收尾须确认请求未过期；browse 模式 sort/page 从 URL 还原；详情页五路取数并行
- **C14 安全基线**：外部抓取链接仅放行 `http(s)`；`/api/health` 不回显异常细节；`/api/tools/status` 不回显服务端路径且探测结果缓存 30s；MCP 工具名截断时附加哈希防碰撞
- **C15 FTS 与主表一致性（2026-09-13 状态确认新增）**：`rebuildFts(type)` 必须先做**孤儿清理**（`DELETE FROM Product_fts WHERE productId NOT IN (SELECT id FROM Product)`，与 type 无关、仅删主表中已不存在的行），再按 type 重建。**原因**：L1 全量替换会给产品生成全新 id，按"当前 Product 表 id"定位的 DELETE 无法命中旧 id 的 FTS 行 → 每次同步都会累积与该类型条数相等的孤儿（实测 bond 一次同步即留 1052 行）；且 L1 的暂存表在用完后必须 `DROP TABLE`（不得只 `DELETE`），避免残留空表
  - 配套运维脚本：`web/scripts/fix-fts.mjs`（一次性一致性修复：清孤儿 + 补缺失 + 清暂存表，可重复执行）
- **C16 采集线程安全（2026-09-13 bug 修复固化）**：`adapter._run_with_timeout` 内对模块级计数器（`_collect_live`/`_collect_inflight`）赋值**必须声明 `global`**（L3 引入时仅声明了 `_collect_live`，导致 `_collect_inflight += 1` 变成局部变量 → **UnboundLocalError → 研报引擎全部采集即时崩溃**，且因 test-p5 复用当日已完成研报而未覆盖到）；信号量 `acquire()` **必须有超时**（上游持续挂起占满名额时不得永久阻塞，超时即降级返回）
- **C17 进程内注册表/单例必须挂 `globalThis`（2026-09-13 修复固化，同类问题第二次出现）**：Next dev 按需编译 / HMR 会重建模块作用域，**模块级变量随之重置** → 出现"写入方与读取方持有不同实例"的静默故障。已发生两例：① P6 MCP 运行时注册表（每次重载重复 spawn stdio 子进程）；② **P3 SSE `clients` Map（连接注册在旧 Map、广播查新 Map → 事件偶发丢失，test-p3 间歇失败）**。规则：任何**跨请求共享状态的进程内单例**（连接表、注册表、缓存、锁）一律用 `Symbol.for("invest-manager.<name>")` 挂 `globalThis`；新增此类单例时须检查本约束
- **C18 每轮工具循环必须重新裁剪上下文（2026-09-13 第二轮审查）**：`chat/route.ts` 的工具循环内**不得**使用循环外一次性计算的裁剪快照——超预算时 `trimContext` 返回新数组，循环内 `messages.push()` 的工具结果不会出现在发给 LLM 的数组 → 多轮 function calling 静默失效；同步修正裁剪边界（**最后一条消息自身超预算时硬截断保留，禁止整条丢弃**）
- **C19 研报订阅生命周期（2026-09-13 第二轮审查）**：`researchWatchers` 必须挂 globalThis（C17 同类）；且 **failed 分支同样 `takeWatchers` 清理并向发起会话推送失败说明**——否则 Map 无界增长 + 发起会话收不到任何反馈
- **C20 同步/采集必须单飞（2026-09-13 第二轮审查）**：`syncType` 用**固定名暂存表**，同类型并发同步会互相清空对方暂存行 → 事务拷入不完整集合 → Product 数据丢失；`/api/sync` 可被定时任务与手动并发触发 → 已加按类型 in-flight 单飞；暂存表清理统一放 **finally**（失败路径同样 DROP）
- **C21 数值序列化安全（2026-09-13 第二轮审查）**：`to_float` 必须过滤**全部非有限值**（NaN 与 ±Inf，`math.isfinite`）；所有 provider 的数值字段（含 yfinance `fast_info` / K 线行）禁止裸 `float()`——非有限值进入 JSON 会因 `allow_nan=False` 抛 ValueError → 500，破坏"失败显式降级"契约
- **C22 恢复类操作的先验校验与回滚（2026-09-13 第二轮审查）**：`backup_db.py restore` 必须 ① 恢复前对备份做 `integrity_check` + 表结构校验（非法备份拒绝执行，防止把线上库"恢复"成空文件）② 清理目标库的 `-wal/-shm` 残留（旧 WAL 会被误应用）③ 失败自动回滚原库
- **C23 测试脚本不得污染开发库（2026-09-13 第二轮审查）**：测试内的 `deleteMany({})` 等批量清理**必须限定范围**（如按测试会话/标题前缀），禁止无 where 的全库删除；验收断言不得写死单一数据源 `source` 值（多源链下降级属正确行为）

### 第四轮审查固化约束（C26–C33，2026-09-15/16；修复清单见 `code-review.md`）

> 第四轮全项目 code review（CR4）共处理 P1×5 + P2×12 + P3×25 项，全部落地并验证（详见 Progress.md 09-15/09-16 日志与 `code-review.md`）。其中可复用的强制规则固化为下列约束，后续修改不得回退。

- **C26 跨类型共享实体必须带 type 作用域（2026-09-15 CR4-1）**：A股与基金/转债代码段大量重叠（如 `000001` = 平安银行 stock 与 华夏成长混合 fund 并存于 Product 表）。凡以 `code` 参与唯一键或查询的实体（`ResearchReport` 等）**必须把 `type` 纳入唯一键与 where 条件**——`ResearchReport` 唯一键已由 `(code,date)` 升级为 `(type,code,date)`；新增同类实体时须检查本约束
- **C27 进程内缓存/单例一律挂 `globalThis`（2026-09-15 CR4-2，C17 补漏）**：C17 的适用范围明确包含**缓存**——`kline.lastChecked/lastFailed`、`events` 缓存亦须挂 `Symbol.for` globalThis（dev HMR 重置会使 `lastFailed` 限流窗口失效，叠加回源放大）。C17+C27 合并口径：**任何跨请求共享的进程内单例（连接表、注册表、缓存、锁、watcher）都必须挂 globalThis**，无例外
- **C28 K 线缓存窗口抑制必须双向对称（2026-09-15 CR4-3）**：`kline.ts` 的**头部缺口补齐分支与尾部增量分支**都必须同时判断 `lastFailed`（失败窗口）与 `lastChecked`（复查窗口），且头部缺口"成功但空响应"同样要写入 `lastFailed`——否则上市不足区间的标的每次加载都会整段回源头部缺口，持续捶打上游（R15 限流防线）
- **C29 限速器以"逻辑请求"为单位计次（2026-09-15 CR4-4）**：多 host/多轮重试的**同一逻辑请求**必须包在**单个** `_em_request` 闭包内，只 `acquire()` 一次、只回报一次成功/失败——按 host 逐次计次会在 `failure_threshold=2` 下被两次抖动触发全源族熔断（第 3 个 host 永远轮不到）；状态码校验与 JSON 解析仍必须在闭包内完成（C6）
- **C30 数值转换禁止裸 `float()`（2026-09-15 CR4-5，C21 补漏）**：C21 的"全部 provider 数值字段禁止裸 `float()`"重申适用于 **sina_provider 的 K 线行 / crypto_provider 的 quote+kline / pipeline 板块涨跌幅**等此前漏网处；裸 `float()` 拦不住 NaN（`float(nan)` 不抛异常）会污染缓存与落库文本
- **C31 长驻进程不以 root 运行，但保持 exec 语义（2026-09-15 CR4-6）**：data-service 容器默认用户保持 root（`compose exec` 备份/恢复需写 `/backup`、`/data`），仅 **uvicorn 经 `setpriv` 降权到 uid 1000**（与 web 容器 node 用户同号，共享卷 `prisma-data` 归属不受影响）；`setpriv` 缺失时回退 root 直跑并告警。**⚠️ 此约束的镜像构建/运行验证尚未执行**（主人指示暂不推进 Docker），启用前必须先验证容器内进程 uid、两容器 healthy 与 `compose exec` 备份正常
- **C32 前端在途请求与定时器必须可取消（2026-09-15 CR4-7）**：① 加载型 fetch（图表区间/对比、搜索）必须用 `AbortController` + 请求序号守卫，**过期响应不得写入状态**，收尾 `setPending(false)` 仅限当前请求；② 轮询 `setInterval` 必须有清理路径与**次数上限**，且 effect 内 `await` 之后设置定时器前须检查 `cancelled` 标志（防卸载竞赛泄漏）；③ 轮询循环（如热点触发）须挂卸载标志
- **C33 对外接口输入必须白名单校验（2026-09-15 CR4-8）**：路由层禁止信任 TS 类型（运行时无约束）——`sessions PUT` 的 `role`、`research/start` 的 `type`/`code`、`search` 的 `q` 长度一律显式校验（type 白名单、code `[\w.-]{1,20}`、q ≤100 字符）；`code`/`type` 会拼入研报推送的 markdown 链接，收紧字符集可抑制外链注入面

### 第五轮审查固化约束（C34，2026-09-17；修复清单见 `code-review.md` CR5 节）

> 第五轮全项目 code review（CR5）共确认 P1×2 + P2×1 + 需求缺口×3 + P3×6，其中 **A+B 批 8 项（P1×2 + P2×1 + P3×5）已实施并验证**；需求缺口×3 与 P3 的写接口鉴权项**暂不处理**（边界见 `code-review.md`）。本轮可复用规则固化如下。

- **C34 缓存窗口/计数必须与成功路径对称记账（2026-09-17 CR5-1）**：任何"失败负缓存 / 限流计数 / 熔断计数 / 复查窗口"的写入点，**必须与成功路径成对存在**——只写成功、不写失败的守卫会因此恒假而**静默失效**（代码看起来有防护，实际是死代码）。本次两例：① CR5-1 CoinGecko `_markets_fail_ts` 仅在 `__init__` 与成功路径置 0、失败路径从不写入 → 守卫 `now - fail_ts < COOLDOWN` 恒真失效，不可达时每请求空烧 ~41s；② C28 的 kline `lastFailed`/`lastChecked` 头部缺口分支漏写（CR4-4）。**验收要求**：此类修复必须附**反向验证**（临时回退修复，确认对应断言会失败），防止"声称已修实则失效"再次发生

**CR5 修复的需求映射（CR5 未新增需求编号，其修复回填到既有需求）**

| CR5 项 | 对应需求 | 说明 |
|---|---|---|
| CR5-1 CoinGecko 负缓存 | **R15**（多源降级/频率控制） | 失败冷却失效 → 海外源不可达时持续空烧，属 R15 防线漏网 |
| CR5-2 失败渲染成"已完成" | **R16**（新增，2026-09-17） | 失败终态必须如实呈现，不得回落假象 |
| CR5-3 陈旧 running 死路 | **R17**（新增，2026-09-17） | 长时运行态必须有可退出出口 |
| CR5-P5 热点触发漏刷新 | **R5**（加载反馈）/ **R16** | 等待态收尾必须如实收敛 |
| CR5-P1 缓存挂 globalThis | **C17/C27** | 约束一致性（非新需求） |
| CR5-P2 错误码透传 / CR5-P3 入参上限 / CR5-P6 依赖数组 | **R10**（降级语义）/ **C33**（输入校验） | 既有约束覆盖 |
| CR5-D1 R13 交叉验证 | **R13** | 暂不处理，需求条目保持原样 |
| CR5-D2 webhook / CR5-D3 LLM 兜底 | **M1 webhook 通道** / **M2 兜底召回** | 暂不处理，需求条目保持原样 |
| CR5-P4 写接口鉴权 | **（新增预置项）** | 上云/`WEB_PORT` 对外前必须补；当前单机无暴露面 |

### 可优化点（O 系列，待决策，按建议优先级排序）

| 编号 | 优化点 | 理由 / 现状 | 建议做法 |
|---|---|---|---|
| O1 | 聊天上下文无 token 预算 | 历史固定 200 条 + 每工具结果 4KB，长会话会撑爆 LLM 上下文并降速 | 按字符/token 预算裁剪，只带最近 N 轮 |
| O2 | 进程内缓存无上限 | kline lastChecked/lastFailed、events、research `_tasks`/`_daily_done`、provider `_news_cache` 等均为无界 Map，长期运行内存只增不减 | 统一 LRU（容量上限）或按日清理任务 |
| O3 | 快照刷新可并发 | 每日 sync 与手动 `/api/market/refresh` 可能同时触发长事务，SQLite 单写锁下易超时 | 进程内单飞（in-flight 去重） |
| O4 | sync 长事务持锁 | 单事务 deleteMany+createMany（300s 超时）期间整库写锁 | 临时表 + 原子换名，或缩小事务粒度 |
| O5 | 搜索召回无稳定排序 | LIKE 候选 `take:300` 无 orderBy，短查询召回偏斜；limit 未 clamp | 候选加稳定排序 + `limit` 裁剪到 1~50 |
| O6 | 公共逻辑重复 | 北京时间、行情富集、`_num`、`_chain(_call)`、代码前缀映射各有 2~4 份实现 | 抽公共 util 单一实现 |
| O7 | 前端体验 | ChatUI 消息列表 `key={i}` 无虚拟化；热点站内跳转用 `<a>` 非 `next/link` | 稳定 key + 虚拟列表；改 `Link` |
| O8 | web 镜像 1.62GB | 含 devDependencies；**2026-09-14 已闭环**：1.62GB → 1.25GB（-23%），容器内占用 0.89GB | 独立 `prod-deps` stage 裁剪（C24/C25）+ 去 musl/wasm 变体 |
| O9 | `/hotspots/run` 同步阻塞 | 手动触发在请求内同步执行整条 pipeline（分钟级），占线程池 worker | 复用 scheduler 单飞，立即返回任务状态 |
| O10 | 研报采集线程治理 | 看门狗超时后泄漏线程无法强杀（每次采集最多 6~8 个） | 限制并发采集数并监控 |
| O11 | 技能/打分微开销 | selectSkills 每请求重复扫描目录×2；score 每候选重复 JSON.parse(tags) | 合并复用、预解析缓存 |
| O12 | 可观测性 | safeAppend 失败仅 console（前端不感知）；LLM 请求日志无条件输出 | 流内 `warn` 事件；日志走 debug 开关 |

### O 系列优化实施计划（2026-09-13 已批准并全部执行完成 ✅）

> 实施顺序 **B → M → L**（按风险与改动面递增）。每批独立交付并跑回归门槛：`tsc --noEmit` 零错误 + vitest 全绿 + 受影响集成套件（test-p4/p6）全绿。任一环节失败按 R9 纪律（重试 ≤2 次）后停止并沟通。

#### B 批（低风险，约 0.5 天）

- **B1（O11 技能/打分重复计算）**：`skillsBodyPrompt` 复用一次 `selectSkills` 结果（现重复调用 2 次、含 2 次目录扫描）；`score.ts` 的 `JSON.parse(tags)` 改为模块级 WeakMap 缓存（同一 Product 对象不重复解析）。范围：`web/lib/skills.ts`、`web/lib/gateway.ts`、`web/lib/score.ts`。**验证**：现有 skills/gateway/score 单测全绿（共 29 项）。
- **B2（O5 搜索召回稳定化）**：LIKE 召回查询加稳定排序（`code asc`）避免候选偏斜；`limit` 统一 clamp 到 1~50。范围：`web/lib/search.ts`。**验证**：test-p1.mjs 全绿 + 新增 2 条断言（单字符查询首位为精确代码命中、limit 越界被夹紧）。
- **B3（O12 可观测性）**：`safeAppend` 失败时向 SSE 流发 `warn` 事件（前端 toast 提示"该条可能未保存"）；LLM 请求日志受 `LLM_DEBUG=1` 控制。范围：`web/app/api/chat/route.ts`、`web/lib/llm.ts`。**验证**：test-p4 全绿 + SSR 断言 warn 事件路径存在。
- **B4（O6 公共逻辑抽取）**：新增 `web/lib/time.ts`（`beijingToday()`，替换 kline/research/tools/ProductCharts 四处手写）、`web/lib/quote-enrich.ts`（合并 search.ts/browse.ts 的行情富集）；data-service 侧 `_num` 下沉到 `app/utils/num.py`（akshare/tencent 复用）、`_chain` 收敛到 `app/providers/chain.py`（main.py/mcp_server.py 复用）。纯重构、行为不变。**验证**：全套单测 + test-p1/p2/p5 回归全绿。
- **B5（O7 前端体验）**：ChatUI 消息列表用稳定 key（消息 id，不再 `key={i}`）；HotspotFeed 站内跳转 `<a>` 改 `next/link`。虚拟化暂缓（消息量小，收益低）。范围：`web/app/chat/ChatUI.tsx`、`web/app/HotspotFeed.tsx`。**验证**：页面 SSR 断言 + test-p4 全绿。

#### M 批（中风险，约 1 天）

- **M1（O1 聊天上下文预算）**：组装消息时按**字符预算**裁剪（默认 24,000 字符，`CHAT_CONTEXT_BUDGET` 可配）：先放系统提示与最近轮次，超出则丢弃最旧轮次（成对裁掉，不切断 tool_call/result 配对）；预算耗尽时在 system 尾部追加"更早历史已省略"标注。范围：`web/app/api/chat/route.ts`。**验证**：test-p4 全绿 + 新增断言（构造超长历史后消息总长在预算内、tool 配对完整）。
- **M2（O3 快照单飞）**：`refreshSnapshot(type)` 增加 in-flight Promise 去重（并发触发共享同一次刷新），返回相同的 in-flight 结果。范围：`web/lib/market-snapshot.ts`。**验证**：新增单测（并发调用 2 次 → data-service 只被请求 1 轮）。
- **M3（O2 进程内缓存治理）**：web 侧新增微型 LRU（默认 500 条上限）用于 `kline.lastChecked/lastFailed`、`events`、skills 缓存；data-service 侧 research `_tasks`/`_daily_done` 增加惰性淘汰（完成超过 24h 的任务在下次启动时清出）+ 定时清理钩子。范围：`web/lib/kline.ts`、`web/lib/events.ts`、`web/lib/skills.ts`、`data-service/app/research/tasks.py`。**验证**：单测（LRU 淘汰、任务淘汰）+ 现有套件全绿。
- **M4（O9 手动抓取异步化）**：`/hotspots/run` 改为"提交后台任务 + 立即返回 taskId"，前端轮询 `/hotspots/status`（scheduler 已有单飞锁可直接复用）；BFF 代理路由同步改为轮询模型。范围：`data-service/app/hotspot/scheduler.py`、`data-service/app/main.py`、`web/app/api/hotspots/run/route.ts`、`web/app/HotspotFeed.tsx`。**验证**：test-p3 全绿 + 新增断言（run 立即返回且 status 可见 running → done）。

#### L 批（较大，单独评估后实施）

- **L1（O4 sync 事务粒度）**：全量替换改为"先写临时表 → 事务内原子换名"（`CREATE TABLE ... AS` 复制 schema → 批量写入 → `DROP/RENAME`），把写锁窗口从分钟级降到秒级；保留空载荷保护（C1）。范围：`web/lib/sync.ts`。**风险**：换名期间的查询可见性（SQLite 对 RENAME 的原子性）需先在测试库验证。**验证**：test-db.mjs + test-p1 全绿 + 并发读测试。
- **L2（O8 web 镜像瘦身）✅ 2026-09-14 完成**：`prisma` 移入 dependencies + 锁文件同步（C24）+ 独立 `prod-deps` stage 裁剪（C25）+ 去 musl/wasm 平台变体。**实测**：1.62GB → **1.25GB**（`docker images` 口径，-23%），容器内 0.89GB；两容器 healthy、冒烟 **8/8**。**过程中发现并修复 2 个真缺陷**：① 仅改 package.json 未同步 `package-lock.json` → `prisma` CLI 被 `--omit=dev` 误裁 → `migrate deploy` 必失败（C24 固化）；② 在 runner 内先 COPY 再 prune → 体积不降（层语义，C25 固化）。
- **L3（O10 采集线程治理）**：研报采集并发数上限（信号量，默认 4）+ 泄漏线程计数进 `/research/status` 可观测。范围：`data-service/app/research/adapter.py`、`data-service/app/research/tasks.py`。**验证**：test-p5 全绿 + status 输出含线程数。

#### 执行结果（2026-09-13）

| 批次 | 状态 | 验证 |
|---|---|---|
| B1 技能/打分重复计算 | ✅ | tsc 0 错 + vitest 65/65 |
| B2 搜索召回稳定化 | ✅ | test-p1 19/20（唯一失败为转债行情富集，属东财限流环境波动，人工 curl 验证富集正常） |
| B3 可观测性 | ✅ | test-p4 19/19 |
| B4 公共逻辑抽取 | ✅ | test-p1/p4 全绿 + data-service 离线 45/45 |
| B5 前端稳定 key / Link | ✅ | tsc 0 错 |
| M1 聊天上下文预算 | ✅ | 新增 context-budget.ts（24K 字符可配），test-p4 19/19 |
| M2 快照单飞 | ✅ | test-p1 全绿 |
| M3 缓存 LRU / 任务淘汰 | ✅ | 新增 lib/lru.ts；kline/events 换 LRU；research 任务 24h 淘汰 |
| M4 手动抓取异步化 | ✅ | test-p3 28/28（修复了初版实现的一个死锁：request_run 置 running 后线程再走 _single_flight 直接返回——已改为 _execute 直接执行） |
| L1 sync 暂存表换名 | ✅ | 实测 bond 同步 1052 条写入成功（31.9s 含源拉取），FTS 行数一致，检索正常 |
| L2 web 镜像瘦身 | ⚠️ 代码完成 | prisma 移入 dependencies + Dockerfile npm prune；镜像重建因 Docker Desktop 守护进程退出未完成（需重启 Docker Desktop 后 `docker compose build web` 验证） |
| L3 采集线程治理 | ✅ | adapter 增加信号量（默认 4）+ collect_stats 进 /research/status；离线测试 45/45 |

#### 不做 / 暂缓（已评估）

- ChatUI 虚拟化（消息量小，收益低，B5 仅做稳定 key）
- `hotspots ingest` 拉全量 title 去重（量小，已在 C 系列修复口径问题）
- `ProductCharts` 大数组虚拟化（当前 90 点，风险低）
- MCP 服务器进一步功能（HTTP profile 已可用，外部 stdio 第三方 server 保持 disabled 至网络环境允许）

## 批次 D 决策记录（2026-09-19，第一轮 code review 需求缺口处置）

> 第一轮 code review（见 `code-review.md` 第三节）列出 7 项需求交付缺口 G1–G7，经主人决策如下。

| 编号 | 缺口 | 决策 | 落地/说明 |
|---|---|---|---|
| **G1** | M1 webhook 推送（企业微信/邮件）未实现 | **显式裁剪** | 站内 dashboard + SSE 实时推送已覆盖核心需求；webhook 与"本地单机"定位不匹配，按裁剪处理。**需求条目已在上文 M1 划除**；未来如需，重新立项 |
| **G2** | 产品主数据无自动同步 | **实现** | `data-service/app/sync_scheduler.py` + `/sync/status`、`/sync/run`；默认每日 02:00（北京时间），含启动补跑 |
| **G3** | R13 双源交叉验证未落地 | **实现** | `providers/chain.py#verify_metric` + `/quote/verified`（按需端点，不叠加普通 /quote，避免放大外部请求）；差异超阈值在 `note` 显式标注 |
| **G4** | M2 FTS 无结果时 LLM 兜底召回未实现 | **实现** | `lib/search.ts#llmFallback` + `lib/llm.ts#chatJson`；LLM 未配置/失败时静默降级 |
| **G5** | Watchlist 只读不通写 | **实现** | `/api/watchlist`（GET/POST/DELETE）+ `app/components/WatchButton.tsx`（详情页） |
| **G6** | `hk` 类型无 provider | **实现 + 补备源** | ① `data-service/app/providers/hk_provider.py`（东财直连 + **多 host 降级**，非 akshare 封装）；② **腾讯港股备源**（扩展 `tencent_provider`：`_hk_symbol`/`_symbol_for` + `register_chain(["hk"], …, position=1)`）；③ web 侧 `SYNC_TYPES`、搜索 Tab、行情富集、快照白名单纳入 hk。详见 M8 表「港股」三行 |
| **G7** | 写接口无鉴权 | **部分实现** | B4 已加 Origin/Referer 校验（拦浏览器跨站简单表单）；**完整身份鉴权留待上云前**补齐（届时需 token，当前单机无暴露面） |

**未闭环/前置项**：G7 的完整鉴权；G2/G3/G6 的真实外部源连通性验证（沙箱网络受限，需本地环境实测：`POST /api/sync?type=hk`、`GET /quote?type=hk&code=00700`、`GET /quote/verified?type=stock&code=600519`、`/sync/status`）。

**G6 追加记录（2026-09-20，本地连通性排查后）**：本地 `POST /api/sync?type=hk` 首次失败（`RemoteDisconnected`），排查确认**根因非"港股被封"，而是 akshare `stock_hk_spot_em` 硬编码的 `72.push2` 节点不可达**（同族 `push2delay` / `7.push2` 返回 200 真实数据）。据此：① 重写 `hk_provider` 为直连 + 多 host 降级；② 补腾讯备源（行情 + 日K 均实测可用；列表无备源，显式降级）。**故 hk 实际为「东财多host主源 + 腾讯备源」双层防线**，而非单点。
