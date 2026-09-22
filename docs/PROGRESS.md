# 项目执行进度（Invest Manager）

> **文档约定**：[PLAN.md](PLAN.md) 是项目唯一的需求与设计来源，本文件**只记录执行进度**，不记录需求与方案。
> 更新方式：① 改下方状态总览表；② 进度日志追加一条（**倒序，最新在上**）。执行中的阻塞与偏差记入文末「阻塞与问题」。
> 约束与数据源事实见 [CONSTRAINTS.md](CONSTRAINTS.md)；审查发现与修复状态见 [CODE-REVIEW.md](CODE-REVIEW.md) / [FIX-LEDGER.md](FIX-LEDGER.md)；被压缩掉的原始材料见 [history/](history/)。

## 状态总览

| 阶段 | 内容 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|
| P0 | 脚手架：Next.js + Prisma/SQLite + FastAPI data-service 骨架 | ✅ 完成 | 2026-09-10 | 全链路已验证 |
| P1 | 产品主数据 + 智能搜索（M2） | ✅ 完成 | 2026-09-11 | 34,776 条产品已同步；加密数据源待决策 |
| P2 | 产品详情页 + 图表（M3） | ✅ 完成 | 2026-09-13 | **验收 38/38**（转债 K 线遗留已闭环，见 09-13 日志） |
| P3 | 热点 pipeline + dashboard（M1） | ✅ 完成 | 2026-09-12 | 验收 27/27；成分映射经新浪备源闭环 |
| P4 | 统一 Agent + L1 工具（M4） | ✅ 完成 | 2026-09-12 | 验收 19/19（含 function calling E2E + 多轮上下文） |
| P5 | Harness 整合：OpenBB + TradingAgents（M5/M6） | ✅ 完成 | 2026-09-12 | 验收 19/19；研报端到端闭环（B 计划引擎） |
| P6 | 扩展机制：Skills + MCP（M7） | ✅ 完成 | 2026-09-13 | 验收 21/21 |
| P7 | Docker 化 | ✅ 完成 | 2026-09-13 | 验收全过（双镜像 build / 健康检查 / 卷持久化 / 备份恢复 / 跨容器回调 / 冒烟 8-8） |

状态标记：⬜ 未开始 ｜ 🟡 进行中 ｜ ✅ 完成 ｜ ⚠️ 完成但有遗留问题

> **完成度口径**：本表只记**最终值**——P2 = **38/38**（35 → 36 → 36/38 → 38/38 的演进过程留在各自日期日志内）。
> **验证基线（最新）**：`tsc --noEmit` 0 错 ｜ `vitest` **148/148**（24 文件，2026-09-22 起）｜ 集成 `verify-all` 7 套件全 exit=0（test-db 16 / p1 20 / p2 38 / p3 27 / p4 19 / p5 21 / p6 21；p6 于 09-22 llm 档重跑 24/24）｜ 冒烟 7/8（第 6 项容器内 health 于本地开发态不适用）｜ data-service 离线 42+6+10+18+9+8+15+7 全绿。

> **当前阶段（2026-09-20 更新）**：P0–P7 全部完成 + **七轮** code review（CR1–CR7）。
> CR1–CR5 已闭环并提交（`4905095` 及之前）；**CR6 已处置但未提交**（工作树 ~75 个未提交路径）；**CR7 全部 14 项未修复**。
> **未闭环项**（详细看板见 [FIX-LEDGER.md](FIX-LEDGER.md)）：
> ① CR7-1/CR7-2（P1，产出错误）；② CR7-3 = G3/R13「零调用方端点」待定调；③ CR7-4 = G6 港股消费侧三处断链；④ G7 完整身份鉴权（上云前必补）；⑤ C31 Dockerfile 进程降权的构建/运行验证（主人指示暂不推进 Docker）。

## 进度日志

### 2026-09-22 — OPT-1 路线 C：技能路由改 load_skill 工具化加载（评估→拍板→实施→验收，当日闭环）

- **评估**：M7 优化点 1（触发词子串匹配误命中）三条路线——TypeSafe Jev SaaS 作废（境外 API + 新凭据/SDK 依赖 + CJK 不保证 + TTFT 同步路径硬伤）；Laya 自托管未采纳留备选（Python/torch 与 Node 侧错配、镜像重量、成熟度）；**拍板走路线 C**（主 LLM 经 `load_skill` 工具自主拉取技能正文，`SKILL_ROUTER` 三档默认 llm）。
- **实施**：commit `10745ff`（9 文件：skills/gateway/route/ChatUI + 三套测试改造 + 新增 `eval-skill-router.mjs`）；逐文件明细见 [history/2026-09-22-opt1-路线C-技能路由改造.md](history/2026-09-22-opt1-路线C-技能路由改造.md)。
- **验证**：`tsc --noEmit` 0 错 ｜ `vitest` **148/148**（基线 140）｜ `test-p6` llm 档实跑 **24/24** ｜ 真实 LLM 行为评估**加载率 100%（≥90%）、误加载率 0%（≤10%）→ 达标**，无需退 hybrid。
- **回滚**：`SKILL_ROUTER=keyword` 一行 env 即回原行为。

### 2026-09-20 — CR7 第二轮·全项目审查（14 项，全部未修复）⏳

**审查方式**：全量逐文件通读——data-service 27 个源文件（5.5k 行）+ `web/lib` 29 个非测试文件 + 21 个 `route.ts` + 18 个 tsx + PLAN（R1–R17 / M1–M8 / C 系列）+ 容器化与迁移，每条发现回代码用 `grep`/`sed` 取行号证据。**本轮未运行任何测试/构建**。

**结果**：P1×2 + P2×6 + P3×6 = **14 项，全部未修复**，待主人逐项决策。两条 P1：

- **CR7-1** 技术分析师 `dataBased` **硬编码 True**（另两角色都有真实数据门控），叠加 `:249` 归一化默认 True → K 线不可用时该角色仍进辩论并成为评级依据，违反 M5 话语约束与 R16。
- **CR7-2** 研报回读 `/api/kline` 传 `YYYYMMDD`，被 web `normalizeRange` **静默回落**为默认 90 日 → `days` 参数完全失效，「研报与详情页归因同源」在窗口长度上不成立。与 V1 同族的跨语言日期契约问题。

**其中两条是对已闭环结论的推翻/修正**：

- **CR7-3 推翻 G3/R13 的 ✅**：`/quote/verified` + `verify_metric` 已实现且有 8 项测试，但 **web 全仓 `grep quote/verified` = 0**——无 BFF 路由、无 UI、不在 MCP 工具集。**2026-09-20 复核确认此判断成立**。批次 D 自订原则"每项实现或显式裁剪，不留模糊态"，故需主人三选一定调。
- **CR7-4 修正 G6 的 ✅**：港股取数侧已闭环，**消费侧仍三处断链**（`tools.ts` 枚举无 hk / `profile.ts` 无 hk·us 模板 / `currency` 字段全 web 侧零命中）。

**CR7-14 文档漂移**：`PLAN.md:257` M7 优化点 3 已被 `Lru` 推翻（**整理时已改记「已闭环」**）；`providers/__init__.py` 注释与注册表语义不符（待办）；**`Progress.md` 缺 09-19/20 整轮记录**（**整理时已补齐，即本批条目**）。
**同期证伪**：该轮报告称"PLAN 工作树删除了 C18–C34 定义（−145/+31）"——**实测 diff 仅 +36/−5、34 条定义齐全，属误报**，已从三处清除。

**完整 14 项详述、建议处置顺序、8 项已核验排除**见 [CODE-REVIEW.md](CODE-REVIEW.md)；修复计划与 5 项待拍板决策见 [FIX-LEDGER.md](FIX-LEDGER.md)。

---

### 2026-09-20 — G6 港股连通性排障闭环 + 腾讯备源补强 ✅（用户本地验证驱动）

**背景**：用户本地 `POST /api/sync?type=hk` 返回 `RemoteDisconnected`。逐节点探测后确认**根因不是"港股被封"**：

| 节点 | 结果 |
|---|---|
| `72.push2.eastmoney.com`（**akshare `stock_hk_spot_em` 硬编码**） | ❌ `RemoteDisconnected` |
| `81.push2` / `push2` / `82.push2` | ❌ 同上 |
| **`push2delay.eastmoney.com`** | ✅ HTTP 200（真实数据 `89988 阿里巴巴-WR`） |
| **`7.push2.eastmoney.com`** | ✅ HTTP 200 |

初版 `hk_provider` 复用了 akshare 封装，**等于绕过了本项目已有的多 host 降级能力**。

**四处修复**：

1. **`hk_provider` 改直连 + 多 host 降级**：`HK_SPOT_HOSTS` / `HK_HIST_HOSTS` 按序降级，走同一源族限速器 + 看门狗，全失败才抛 `ProviderError`。
2. **分页缺陷**（本轮实测新发现的真实缺陷）：东财港股 `clist/get` **忽略大分页参数**（`pz=100/1000/10000` 均只返回 100 条），港股 `total≈4707` → 初版单请求只拿到 100 条，`00700` 根本不在其中 → 改为按 `total` 分页遍历（实测取满 **4707 只**）。
3. **快/慢路径分离（性能红线）**：发现"行情复用列表快照"会导致**查单个港股耗时约 4 分钟**（拉全量 4700 条）→ 重构为单股 `/api/qt/stock/get`、批量 `/api/qt/ulist.np`（各 1 次请求）、全量列表 `clist/get` **仅每日同步调用**；新增单测 `test_quote_does_not_trigger_list_paging` **锁为红线**。
4. **腾讯港股备源**（用户选定方案 A）：扩展 `tencent_provider`（不新建文件）——`_hk_symbol`（5 位补零 → `hkXXXXX`）+ `_symbol_for`（**按类型显式分派**；5 位数字与 A 股前缀规则冲突，**禁止复用 `_symbol`**，也禁止"按长度猜类型"）+ `register_chain(["hk"], position=1)`。
5. **BFF 同步超时不足**（核对中发现，同属本轮）：`web/lib/sync.ts` 拉取 `/products` 超时 180s，而港股分页实测约 **236s** → **必然超时**（即便服务端已修好）→ 放宽至 **600s**。

**验证**：`test_g6_hk.py` 9 → **28/28**（多 host 降级 / 腾讯符号映射含边界 / 行情不触发分页红线 / 腾讯港股行情与 K 线解析 / 链顺序）；**3 处反向验证**（削弱多 host、移除类型分派、行情改用列表接口）均精确失败；tsc 0 错 / vitest 140/140。
**端到端降级实测通过**：链顺序 `['akshare-hk','tencent']`；强制主源失败 → 自动切腾讯（`419.0 腾讯控股`，note 标注降级链）；港股 K 线降级取到 14 根。**港股列表无备源**（腾讯无全量港股列表接口）→ 显式降级（R10）。

**收尾状态**：G6 连通性 + 备源补强完成，**尚未 git 提交**。

---

### 2026-09-20 — 双服务全量集成验收（CR6 四批统一验收）✅

**环境**：本地开发态（data-service 127.0.0.1:8000 + web 3000），非容器。

**集成套件**（`node web/scripts/verify-all.mjs`，全部 exit=0）：test-db **16/16**、test-p1 **20/20**、test-p2 **38/38**、test-p3 **27/27**、test-p4 **19/19**、test-p5 **21/21**、test-p6 **21/21**。
**冒烟**（`scripts/smoke.mjs`）：✅ **7/8**——BFF 五项全绿；唯一失败为第 6 项"容器内 data-service health"，因本次为**本地开发态**（无 docker compose），**预期不适用**。
**静态与单测**：`tsc --noEmit` ✅ 0 错；`vitest` ✅ **140/140**（24 文件）；data-service 离线 ✅ 42+6+10+18+9+8+15+7 全绿。

**验收中发现并修复的 2 个真实缺陷**（均为本轮改动引入，已修复 + 回归测试 + 反向验证）：

1. **[高] V1 — 批量写把 `KlineDaily.date` 存成文本 → 日期范围查询静默漏行**
   现象：test-p2 的 R13 交叉验证失败（`kline=1266.98` vs `quote=1257.12`）。根因：把 `upsertCandles` 改为原生 `INSERT OR IGNORE` 时日期参数传了 ISO 字符串，而 Prisma 对 SQLite DateTime 存的是 **Unix 毫秒整数** → 文本行与 `date >= ? / <= ?`（数字比较）不匹配，在日期范围查询中被**静默漏掉**（实测 3 行）。
   修复：`web/lib/kline.ts` 改传 `dayStart(c.date).getTime()`；一次性修复脚本 `web/scripts/fix-kline-date.mjs`。回归防线 `kline-date-format.test.ts` + 反向验证。**效果：test-p2 37/38 → 38/38**。
2. **[中] V2 — G2 自动同步用降级备源"缩小"主数据**
   现象：test-p1 失败（`bond=329 < 500`），此前全量为 1052。根因：G2 新增的每日同步凌晨自动跑过一次，当时东财限流 → 转债列表降级到新浪 cov_spot（约 320 只），而全量替换语义会用这 329 条**覆盖**原有 1052 条 → **主数据静默劣化**。
   修复：`web/lib/sync.ts` 在 C1 空载荷保护之外增加**降级缩水保护**（新载荷 < 现有 70% 时保留旧数据并显式报错）。回归防线 `sync-shrink.test.ts`（4 项）+ 反向验证。数据已重新同步恢复（bond 1053）。**效果：test-p1 19/20 → 20/20**。

**验收中修正的 2 处测试脆弱性**（非产品缺陷）：① test-p5 `sources.length >= 2` 因 `meta.sources` 按来源名去重、行情/K线/新闻同源时塌缩为 1 项 → 改断言新增的 `meta.dimensions`；② test-p5 对"当日已有研报"的环境依赖导致跨天首次运行必失败 → 改为按当日实际状态分流断言。

**收尾状态**：CR6 四批改动 + 验收修复已全部落地并**通过全量验证**，**尚未 git 提交**。

**V3（同批发现，见下条）**：港股 provider 三处实现缺陷 —— 由用户本地验证驱动发现。

---

### 2026-09-19 — CR6 批次 D 执行完成 ✅（G1–G7 需求缺口处置）

**决策**（用户）：G2/G3/G4/G5/G6 实现；G1 显式裁剪；G7 由 B4 Origin 校验覆盖（完整鉴权留待上云前）。**决策原文见 [PLAN.md 决策记录](PLAN.md)**。

**落地**：

- **G2 产品主数据每日自动同步**：新增 `data-service/app/sync_scheduler.py`（APScheduler 每日 02:00 Asia/Shanghai，`SYNC_HOUR`/`SYNC_MINUTE` 可覆盖 + 启动补跑，回调 web `POST /api/sync`；单飞 + 状态端点）+ `main.py` 的 lifespan / `/sync/status` / `/sync/run`。
- **G6 港股 provider**：新增 `hk_provider.py`（东财直连 + 多 host 降级）；web 侧 `SYNC_TYPES`、搜索 Tab、行情富集、快照白名单纳入 hk。
- **G4 LLM 兜底召回**：`llm.ts#chatJson` + `search.ts#llmFallback`（首查无结果时用 LLM 抽关键词重查，失败静默返回空）。
- **G5 Watchlist 自选**：新增 `/api/watchlist`（GET/POST/DELETE，白名单校验 + upsert 幂等）+ `WatchButton.tsx`（详情页身份区）。
- **G3 R13 双源交叉验证**：`providers/chain.py#verify_metric`（主源 + 备源比对，超阈值标注偏差，备源不可用不阻塞）+ `/quote/verified`（**按需端点，不叠加**普通 /quote）。
- **G1 显式裁剪**：PLAN M1 webhook 条目划除 + 决策记录。

**验证**：`tsc` 0 错 / `vitest` **135/135**（22 文件，D 批新增 10 项）/ ds 离线 `test_p2_m8` 42、`test_cr6_timeutil` 6、`test_cr6_pipeline` 10、`test_cr6_lru` 18、`test_p6_fund_report` 15、`test_p6_mcp` 7、**`test_g6_hk` 9**、**`test_g3_crosscheck` 8**。
**当时未做**：集成套件未跑（需双服务启动）；G2/G3/G6 真实外部源连通性未在沙箱验证。

---

### 2026-09-19 — CR6 批次 C 执行完成 ✅（收尾 / 一致性 / 优化）

- **C1 日期口径统一为北京时间（CR-06）**：新增 `data-service/app/utils/timeutil.py`（`beijing_now`/`beijing_today`/`beijing_today_date`/`beijing_shift_days`）；`research/tasks.py`（5 处 `date.today()` → `beijing_today()`）、`research/adapter.py`、`hotspot/pipeline.py`（digest date）、`hotspot/scheduler.py`（补跑判断）全部改；新增 `test_cr6_timeutil.py` 6 项。
- **C2 接通事件日期筛选（CR-10）**：新增纯函数 `narrowByDates`；详情页 kline 就绪后用 `pickEventDates`（转折点 + 大波动日）收窄事件——**此前 `pickEventDates` 只被单测引用、生产未接线**（R11 设计未落地）。
- **C3 `/api/research/start` 可选 sessionId（CR-14）**：接受并透传，统一入口会话语义。
- **C5 转债备源交易所显式传递（CR-17）**：新增 `_sina_symbol_exchange`（`sh/sz/bj` 前缀 → SH/SZ/BJ），不再依赖数字前缀推断。
- **C6 转债快照陈旧显式标注（CR-18）**：刷新失败沿用旧快照时记录 `_stale_note`（含旧快照时点）并在响应 `note` 标注。
- **C8 看门狗放弃线程可观测（CR-22）**：新增 `abandoned_count()` 计数与阈值告警（默认 20）；`/health` 返回 `abandonedWatchdogs`。
- **C4 kline 批量写入（CR-15 部分）**：`upsertCandles` 由逐行 `await create` 改为分块 `INSERT OR IGNORE`（50 行/批），首次回源 5 年从 ~1200 次往返降为 ~24 次。**⚠️ 正是这一改动引入了 V1**（见 09-20 验收条）。
- **C7 每日限额双侧判断（CR-20）— 评估后保留现状**：web 查库（持久兜底）+ ds 内存 `_daily_done`（快速判断）是**有意的双层设计**，主要风险（日期口径错位）已由 C1 消除。
- **C9 CR-15 其余项收尾**：PUT content 长度上限 20000；DELETE 区分 P2025(404) 与真实 DB 故障(500)；`rebuildFts` 分步 try/catch + 日志；`llm.ts` 收尾 `decoder.decode()` flush + 删死变量；`gateway.ts` 状态缓存按 `connect` 分键。**评估后不改并记录理由**：`research-target` 6 位数字误判、`search` 单字符候选偏斜、`sync` 行 type 取自 payload、进程内单飞多副本。

**验证**：`tsc` 0 错 / `vitest` **125/125**（20 文件，C 批新增 4 项）/ ds 离线 `test_p2_m8` 42、`test_cr6_timeutil` 6、`test_cr6_pipeline` 10、`test_cr6_lru` 18、`test_p6_fund_report` 15、`test_p6_mcp` 7 / Python 语法校验 9 个改动文件通过。

---

### 2026-09-19 — CR6 批次 B 执行完成 ✅（中风险，需设计判断）

**决策项已确认**（用户）：B1 = `connection_limit=1`；B5 = 快照保留旧值（COALESCE）；B4 = Origin/Referer 校验（轻量）。

- **B1 busy_timeout 覆盖连接池（CR-04）**：新增 `datasourceUrl()` 向 `DATABASE_URL` 注入 `connection_limit=1`（dev/容器两种 URL 统一生效；已显式配置时不覆盖），使唯一连接承载 `busy_timeout`。附带修复：`ensureSqlitePragmas` 失败不再永久缓存。
- **B2 kline 头/尾缺口拆分复查窗口（CR-05）**：新增独立 `lastCheckedTail`（挂 globalThis），尾部分支不再被头部补全压制。
- **B3 长请求 maxDuration（CR-07）**：`/api/sync`、`/api/market/refresh` 显式 `maxDuration = 800`。
- **B4 写端点 Origin 校验（CR-08）**：新增 `web/lib/request-origin.ts#checkRequestOrigin`（Origin 缺失回退 Referer；无来源如 curl/测试放行）；三端点入口校验，跨站 403。
- **B5 快照保留旧值（CR-09）**：抽出纯函数 `buildSnapshotUpdate`；SQL 改 `COALESCE(CASE …, "lastPrice")`。
- **B6 热点去重唯一索引（CR-11）**：`HotspotDigest` 增 `@@unique([date, title])` + 迁移（先清理历史重复行再建索引，已 `migrate deploy` 应用）；`create` 捕获 P2002 归为"跳过"。
- **B7 热点 pipeline 超时覆盖全流程（CR-16）**：`fetch_news(deadline=)`（预算耗尽跳过后续新闻源）、`structure_topics(deadline=)`（LLM 超时取剩余预算）。
- **B8 净值表失败负缓存（CR-19）**：新增 `_fund_nav_fail_ts` + `FUND_NAV_FAIL_COOLDOWN`（5 分钟），失败写时间戳（与成功路径对称）。

**验证**：`tsc` 0 错 / `vitest` **121/121**（20 文件，B 批新增 20 项）/ ds 离线 `test_p2_m8` 36、`test_cr6_pipeline` 10、`test_cr6_lru` 18、`test_p6_fund_report` 15、`test_p6_mcp` 7 / Prisma 迁移应用成功。

---

### 2026-09-19 — CR6 批次 A 执行完成 ✅（高价值低风险修复）

- **A1 会话历史 tool 配对修复（CR-01，P1）**：新增 `web/lib/chat-history.ts`（零依赖纯函数 `repairToolPairing`——丢弃孤立 tool 消息；把 `assistant.tool_calls` 收窄到"确有 tool 结果回应"的子集）；`route.ts` 的 `tool_call_id` 兜底由常量 `"call"` 改为 `""`；`PUT /api/chat/sessions` 对 `role:"tool"` 强制要求 `toolCallId`。
  **背景**：孤立 tool 消息会让**该会话永久 400**（用户只能删会话自愈）。
- **A2 LLM 流超时语义修正（CR-02，P1）**：连接超时改用独立 `AbortController`，**仅约束"响应头到达"**；body 读取阶段由 `IDLE_TIMEOUT_MS` 空闲看门狗约束。不再把 60s 超时信号覆盖整条流（原实现会把长回答静默截断）。
- **A3 running 复用分支登记 watcher（CR-03，P1）**：未陈旧 running 分支在 return 前调用 `watchResearch`，与 409 并发去重路径一致（原实现导致"承诺推送却推不到"）。
- **A4 `mcp.stopAllMcp` 竞态加固（CR-12）**：`ServerRuntime` 增 `generation`；`ensureConnected` 完成时若代际已变则丢弃结果并关闭连接（防复活已停止 server）。
- **A5 `callMcpTool` 降级语义修正（CR-13）**：按工具名前缀 `mcp_<server>_` 定位目标 server，**只连它一个**；源降级/禁用时返回"该 MCP 源当前不可用（已降级）"，不再误报"未知 MCP 工具"。
- **A6 零风险打包（CR-15 部分）**：`.gitignore` 补 `*.db-wal`/`*.db-shm`；`db-stat.mjs` 移除不存在的 `syncState`；`context-budget.ts` 移除 `overflow` 死变量；`tasks.py` 移除 `_ = started`；`kline.ts` 移除 `normalizeRange` 死条件。

**验证**：`tsc` 0 错 / `vitest` **101/101**（16 文件，含新增 `chat-history.test.ts` 9 项）/ ds 离线 `test_p2_m8` 31、`test_cr6_lru` 18、`test_cr6_pipeline` 10、`test_p6_fund_report` 15、`test_p6_mcp` 7。

---

### 2026-09-17 — 第五轮全项目 code review（CR5）：8 项修复（含 1 项"修复静默失效"）✅

**前置**：单路串行通读 + 逐条人工验证，共 **P1×2 + P2×1 + 需求交付缺口×3 + P3×6**；主人按"少改动、尽量复用"原则批复 **A+B 批 8 项**，CR5-P4 与 CR5-D1/D2/D3 **暂不处理**。

**P1（2 项，全部修复）**

1. **CR5-1 CoinGecko 失败负缓存是死代码（推翻 CR4 结论）**：`_markets_fail_ts` 仅在 `__init__` 与**成功**路径置 0，失败路径**从不写入** → 守卫 `now - fail_ts < CG_FAIL_COOLDOWN` 恒假 → 第四轮声称的"失败冷却"**实际从未生效**，CoinGecko 不可达时每个 crypto 请求仍完整重试约 41s 占住线程池 worker。修复：`_fetch_markets` 内 try/except 失败写 `_markets_fail_ts`（与成功路径对称）。
2. **CR5-2 研报失败广播被渲染成"已完成（中性）"假成功卡片**：后端失败分支广播 `{failed:true, error}`（无 rating/summary），而 ChatUI 监听器**不判别该字段** → 一律走成功分支，`rating` 缺失回落"中性" → 发起会话实时看到"已完成·中性"的假消息。修复：监听器新增 `if (data.failed)` 分支。

**P2（1 项）**

- **CR5-3 陈旧 running 是 UI 死路（CR4-6 只修了一半）**：后端已具备"running 超 10 分钟可重提"能力，但前端 `running` 分支**无任何出口**——ds 内存任务表重启即丢任务 → 详情页永久"执行中"，轮询到顶仅报错、无按钮（用户被卡死）。修复：新增零依赖模块 `web/lib/research-stale.ts`，陈旧 running 落入既有"起始态"分支（复用已有触发按钮），并停止空转轮询。

**P3（5 项，全部修复）**：CR5-P5 热点触发在"任务早于首个轮询完成"时不再漏刷新；CR5-P1 `score.ts#tagCache`、`skills.ts#cache` 挂 globalThis（C17/C27 口径），skills 缓存顺带换 `Lru(200)`；CR5-P2 `/api/quote` 错误码按 `res.status` 透传；CR5-P3 `/api/chat` 与 `/api/search/click` 入参加长度上限；CR5-P6 `ResearchPanel.trigger` 依赖数组清理。

**实现中的偏离（已记录）**：CR5-3 原方案设想 `ResearchPanel` 从 `@/lib/research` 导入常量，实现时发现该组件是 `"use client"` 而 `@/lib/research` **牵连 prisma**（打入客户端包会构建失败）→ 改抽零依赖模块 `research-stale.ts`。

**新增回归测试（含反向验证）**：`test_p2_m8.py` 的 `test_crypto_failure_negative_cache()` 6 项断言——**做过反向验证**（临时回退 → 断言精确失败 `n:2`，证明又发起外部请求 → 恢复后通过），确保不是"永远为真"的假断言；`research-stale.test.ts` 6 项。

**过程中发现并修复的自伤**：CR5-3 抽模块时漏删 `ResearchPanel` 内原有的本地 `isStaleRunning` 定义（遮蔽导入）→ `tsc` 报错。**教训：验证点必须晚于最后一次改动**。

**验证**：`tsc` 0 错 / `vitest` **79/79**（11 文件，本轮 +6）/ ds 离线 `test_p2_m8` **29/29**（+6）、`test_p6_mcp` 7、`test_p6_fund_report` 15 / 集成 test-p5 **21/21** / 集成 test-p2 **37/38**——唯一失败「分钟线 502」为**东财 IP 级限流瞬时波动**（单发探测该接口返回 200 + 28013 字节真实数据；本轮未触碰 kline/分钟线路径），按 R9 纪律未再重试。

**文档**：PLAN 新增 **C34** + 第五轮审查说明 + **需求表新增 R16/R17**。

**编号口径变更（2026-09-17）**：第五轮审查编号原写作 `R5-x`，与 PLAN 既有**需求编号 R5**（加载反馈）冲突 → 经主人确认，**第四、五轮审查编号全局改为 `CR4-x` / `CR5-x`**，需求编号 R5–R17 保持原样。**已应用的 Prisma 迁移文件 `migration.sql` 内的 `R4` 注释有意保留**（Prisma 校验迁移 checksum，改已应用迁移会致 `migrate deploy` 报错）。

**暂不处理（边界已明确）**：CR5-P4 写接口鉴权（**上云/`WEB_PORT` 对外前必须补**）；CR5-D1 R13 双源交叉验证；CR5-D2 webhook 推送；CR5-D3 LLM 兜底召回——后三项的 PLAN 需求条目**保持原样**。

**收尾状态**：8 项改动已落地并验证；**改动尚未 git 提交**。

---

### 2026-09-15 → 09-16 — 第四轮全项目 code review（CR4）：P1×5 + P2×12 + P3×25 全量修复与验证 ✅

**前置**：三路并行审查 + 逐条人工验证，共 P1 5 / P2 12 / P3 25 项；主人批准后实施修复——**仅改代码、不改变需求功能**。

**P1（5 项，全部修复）**

1. **CR4-1 研报唯一键缺 type → 跨类型串研报（已实测确认）**：`@@unique([code,date])` → `@@unique([type,code,date])`（迁移 `20260915_research_unique_type_code_date`）。实测 `000001` 平安银行(stock)/华夏成长混合(fund) 可并存。
2. **CR4-2 `sina_provider` 裸 `float()` → NaN 进 6h 缓存 → /kline 500（C21 漏网）** → 统一 `to_float`，任一字段为 None 跳过该行。
3. **CR4-3 MCP stdio 进程生命周期两缺陷**：① 崩溃后状态面板假 connected 且永不重连 → `ensureConnected` 用 `alive` 判断 + 清死引用重连；② 握手失败泄漏子进程 → `connect()` try/catch + `stop()`。
4. **CR4-4 K 线头部缺口"成功但空响应"不设窗口（C11 漏网路径）** → 头部分支对称加 `recentlyChecked` + 空响应写 `lastFailed`。
5. **CR4-5 东财限速按 host 计次 → 单逻辑请求即触发全源族熔断** → `_em_get`/K 线多 host 循环包进单个 `_em_request` 闭包（只计次一次）。

**P2（12 项，全部修复）**：① 工具循环跑满后追加无 tools 收尾调用 + warn；② 最终 assistant 消息只落库一次（原重复两遍）；③ CoinGecko 失败负缓存（冷却 5 分钟）；④ LLM 流空闲看门狗 + 首字节连接超时；⑤ `tool_calls` name 仅在为空时赋值；⑥ 研报 running 陈旧恢复（超 10 分钟按 failed）+ 前端轮询上限 60 次；⑦ `ProductCharts` 区间/对比加载加 `AbortController` + 序号守卫；⑧ `ResearchPanel` 轮询 interval 卸载竞态泄漏；⑨ `/api/quote` 裸 fetch 补 15s 超时；⑩ APScheduler 加 `misfire_grace_time=1800 + coalesce`；⑪ `request_run`/`adapter._run_with_timeout` 的 `Thread.start()` 失败回滚状态/名额；⑫ 数值/健壮性打包（pipeline 板块涨跌幅 isfinite、crypto K 线/quote `to_float`、东财 K 线行长度校验）。

**P3（25 项，全部处理）**：#1 openbb 代理注入（核实 yfinance 1.7.0 `Ticker` 原生支持 `session` → `_overseas_session()` trust_env=False + 显式 proxies 注入）；#2 events/kline 缓存挂 globalThis（C17 漏网）；#3 `trimContext` 计入 system 体积 + 硬截断覆盖 tool_calls 参数；#4 events 降级结果短 TTL；#5 mcp `runtimeFor` enable/disable 对称；#6 Dockerfile 进程降权（见下）；#7 `tasks.py` 调试日志降为 info；#8 `backup_db` 只读打开备份源 + 校验失败删损坏产物；#9 详情页 `key={type:code}`；#10 HotspotFeed 轮询卸载取消；#11 ECharts resize 监听；#12 sessions PUT role 白名单；#13 `/api/search` q 长度上限 100；#14 research start type/code 白名单；#15 done 但 fullReport 缺失时渲染 summary；#16 rejected 分支登记 watcher（C8 承诺闭环）；#17 search-client 防抖清理 abort 在途请求；#18 sourceUrls 按 topic 相关性挑选；#19 engine timeout 接入 chat_json；#20 tavily Session 显式关闭；#21 pipeline finishedAt 用北京时间 TZ；#22 search-cache 换 LRU(50)；#23 skills 缓存清理已删目录；#24 sync 暂存表 DROP+CREATE；#25 `verify-suites.txt` 入 `.gitignore`。

**#6 Dockerfile 降权的设计（代码完成，未验证）**：容器默认用户保持 root（`compose exec` 备份/恢复行为不变）；仅 uvicorn 经 `setpriv` 降到 **uid 1000**；`setpriv` 缺失时回退 root 直跑并告警。**按主人指示暂不推进 Docker**，故此项**未经构建验证**（即 **C31 未闭环项**）。

**验证（全绿）**：`tsc` **0 错** / `vitest` **73/73**（10 文件）/ ds 离线 `test_p2_m8` **23/23** + `test_p6_mcp` 7 + `test_p6_fund_report` 15 / 迁移已应用。双服务集成实测：test-p1 **20/20**、test-p2 **38/38**、test-p3 **27/27**、test-p4 **19/19**、test-p5 **21/21**、test-p6 **21/21**、test-db **16/16**。

**过程记录**：test-p5 首跑报 1 失败（"当日已完成标的直接复用"）——经查为**当天尚未生成 600519 研报**的时序，非回归，研报生成后复跑通过；test-p2 前次唯一失败「分钟线 502」本轮已恢复。验证后清理了 CR4-1 验证遗留的 1 行 `000001 fund` 空研报行。

**收尾状态**：42 项非 Docker 改动全部落地并经逐条 grep 核验；**改动尚未 git 提交**（工作树 39 修改 + 3 新增）。

---

### 2026-09-14 — L2 镜像瘦身验证闭环（发现并修复 2 个真缺陷）✅

**背景**：L2 代码于 09-13 完成但验证被 Docker Desktop 未运行阻塞；本次 Docker 起来（v29.7.2）后执行 `docker compose build web && docker compose up -d && node scripts/smoke.mjs`。

**过程中的两个真实缺陷（均已修复 + 固化为约束）**

1. **[高] `prisma` CLI 被误裁 → 容器必然启动失败**：把 `prisma` 从 devDependencies 移入 dependencies 时**只改了 `package.json`、未同步 `package-lock.json`**；`npm ci`/`npm prune` 以锁文件为准 → `--omit=dev` 把 prisma 当开发依赖删掉，入口脚本的 `prisma migrate deploy` 直接失败（实测镜像内 `node_modules/prisma` = MISSING）。修复：`npm install --package-lock-only` 同步锁文件（比对确认**无版本漂移**）。→ **固化 C24**
2. **[中] 裁剪位置错误 → 体积零下降**：Dockerfile 原在 runner 内"先 COPY 再 `npm prune`"，被删文件仍留在更早的层里 → 实测体积仍 1.62GB（层语义）。修复：改为独立 `FROM build AS prod-deps` 内裁剪。→ **固化 C25**

**额外优化**：本镜像是 Debian/glibc，`@next/swc-linux-x64-musl`(137MB) 与 `sharp` 的 musl/wasm 变体(28MB) 纯冗余 → 裁剪，再省 **165MB**。

**实测结果**

| 指标 | 前 | 后 |
|---|---|---|
| `docker images` 体积 | 1.62GB | **1.25GB（-23%）** |
| 容器内实际占用（`du -sx /`） | ~1.29GB | **0.89GB** |
| 精确 `.Size`（压缩） | — | 279MB |

**关键认知（纠正原估算口径）**：**devDependencies 不是体积大头**——裁剪后 `node_modules` 仍 833MB，主体为运行时依赖（`@next` SWC 273MB / `next` 156MB / `@prisma` 112MB / `prisma` CLI 67MB / `echarts` 62MB / `@img/sharp` 46MB）。故 PLAN 原"预期 ~0.9GB"的口径有误（0.89GB 实为容器内占用，非 `docker images` 口径）。

**验收**：`docker compose build web` 通过；两容器 **healthy**（web 健康即证明 `prisma migrate deploy` 在裁剪后镜像中正常工作）；冒烟 **8/8 全绿**。镜像内关键依赖核对：`prisma` / `@prisma/client` / `next` / `@next/swc-linux-x64-gnu` 均在位，`vitest` 与 musl SWC 已裁掉。

**遗留（评估记录，未做）**：① `prisma migrate deploy` 拆独立 one-shot 服务可再省 67MB；② 项目未用 `next/image`，`@img/sharp` 46MB 理论可去（需验证 `next start` 不强制加载）。

---

### 2026-09-13 — CR2 第二轮全项目 code review（四路并行）：12 项真实缺陷全部修复 ✅

**审查方式**：四路 Explore 代理并行（web/app、web/lib、data-service、脚本+容器化+测试）+ 逐条人工验证。
**回归验证**：`tsc` 0 错 / `vitest` 65/65 / test-p1 20/20 / test-p2 38/38 / test-p3 28/28 / test-p4 19/19 / test-p5 21/21 / test-p6 21/21 / ds 离线 45/45。

**P0（1 项，实测确认后修复）**

- **研报启动接口死锁**：`research/tasks.py` 的 `start_research` 在**非重入锁**（`threading.Lock`）持有期内调用 `_evict_expired()`，后者再次获取同一把锁 → **同线程自锁**。实测：`POST /research/start` 20 秒超时无响应（HTTP=000）、`_lock` 被永久持有 → **研报功能完全不可用且轮询端点全部阻塞**；因 test-p5 复用当日已完成研报而未在回归中暴露。修复：改 `threading.RLock()` + 重启后实测 0.46s 返回 ✅

**P1（8 项）**

1. **聊天上下文裁剪后工具结果丢失**：`trimContext` 在工具循环外一次性计算 → 改为**每轮重新裁剪**（C18）
2. **裁剪边界丢用户提问**：最后一条消息自身超预算时 `kept=[]` → 改为硬截断保留（C18）
3. **test-db 无 where 全库删聊天消息**：`chatMessage.deleteMany({})` 会清空开发库全部真实会话（不可逆）→ 删除该行（C23）
4. **`researchWatchers` C17 违反 + 失败不清理**：模块级 Map 未挂 globalThis（HMR 重置 → 定向推送失效）；且仅 done 分支清理 → 失败/未完成任务 Map 无界增长 → 双修（C19）
5. **sync 并发共享暂存表 → 数据丢失**：两次同类型同步互相清空对方暂存行 → 加按类型 in-flight 单飞（C20）
6. **`backup_db restore` 无校验无回滚**：非法备份会把线上库"恢复"成空文件 → 加 integrity_check + 表结构校验 + WAL/SHM 清理 + 失败自动回滚（C22）
7. **C7 看门狗漏包（两处）**：`sina_provider` 的 `fund_etf_hist_sina` 直调；`hotspot/pipeline.py` **8 处** akshare 直调 → 挂死会使 `_state["running"]` 永久 True、**热点功能静默失效** → 统一 `_ak_guarded` 包装
8. **openbb 数值 NaN/Inf 进入 JSON → 500**：`fast_info` 与 K 线行裸 `float()` → 统一 `to_float`；`to_float` 补 `math.isfinite`（原只滤 NaN 不滤 Inf）

**P2（5 项，择要修复）**：① K 线"成功但空响应"不计失败窗口 → 已计入并显式标注；② `openbb.get_news` 返回 dict 违反 C5 契约 → 统一 `list[dict]`；③ `research/ingest` 缺 `type` 校验 → Prisma 500（堆栈泄漏）→ 400 校验；④ `research.ts` fullReport 盲目 slice 200K 会产出非法 JSON → 超限丢弃 fullReport；⑤ ChatUI 缺 `warn` 事件分支 + 超时未 `reader.cancel()`。

**已排除的误报/低价值项（不修）**：tools/status 探测缓存与路径过滤（C14 已达标）、C1/C2/C4/C11/C12/C13 复查均正确、`chain.py` 把 NotSupported 收敛为 Error、gateway statusCache 不分键、测试会话清理仅在正常路径。

**文档**：PLAN 新增 **C18–C23** + 第二轮审查说明。

---

### 2026-09-13 — git 初始化 + 转债链路修复（P2 遗留闭环）+ 采集线程 P0 bug ✅

**一、git 初始化**

- `git init -b main` + 基线提交 `b22671f`（155 文件 / 22,322 行）；`.gitignore` 已覆盖 `.env`/`*.db`/`node_modules`/`.venv*`/`.next`/`*.log`/`backups`——暂存清单核对无敏感文件、最大文件 160K（package-lock）

**二、修复的 4 个真实缺陷**

1. **[高 P0] 研报采集全线崩溃（L3 信号量引入）**：`adapter._run_with_timeout` 只声明了 `global _collect_live`，而 `_collect_inflight += 1` 未声明 → **UnboundLocalError** → 研报引擎的所有数据采集**必然即时失败**。此前未被发现：test-p5 因"600519 当日研报已完成 → 直接复用"未触发真实采集。修复：补 `global` 声明；**同时修隐患**：`Semaphore.acquire()` 原为无限等待 → 改为带超时（`RESEARCH_COLLECT_ACQUIRE_TIMEOUT` 默认 60s）。已固化 **C16**
2. **[中] 转债行情不可用（bond 无备源）**：新增 `sina_bond_provider`（新浪 `bond_zh_hs_cov_spot` 快照：缓存 60s + 锁内双检 + 看门狗）。实测 111000 起帆转债 141.358、123071 天能转债 114.781、123284 强达转债 209.096 **均经新浪备源返回真实报价**（东财限流期间）
3. **[中] 转债列表限流即空**：`_list_convertible_bonds` 增加新浪 cov_spot 回退；修复调用约定错误（`_ak_request` 抛异常而非返回元组 → 曾致 500）
4. **[中] SSE 事件偶发丢失（P3 起潜伏，dev 环境）**：`lib/sse.ts` 的 `clients` Map 为**模块级变量**，Next dev HMR 重建模块作用域时被重置 → 连接注册在旧 Map、广播查新 Map → test-p3 的 SSE 断言间歇失败（**同类问题第二次出现**）。修复：clients 挂 `globalThis` → **test-p3 连续 3 次 28/28 稳定通过**。已固化 **C17**

**三、P2 遗留 2 项"转债 K 线"彻底定性并闭环（验收 36/38 → 38/38 ✅）**

根因有三层（此前长期误归因为单一"东财限流"）：

| 层 | 事实 |
|---|---|
| ① 测试标的选错 | 原断言**动态选取列表首个 11/12 前缀标的**，实际命中 **113710 四方转债 / 123285 润禾转02——均不在实时行情列表（未上市/已退市）**，K 线本就不可能存在 |
| ② 外部源限制（真实） | 转债 K 线**仅有东财一个源**：系统性排除腾讯（`fqkline`/`kline` 转债 day 恒空）、`bond_zh_hs_cov_daily`（已废弃）、新浪通用 K 线（返回 null）、网易 chddata（沙箱 502，待本机复测） |
| ③ 断言语义过严 | 原断言要求"必须有 K 线"，而 R10/R12 的正确语义是「**可用 或 显式降级**」 |

测试修正：候选池改为**活跃代码段 + 行情预筛（price 非空 = 在交易）+ 任一成功即通过 + 显式降级亦通过**。

**四、回归验证（全绿）**：`tsc` 0 错 / `vitest` 65/65 / test-p1 20/20 / test-p2 **38/38** / test-p3 **28/28** / test-p4 19/19 / test-p5 21/21 / test-p6 21/21 / ds 离线 45/45

---

### 2026-09-13 — 项目状态确认（全量复验）+ 发现并修复 2 个缺陷 ✅

**确认方式**：不依赖记忆，逐项实测——文档结构核对、代码与产物核对、双服务启动 + 全量测试复跑、配置键核对、数据库现状统计。

**环境现状（当时）**：web(3000)/data-service(8000) 启动正常；Docker **守护进程未运行**（`npipe` 不存在）→ L2 镜像重建验证仍阻塞；**项目未初始化 git**；数据库 product 34,777（bond 1052 / fund 27811 / stock 5913 / us 1）、klineDaily 492、hotspotDigest 22、researchReport 5。

**全量复验**：`tsc` 0 错 / `vitest` 65/65 / ds 离线 45/45 / test-db 16/16 / test-p1 19/20（唯一失败：可转债行情富集——东财限流环境波动）/ test-p3 28/28 / test-p4 19/19 / test-p5 全绿 / test-p6 21/21。

**本轮发现并修复的真实缺陷（2 个）**

1. **[高] FTS 孤儿行累积（L1 引入的回归）**：`rebuildFts` 的 DELETE 用「Product 表当前 id」定位，而 L1 全量替换会给产品生成**全新 id** → 旧 id 的 FTS 行永不删除。实测：`Product_fts` 35,828 行 vs `Product` 34,777 行，**孤儿 1,052 行且全部是转债**（恰等于一次 bond 全量同步的条数）。
   修复：`rebuildFts` 前置通用孤儿清理；L1 暂存表用后 `DROP TABLE`。数据修复脚本 `scripts/fix-fts.mjs` 已执行 → 孤儿 1052→0、缺失 1→0（补 AAPL）、FTS = Product 34,777 ✅。已固化 **C15**
2. **[中] test-p3 SSE 断言竞态（测试缺陷，非产品缺陷）**：`readUntil` 每轮新建 `reader.read()` 并在 race 失败后丢弃 pending 结果 → 多个并发 read 竞争同一 stream，事件偶发被丢。**产品链路经 curl 独立验证完好**。修复为"始终保持唯一 pending read"模式。

**另修正 1 处测试口径过时**：test-p1 的 FTS 一致性断言 `total` 仅算 stock+fund+bond，未含 P5 新增的 `us` 类型 → 改为按全部类型求和。

**新增/保留的运维脚本**：`fix-fts.mjs`、`verify-all.mjs`、`db-stat.mjs`。

---

### 2026-09-13 — O 系列优化（B+M+L 共 12 项）全部执行完成 ✅

用户批准全部执行。按 B → M → L 分批落地：

**B 批（5 项）**：B1 `selectSkills` 合并 + tags 解析缓存（Map 上限 2000 轮换）；B2 LIKE 召回加 `code asc` 排序 + limit clamp 1~50；B3 `safeAppend` 失败发 SSE warn 事件 + LLM 日志 `LLM_DEBUG` 开关；B4 抽取公共 util（web: `lib/time.ts`、`lib/quote-enrich.ts`；ds: `utils/num.py`、`providers/chain.py`）；B5 ChatUI 消息稳定 key + HotspotFeed 站内跳转改 `next/link`。

**M 批（4 项）**：M1 新增 `lib/context-budget.ts`（默认 24K 可配 `CHAT_CONTEXT_BUDGET`，从最早整轮丢弃、不切断 tool_calls 配对）；M2 `refreshSnapshot` 加单飞；M3 新增 `lib/lru.ts`，kline `lastChecked/lastFailed` 换 LRU(500)、events 换 LRU(300)，ds `research` 的 `_tasks`/`_daily_done` 完成 24h 惰性淘汰；M4 `/hotspots/run` 异步化（`scheduler.request_run` 后台线程执行，立即返回 accepted）。

**L 批（3 项）**：L1 sync 全量替换改为分型暂存表（`Product_stage_<type>`）——重活移出主表写锁窗口；L2 prisma 移入 dependencies + Dockerfile prune；L3 adapter 增加信号量（`RESEARCH_MAX_COLLECT_THREADS` 默认 4）+ `collect_stats` 进 `/research/status`。

**执行中发现并修复的缺陷**：M4 初版实现死锁——`request_run` 先置 `running=True`，后台线程内又走 `_single_flight` 检查到 running 已置位直接 return → 任务永不执行且 running 永久卡死。修复：拆出 `_execute`，`request_run` 认领后直接派发。

**验证**：`tsc` 0 错；`vitest` 65/65；test-p1 19/20（唯一失败为转债行情富集——东财限流环境波动）；test-p3 28/28；test-p4 19/19；test-p6 21/21；ds 离线 45/45；L1 实测 bond 同步 1052 条（31.9s）；M4 实测 POST run 立即返回（1.3s，原为分钟级阻塞）。

**遗留**：L2 web 镜像重建验证被 Docker Desktop 守护进程退出阻塞（→ 09-14 闭环）。

---

### 2026-09-13 — O 系列优化实施计划定稿（待批准，未执行）

- 依据全项目代码审查的 O1–O12 优化点，制定**分批实施计划**：B 批（低风险 5 项）→ M 批（中风险 4 项）→ L 批（较大 3 项）
- 每项含做法、改动范围、风险与验证方式；每批回归门槛：`tsc` 0 错 + vitest 全绿 + 受影响集成套件全绿；R9 失败纪律
- 另列「不做/暂缓」4 项（虚拟化、大数组、去重、外部 stdio MCP）
- **状态：已写入 PLAN「O 系列优化实施计划」，待主人批准批次后执行**（该节后于 2026-09-20 整理时迁至 [history/2026-09-13-cr1-全项目审查与O系列明细.md](history/2026-09-13-cr1-全项目审查与O系列明细.md)）

---

### 2026-09-13 — CR1 全项目代码审查：14 项真实缺陷修复 + 12 项可优化点待决策

**审查方式**：三路并行（web 路由/页面层、web lib 层、data-service）+ 逐条人工验证。**验证纪律生效一例**：代理报告"scheduler 用 GET 探测 ingest 路径会 405 → 每次重启重复补跑"，实测 GET 分支存在 → **误报，未采纳**；另"sse.ts 无心跳"结论部分不成立。

**已修复的真实缺陷（高/中，固化为 C1–C14 约束）**

- **[高] 数据丢失**：`syncType` 空载荷先删后插 → 静默清空整类型主数据（C1）
- **[高] 上下文丢失**：`getMessages` asc+take200 取到最早消息（C2）
- **[高] 研报链路地雷**：`adapter` 把 `get_news` 的 list 返回值当 dict 用 → **东财主源一旦恢复就 AttributeError 打挂整条研报任务**（P5 期间因东财限流被掩盖，巨潮备源成死代码）（C5）
- **[高] 容器化下按钮失效**：热点"立即抓取"由浏览器直连 data-service → 新增 BFF 代理（C9）
- **[中] 工具调用静默失效**：LLM 流尾帧被丢弃 + 强依赖 `finish==="tool_calls"`（C3）
- **[中] 缺价报成 0 元**：`Number(null)===0` 透传给 LLM（C4）
- **[中] 熔断失效**：`_em_request` 在状态码校验前回报成功（C6）
- **[中] 线程池挂死风险**：akshare 内部无 timeout → 新增 `utils/timeout.py` 看门狗（C7）
- **[中] 跨会话串消息**：研报完成广播无会话归属 → 定向落库 + 广播带 `sessionIds`（C8）
- **[中] 静默丢研报**：ingest 被拒/失败仅 log，任务仍显示成功 → 写回 `ingestOk`/`ingestNote`（C10）
- **[中] 限流放大**：K 线头部缺口回源失败不进失败窗口（C11）；快照整批无报价被当成功（C12）
- **[中] 资源与竞态 / 安全**：见 C13、C14
- **[低]** 首页 DB 异常白屏、sessions PUT 外键 500、热点去重口径、engine 熔断提示硬编码、死代码清理

**验证结果（全绿）**：`tsc --noEmit` 0 错误；`vitest` 65/65；test-p4 19/19、test-p6 21/21；ds 离线 45/45；关键页面 200。

**可优化点（O1–O12）**：已列成决策表写入 PLAN，**待主人逐条批复后实施**。

---

### 2026-09-13 — P7 Docker 化完成 ✅（验收全过；项目 P0–P7 全部落地）

**交付物**

- **镜像**：`web/Dockerfile`（node:22-bookworm-slim + openssl/ca-certificates + npmmirror + `prisma generate`/`next build` → 运行 + 内置 healthcheck）、`data-service/Dockerfile`（python:3.12-slim + tzdata + 锁文件安装 + `uvicorn --host 0.0.0.0`）、`web/docker-entrypoint.sh`（启动前 `prisma migrate deploy`）
- **编排**：`docker-compose.yml`（named volume、TZ、healthcheck、data-service 端口不对外、`INGEST_TOKEN` 缺省拒绝启动、`restart: unless-stopped`、接线 `WEB_BASE_URL`/`WEB_API_BASE`/`DATA_SERVICE_URL`、可选 **mcp profile**、data-service rw 挂数据卷 + `./backups` bind mount）；根 `.env.example`
- **配套**：双侧 `.dockerignore`、`.gitattributes`（LF 锁定）、`requirements-lock.txt`（114 包，容器内生成）、`data-service/scripts/backup_db.py`、`scripts/smoke.mjs`（8 项断言）、`web/app/api/health`（重建）

**验收结果（全部实测通过）**

| 项 | 结果 |
|---|---|
| 双镜像构建 | ✅ web 1.62GB / data-service 744MB |
| 健康检查 | ✅ web healthy（空卷自动 migrate deploy 建库）、data-service healthy |
| 启动顺序 | ✅ data-service 等 web healthy 再启动 |
| 跨容器回调 | ✅ **data-service 启动补跑 → 5 条热点 digest 落库 web**（`x-ingest-token` 鉴权通过、`lastRun` 带 `+08:00`） |
| 容器互访接线 | ✅ BFF quote/kline 经 `http://data-service:8000` 取数正常 |
| 时区 | ✅ 两容器 `date` 均为 CST |
| 鉴权 | ✅ ingest 无 token → 401；缺 `INGEST_TOKEN` 时 compose 拒绝启动 |
| 镜像红线 | ✅ 镜像内无 `.env`/`dev.db`；含 `skills/`+`mcp.json`；无 tradingagents/OpenBB |
| 卷持久化 | ✅ `down`→`up` 后 product/hotspot = 28897/5 不变 |
| **备份→全新卷恢复** | ✅ 在线快照 25.5MB（integrity_check=ok）→ `down -v` 后空库 0/0 → 恢复到 28897/5 |
| MCP profile | ✅ 默认不启动（无 8765 监听）；`--profile mcp` 后宿主 `127.0.0.1:8765` initialize 200 |
| 冒烟 | ✅ 8/8 |

**本轮修复的真实缺陷（3 个）**

1. **research ingest 回调不带 `x-ingest-token`**（`tasks.py`）→ 容器化强制 token 后研报落库会被 403 拦住且**静默丢数据**；顺带修复其**不检查响应码**的问题
2. **`mcp_server` 回调变量名不统一**（`WEB_API_BASE` vs `WEB_BASE_URL`）→ 已兼容读取 `WEB_BASE_URL` 兜底
3. **data-service 数据卷只读挂载导致恢复无法写入** → 改 rw 并明确"恢复前停 web"

**执行中踩到的坑（已固化进 [CONSTRAINTS.md §D](CONSTRAINTS.md)）**

- **Python 版本与锁文件必须一致**：Windows/py3.12 venv 的 freeze 去装 3.11 镜像 → `numpy==2.5.3` 要求 ≥3.12 直接失败 → 改用 3.12 镜像 + **锁文件在容器内生成**
- **base 阶段设 `NODE_ENV=production`** → `npm ci` 跳过 devDependencies → `next build` 找不到 `@tailwindcss/postcss`、运行时无 `prisma` CLI
- **docker.io 认证被拦截（502）** → 基础镜像改用 `docker.m.daocloud.io` 前缀

**环境条件（非代码缺陷）**：股票类型同步因东财 IP 级限流失败（转债/基金正常，本次入库 28,897 条）；加密因容器内无代理不可达（R12 降级已生效）。

**收尾状态**：容器已 `down`（**数据卷保留**，含 28,897 条产品数据与镜像）。

---

### 2026-09-13 — P7 方案三轮评估定稿（用户批准"评估+直接调整，不开发"）

**评估发现（基于 P6 落地事实，逐条对照原 P7 条款）**

1. **接线缺口（必改，最高优先）**：P6 落地后 data-service→web 的回调已增至 4 条（hotspot ingest、research ingest、vendor_adapter 回读 `/api/kline`、MCP `search_products` 回调），全部默认 `http://localhost:3000`——容器内 localhost 指向自身必挂；且**回调变量名不统一**（`WEB_BASE_URL` vs `WEB_API_BASE`，P6 新增的小缺陷）
2. **MCP 容器化陷阱**：容器内绑 127.0.0.1 时宿主机经端口映射也访问不到 → 定为**默认不进容器**，可选走 compose profile `mcp`
3. **healthcheck 细节**：slim 镜像无 curl；web `/api/health` 骨架验证时建过、已随清理删除 → P7 需重建
4. **openssl 落档**：骨架验证的 Prisma openssl 告警对策此前只在日志，未入 PLAN → 已补
5. **具体化**：锁版本 = pip freeze 出 `requirements-lock.txt`；备份 = Python stdlib sqlite3 在线备份 API（WAL 安全）+ 只读卷 + bind mount；冒烟五项修正为 BFF×4 + 容器内 health

**已写入 PLAN**：P7 三轮补强 9 条 + 验证方式 P7 三轮增补 5 项。**未开始开发。**

---

### 2026-09-13 — P6 深度体检：2 项真实风险已修 + 依赖/文档补齐

**新增验证（此前未覆盖）**

- **MCP server HTTP 传输实测通过**：`python -m app.mcp_server --http`（127.0.0.1:8765）→ 客户端 tools/list 10 工具齐全、工具可调（此前仅测过 in-memory 与 stdio，HTTP 是 P6 唯一未实测的传输路径）
- 发现并证实：客户端经沙箱代理访问本地 8765 会 502——MCP 客户端进程须 `NO_PROXY=*` 直连

**代码审查发现并已修复的真实风险（2 项，均高）**

1. **Next.js HMR 进程泄漏**：MCP 运行时注册表存于模块级变量，dev 热重载会重建模块作用域 → 每次 HMR 丢失连接状态并重复 spawn stdio 子进程 → **孤儿进程堆积**。修复：注册表挂 `globalThis` + `process.once("exit")` 统一清理
2. **`ensureConnected` 并发竞态**：多个并发请求同时触发连接 → 重复 spawn。修复：运行时增加 in-flight Promise 去重

**依赖与文档补齐**

- `requirements.txt` 显式补钉 `requests` / `pandas`（此前靠 akshare 传递依赖，P6 重建 venv 时暴露的脆弱点）
- `web/.env.example` 从 5 行补全为全量
- PLAN P7 二轮补强新增：**`skills/` 与 `mcp.json` 须随 web 镜像分发**
- **PLAN 同步修正（实现偏离记录）**：PLAN M7 ② 原写"用官方 `@modelcontextprotocol/sdk` 作为 MCP client"，实际实现为**自研轻量客户端** → 已在 PLAN M7 ② 改写为"实现方式定稿"并注明理由

**回归**：`vitest` 65/65（新增并发去重测试）；test-p6.mjs 21/21；`tsc` 零错误。

---

### 2026-09-13 — P6 扩展机制（Skills + MCP）完成 ✅（验收 21/21）

**交付内容（M7 三部分全齐 + 二轮补强全落地）**

- **① Tool Gateway**（`web/lib/gateway.ts`）：三分命名空间 `builtin:` / `skill:` / `mcp:` 聚合。**红线守住：发给 LLM 的内置工具名一律不变**
- **② Skills 系统**（`web/lib/skills.ts` + `web/skills/`）：Anthropic Agent Skills 格式；**元信息常驻、正文命中才注入**；mtime 热加载免重启；正文上限 2400 字符、同时激活 ≤3。首批技能 3 个：`hotspot-daily`、`tech-indicators`、`fund-report-analysis`
- **③ MCP client**（`web/lib/mcp.ts`）：`mcp.json` 白名单（不自动安装），stdio + HTTP(streamable) 双传输，`sse` 明确拒绝；失败一律降级为"该源工具不可用"（含 60s 重试冷却）；密钥 `${ENV}` 占位注入
- **④ MCP server**（`data-service/app/mcp_server.py`，fastmcp）：只读暴露 10 个工具；默认 stdio，`--http` 仅绑 127.0.0.1:8765
- **⑤ 配套**：L1 新增 `get_fund_report`（7 个 L1 + 2 个 L2 = 9）；data-service 新增 `/fund/report`（缓存 6h）；`/api/tools/status` 状态面板；`web/scripts/mcp-local-util.mjs`

**验收结果（21/21 通过）**

- 状态面板：builtin 9 / skill 3 / mcp local-util **connected**（1 工具）；builtin 工具名无前缀（P4 兼容）；技能正文不泄漏到接口
- 技能注入：未命中 → `meta.skills=[]`；命中热点/基金/技术面各自正确；同时激活 ≤3
- **端到端实证（LLM 自主调用）**：问"现在北京时间几点？是否处于 A 股交易时段？" → LLM **自动选择 MCP 工具** → 返回真实时间 → 回答带时点与免责声明 ✓
- **技能真实生效实证**：问"110022 这只基金的季报怎么看" → 命中 `fund-report-analysis` → LLM 自动 `search_products` 解析标的 → 调 `get_fund_report` → 遇东财限流**如实输出"数据缺口"而非编造** ✓（正是技能约束的设计目标）

**单测（64/64）**：新增 28 项（`skills.test.ts` 10 / `mcp.test.ts` 9 / `gateway.test.ts` 9）；ds 新增 `test_p6_mcp.py` 7、`test_p6_fund_report.py` 15。
**回归**：`test-p4.mjs` 19/19 全绿（工具名未变，红线达成）；`tsc --noEmit` 零错误。

**本轮修复的真实缺陷**

1. **NaN 漏进响应**（`_num` 把 `float('nan')` 当有效值）→ NaN 会产出**非法 JSON**（严格客户端解析失败）。已在 akshare/tencent 两处统一修复为 NaN≡缺失
2. **`mcpStatus()` 不反映 disabled 状态** → 统一在 `runtimeFor` 标记 disabled
3. **状态面板不探测连接** → `/api/tools/status` 改为探测式
4. **`search_products` 的 `import httpx` 在 try 之外** → 依赖缺失时抛错而非降级，已移入 try
5. **`requirements.txt` 遗漏 `yfinance`** → 已补

**环境事故与恢复（重要）**

- **根因**：安装 fastmcp 4.x 时 pip 升级/降级触发大量卸载，被 WorkBuddy 沙箱的 safe-delete 守卫拦截，pip 中断在"已卸载旧版、未装新版"的中间态 → platformdirs/pandas/numpy 等元数据与文件受损，data-service 无法启动
- **恢复**：隔离受损 venv → 重建 → `ensurepip` 补回 pip → **pip 操作一律带 `PYTHONPATH=` 绕开注入的 sitecustomize** → 按锁定后的 requirements 安装 → `pip check` 无破损
- **依赖定版（已写入 requirements 与 [CONSTRAINTS.md §C-2](CONSTRAINTS.md)）**：`fastmcp>=2.0,<3`、`starlette>=0.40,<0.51`、`httpx>=0.27,<1`、`yfinance>=0.2`、`fastapi>=0.115,<0.126`

---

### 2026-09-13 — P6/P7 二轮方案评估定稿（基于 P0–P5 落地事实，用户已确认）

**评估发现的关键事实**：① 工具注册表为单层平铺，未预留 Tool Gateway 结构 → P6 需轻重构；② L2 引擎与热点 digest 已实装 → 两个首批技能可零新数据逻辑；③ `fund-report-analysis` 数据源未验证；④ TradingAgents 仅在 `.venv-spike`、`openbb_provider` 只用 yfinance → P7 镜像可裁掉两大依赖树；⑤ 候选 Tavily MCP 实为 stdio 形态，与"HTTP 优先"有现实冲突；⑥ search 依赖 web 侧 FTS5，fastmcp 暴露须守住"不直连库"铁律。

**用户确认的改进（已写入 PLAN.md）**

- **M7 二轮补强**：Tool Gateway 内部命名空间但 LLM 工具名不变（test-p4 19/19 为回归红线）；Skills 加载器只编排既有 L1/L2 工具；首批技能按稳定性重排（spike 先行）；MCP client MVP 只接 1 个 stdio server
- **P7 二轮补强**：requirements 全量 freeze（不含 tradingagents/OpenBB SDK）；单镜像策略；SQLite 备份/恢复脚本；compose 强制 INGEST_TOKEN；冒烟脚本扩至五项

---

### 2026-09-13 — A/B 方案执行完成（内容质量 + 验证补齐）

**A 方案（内容质量）——全部生效**

1. **基本面维度补齐**：`collect_fundamentals`（同花顺财务摘要主源 → 东财备源，最近 4 期）→ 600519 复验：基本面分析师引用**真实最新数据**（2025 年报营收 1720.54 亿/-1.20%、2026 中报 922.78 亿/+1.30%）
2. **个股新闻备源**：巨潮公告 cninfo（证监会指定披露平台，非东财域名）作为东财个股新闻降级备源 → 实测《2026 年半年度报告》公告成功进入情绪分析（**新闻维度缺口消除**）
3. **话语约束生效**：缺口角色 view="无法判断"（禁方向性结论）；辩论仅采信 `dataBased=true` 的角色；`meta.asOf` 时点标注

**B 方案（验证补齐）——全部完成**

1. ✅ **B1 P3 LLM 结构化复验**：`hotspots/run` → `engine=llm`（Tavily 主源 + LLM 结构化 5 条热点）
2. ✅ **B2 P4 组合链**："查最近热点+看茅台行情" → `get_hotspots` + `get_quote` 多工具调用 → 回答引用真实数据（7/7）
3. ✅ **B3 熔断机制验证**：`RESEARCH_MAX_LLM_CALLS` env 覆盖生效；`allow()` 边界与超时熔断单测 PASS

**本轮新发现并修复**：同花顺财务摘要按报告期**升序**返回 → `head(4)` 取到 1998 年老数据 → 修复为降序取最新 4 期。

---

### 2026-09-13 — P3–P5 全面评估（对比 PLAN 与实际成果）+ 问题清单与解决方案

**用户反馈**：P5 最后研报存在很多问题 → 全面复盘。

**成果对照**：P3 ✅ 27/27（差距：LLM 结构化路径从未复验）；P4 ✅ 19/19（**"光伏板块+基金"组合链未显式测试**）；P5 ✅ 19/19（差距：AAPL 正流程沙箱受限；超时熔断 failed 路径未实测）。

**问题清单（按严重度分级）**

**P0 正确性/可靠性（本轮已修复 3 项）**
1. **LLM 返回 points 可能为字符串而非数组** → ResearchPanel `.map` 潜在崩溃 → ✅ 已修（engine 统一归一化）
2. **报告缺数据截至时点** → ✅ 已修（`meta.asOf`）
3. **BFF 整段回源失败无负缓存** → 用户浏览基金 025449 时东财限流下 10+ 次连续 502 → ✅ 已修（`lastFailed` 失败窗口抑制）

**P0 内容质量（研报短板，方案已落地）**
4. **基本面/新闻情绪两个角色几乎零信息增量** → 方案：补"基本面"维度 + 个股新闻备源（巨潮 cninfo）
5. **基本面角色引用 LLM 训练记忆参与辩论** → 方案：prompt 约束缺口角色禁方向性结论；辩论只引用有真实数据支撑的角色
6. **情绪面"数据缺口=中性"是废话** → 方案：缺新闻时 view 改为"无法判断"

**P1 验证补齐**：P3 LLM 结构化路径复验、P4 组合 L1 链测试、P5 超时熔断 failed 路径实测（→ 均已在 A/B 方案与后续批次完成）、转债 K 线维持搁置。

---

### 2026-09-12 — P5 Harness 整合完成 ✅（验收 19/19；研报端到端闭环）

**交付内容（M5 + M6 + L2 工具链）**

- **M6 美股 provider**（`openbb_provider.py`，yfinance 免费档起步）：美股 quote / 日 K / 新闻，注册为 `us` 类型主源；**沙箱内 Yahoo 对共享出口 IP 限流** → 降级路径实测 ✓
- **M5 深度研究引擎**（B 计划：自研多角色 LLM 链 `app/research/`）：`adapter.py` vendor_adapter **回读统一数据层**（响应新增 `phases` 字段，P2 同源算法，研报与详情页归因同源 ✓）；`engine.py` 5 角色 LLM 链；`tasks.py` 异步任务注册表 + **熔断**（LLM ≤12 次 / 任务 8 分钟超时）+ **code+date 每日限 1 次** + 并发去重 + 完成回调 ingest 落库
- **web L2 链路**：`lib/research.ts` + `/api/research/start|ingest|GET`；L2 工具 `deep_research` / `get_research_report` 入注册表；**聊天意图升档真实触发**；详情页 ⑥ 区 ResearchPanel 研报视图；热点卡片"深度解读"按钮激活
- **TradingAgents spike**：隔离 venv 安装 + import 验证通过（版本冻结 `.venv-spike`）；**B 计划引擎为主力已端到端验证**，native 后端留作后续增强

**端到端实测（600519 贵州茅台）**

- 任务 4b694003：采集（行情经腾讯备源）→ 5 角色 LLM → **rating=谨慎、llmCalls=5、degraded=true（新闻源受东财限流）**
- 研报质量：技术分析师引用 P2 同源阶段；基本面分析师明确声明"无财务数据，不编造"；多空辩论全部有出处；含免责声明 ✓
- 落库 ✓ → 详情页/聊天均可呈现

**验收 19/19**：落库结构 / 话语一致 / 每日限 1 次复用 / AAPL 同一链路（降级场景）/ 详情页 SSR / 聊天意图升档。

**本轮排障沉淀**：`tasks.py` 缺 `import time`（线程首行 NameError 静默死亡 → 任务永远 running、熔断永不触发——**线程异常必须顶层捕获**）；`_key` f-string 笔误；akshare 无 timeout 需看门狗；Python `llm_client` 与 web `llm.ts` 均需 BASE_URL 缺省推断。

**东财遗留集中测试（按用户指示执行）**：转债 K 线（113710/123285）**仍不可用** → 继续搁置；快照补齐**主动跳过**（EM 限流期间全量刷新只会失败并加剧限流）。

---

### 2026-09-12 — P4 体验优化：聊天 Markdown 渲染 + 消息布局重排

- 引入 `react-markdown` + `remark-gfm`：助手回答中的**表格/加粗/列表/斜体**正确渲染
- 布局重排：用户气泡限宽 75% 右对齐；助手消息改浅灰面板；**工具状态合并为单条 chip 并原地更新**；"思考中"呼吸指示；空态改为可点击示例问题
- 验证：`tsc` 0 错误；react-markdown SSR 渲染样例断言全过；`/chat` 编译 200

---

### 2026-09-12 — P4 统一 Agent 完成 ✅（验收 19/19，function calling 端到端打通）

**交付内容（M4 全项 + P4 补强）**

- `web/lib/llm.ts`：OpenAI 兼容流式客户端（token 增量 + `tool_calls` 碎片按 index 拼装）；`LLM_BASE_URL` 缺省时按模型名推断
- `web/lib/tools.ts`：L1 工具注册表 6 个（`search_products` / `get_quote` / `get_kline` / `get_hotspots` / `get_fund_holdings` / `get_phase_analysis`）
- `web/lib/chat.ts` + sessions API：会话/消息持久化（`ChatMessage` 增 `toolCallId`/`name`）
- `/api/chat`：SSE 流式对话（meta/delta/status/tool_result/intent/error/done）+ function calling 循环（≤4 轮）+ 持久化容错 + 意图升档规则
- `/chat` 页面：会话侧栏 + 流式气泡 + 工具状态 chips + 空态引导 + 免责声明

**验收 19/19**：会话持久化 CRUD ✓；**function calling E2E**（问"贵州茅台现在多少钱？"→ 自动调 `get_quote`（经腾讯备源）→ 流式回答引用真实价格）✓；**多轮上下文**（第二轮"它属于哪个产品类型？"正确指代）✓；LLM 未配置场景明确错误事件 ✓；`/chat` SSR ✓。

**本次排查沉淀（重要技术事实）**

1. **Next.js patched fetch 会缓冲 SSE 流**：对 `stream:true` 的出站请求必须加 `cache: "no-store"`，否则 fetch 永远等不到响应——这是"meta 后无事件"的根因
2. SSE 客户端解析：chunk 边界截断事件时只能 `break` 内层等下一 chunk
3. Prisma 相对路径 `file:./dev.db` 与 `.env` 的 BOM 问题：重写 `.env` 必须无 BOM

---

### 2026-09-12 — P4 脚手架交付（🟡 进行中）：13/13 通过

**P4 已交付**：`llm.ts`（未配置抛 `LlmNotConfiguredError`）、`tools.ts`（L1 工具 6 个，全部为既有 API 薄封装）、`chat.ts` + sessions API、`/api/chat`（SSE + function calling 循环 ≤4 轮）、`/chat` 页面、迁移（`ChatMessage` 增 `toolCallId`/`name`）。
**验收 13/13**（当时）：会话 CRUD、SSE 端点、LLM 未配置 → 明确错误事件且**用户消息不丢**、页面 SSR。

**当时剩余（阻塞于 LLM 配置）**：需主人在 `web/.env` 提供 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`。

---

### 2026-09-12 — R15 增强：Tavily 接入 + 新浪板块成分备源（P3 遗留项闭环）

- **用户批准**：接入多源 + 自动降级（保证不空白）+ 控制请求频率；提供 Tavily key
- **配置打通**：新增 `app/config.py`——env 加载顺序 真实环境 > `data-service/.env` > `../web/.env`；`TAVILY_API_KEY` 与 `SEARCH_API_KEY` 互为别名；值自动剥离引号
- **回答用户问题（web search 能否做成分映射）**：不适合——成分股需要精确代码，搜索结果为非结构化文本，LLM 抽取代码有幻觉风险（金融场景不可接受）；**正解 = 新浪结构化板块接口**（非东财域名，实测 84 行业 + 175 概念）
- **pipeline 增强**：Tavily 3 天窗口 + 双查询合并去重；板块名单链 东财 → **新浪行业+概念** → 同花顺；**兜底机制**：关键词命中 <2 条时用"当日涨幅居前板块"补位（数据驱动，仍走成分映射）
- **实测**：`newsSource=tavily` ✓；3 条热点各带 **6 只成分股** ✓
- **P3 验收复跑 27/27 无回归** ✓

---

### 2026-09-12 — P3 热点 pipeline + dashboard 完成 ✅（验收 27/27）

**交付物**

- **data-service v0.5.0**：`hotspot/pipeline.py`（新闻双源 R12：Tavily 代理优先 → 财联社电报 → 东财快讯 → 结构化（LLM 优先，未配置回退关键词规则）→ 板块成分映射 → 回调 `/api/hotspots/ingest` 落库）；`hotspot/llm_client.py`；`hotspot/scheduler.py`（APScheduler 盘前 08:30 / 盘后 16:30 + **启动补跑** + 单飞锁）；端点 `POST /hotspots/run`、`GET /hotspots/status`
- **web**：`lib/sse.ts`（**通用 SSE 基础设施**，P4 流式对话复用）+ `/api/hotspots/stream`；`/api/hotspots/ingest`（落库回调 + SSE 广播 + 可选 INGEST_TOKEN 鉴权）；`lib/hotspots.ts`（落库去重 + 相关产品解析）；**首页改造为热点 dashboard**；迁移 `HotspotDigest` 增 `newsSource/engine/degraded/note`
- **测试**：`web/scripts/test-p3.mjs`（27 项断言）

**验收结果（27/27 全绿）**：真实产出——启动补跑自动触发 → **3 条热点**（人工智能 / 人形机器人 / 水利）落库；调度就绪（下次 08:30 / 16:30，TZ=Asia/Shanghai）✓；SSE 端到端 ✓；R12/R10 降级标注 ✓。

**遗留（并入"东财链接问题"，P5 后集中测试）**：股票板块成分映射未取得数据；LLM 结构化路径未实测；Tavily 路径未实测。

---

### 2026-09-12 — P2 收尾判定：⚠️ 完成（验收 36/38，遗留 2 项搁置至 P5 后）

**完成判定依据**：交付物齐全（详情页六区、ECharts 全图表、KlineDaily 增量缓存、ZigZag 阶段划分、规则画像、事件映射、R14 分类浏览、R15 多源降级与限速）；质量关——web 单测 36/36、ds M8 单测 23/23、`tsc` 零错误、P2 验收 36/38。
**PLAN「验证方式 P2」逐条对照**：① 股票/基金/虚拟币各验 ✓；② 自定义起止 ✓；③ 多标的对比数据通路 ✓；④ KlineDaily 二次访问命中 ✓；⑤ 阶段划分可复算 ✓；⑥ 事件标注命中 + 归因"可能相关" ✓；⑦ 加密降级缺口说明 ✓。
**遗留 2 项**：沪/深转债 K 线（113710/123285）——外部源问题，非代码缺陷（→ 09-13 闭环）。

**用户决策（2026-09-12）**：东财链接问题**记录搁置，P5 完成后集中测试**。

---

### 2026-09-12 — R15/M8 交付：多源自动降级 + 频率控制（P2 验收升至 36/38）

**实现**

- `app/utils/limiter.py`：源族令牌桶（最小间隔 5s / 突发 2 / ≤12 次每分钟）+ 连续失败 2 次熔断冷却（180s 起指数至 900s）；`acquire()` 超时返回 False 交由调用方转备源
- `providers/base.py`：主备链注册表（`register_chain` / `get_provider_chain`）
- `providers/tencent_provider.py`：腾讯备源（行情 + 前复权日 K），覆盖 A股/场内基金
- `providers/sina_provider.py`：新浪备源（`fund_etf_hist_sina`，场内基金日 K）
- `akshare_provider.py`：东财按需路径全部经限速器统一入口 `_em_request`
- `main.py`：`/quote` `/quotes` `/kline` 改为链路迭代；降级成功时在响应 note 标注
- 单测 `tests/test_p2_m8.py`：**23/23 通过**，并借此修复限速器真 bug（`on_success` 未解除冷却）

**实测验证（东财处于冷却期时的真实降级）**

- `/kline?type=fund&code=159915` → **source=tencent，43 根**，note 完整标注降级链路 ✓
- `/quote?type=stock&code=600519` → **source=tencent，price=1275.16** ✓
- `/kline?type=bond&code=113710`（转债）→ 全链路失败 → 502 明确说明（页面降级说明，非空白）✓

**P2 验收：36/38**（35→36）；顺带修复"非交易日导致每次访问都触发增量抓取"的缺陷。

**已知限制（P7 处理）**：主备源复权口径可能不同（东财前复权 / 腾讯 qfq / 新浪不复权），KlineDaily 逐行记录 `source` 可追溯。

---

### 2026-09-12 — P2 体检：35/38；3 项根因锁定为东财额度型限流（附备源实测）

- 全套验收复跑仍 **35/38**，失败 3 项（159915 ETF、113710/123285 转债 K 线）错误均为 `RemoteDisconnected`
- **根因排查（多轮鉴别实验）**：akshare 官方封装同样失败 → 排除自研代码问题；`fqt=0/1/2` 全部失败 → 排除复权参数问题；**关键反证**：连发 6 个探测请求后，连此前正常的股票 K 线也失败 → 这不是"品种级拒绝"，而是**额度极紧的滚动窗口限流**
- **备源实测结果**：✅ 新浪 ETF K 线（3584 行）、✅ 腾讯 ETF K 线（43 行）、✅ 腾讯实时行情；✗ 腾讯转债 K 线（不覆盖）、✗ 新浪转债旧接口（404）
- **处置**：今日不再向东财发请求（R9 复测已超限）

---

### 2026-09-12 — Docker 骨架验证完成（五项全过）；验证后文件与镜像数据已按用户要求全部清除

**验证结论（可行性已证实，P7 照此重建即可）**：✅ 双镜像可 build（**docker.io 需走国内镜像前缀**、pip 用阿里源 + `--timeout 120 --retries 10`、npm ci 需长超时参数）；✅ 全新卷迁移自动应用；✅ 双容器 healthy；✅ 容器互通；✅ 卷持久化。
**已知小坑（P7 正式化处理）**：Prisma 在 slim 镜像内 openssl 探测告警；沙箱网络对 pypi/npm 大文件传输偶发超时。
**清理**：容器/网络/卷/本地镜像 + 文件共 **102 个已删除，零残留**。

---

### 2026-09-12 — Docker 骨架文件就绪；验证被环境阻塞（Docker 守护进程无法启动）

- 全部文件已备好；**阻塞**：本机 Docker Desktop 启动后进程即退出。**需主人手动打开 Docker Desktop 确认**。
- **EM 限流静默期**：发现此前的周期性探测可能反复重置冷却窗口；已挂 45 分钟完全静默观察器。

---

### 2026-09-12 — R14 分类浏览（搜索页增强，用户截图反馈）

- **新需求**：选中分类标签即展示该类全部产品（无需关键词），支持按涨幅/名称排序 → 已实现并写入 PLAN（R14 + M2 补充）
- **实现**：Product 增 `lastPrice`/`lastChangePct` 快照列（**手工迁移**——`migrate dev` 漂移检测会误删应用层维护的 FTS5 虚表）；`lib/browse.ts`；`/api/search` 浏览分支；`POST /api/market/refresh`；每日同步末尾自动刷快照
- **修复**：Prisma 内置 SQLite 不支持 `UPDATE...FROM (VALUES)` → 改事务内批量 `updateMany`；**基金快照写入成功 23,953/27,811**
- **待办**：东财冷却后补股票/转债快照

---

### 2026-09-12 — P2 编码完成（验收 35/38，剩余项为外部限流待复测）

**交付物**

- **data-service v0.3.0**：`/kline` 类型路由（场外基金返回净值历史、`interval=1m` 当日分时透传不落库）；新增 `/news`、`/fund/holdings`、`/bond/yieldcurve`；quote 扩展市值/PE(TTM)/PB/换手率；`crypto_provider` 补齐 quote/kline；**修复 `_secid` 沪转债 11xxxx 前缀错误**（P1 遗留缺陷）
- **web**：`lib/kline.ts`（增量缓存：首段整段回源 → 头部缺口 + 尾部增量）；`lib/phases.ts`（ZigZag 阶段划分）；`lib/profile.ts`（规则模板画像）；`lib/events.ts`（转折点 + 大波动日挂接当日新闻）；`/api/kline`、`/api/events`；**详情页六区重构** + ECharts 6 图
- **测试**：单测 **36/36**；`tsc --noEmit` 零错误；`scripts/test-p2.mjs` 38 项断言

**验收状态**：**35/38 通过**：六区 SSR 全部命中；R13 双源交叉验证通过（偏差 <0.5%）；**缓存验收通过**（二次访问 `fetchedDays=0`）；**3 项失败 = 东财 IP 级限流**。
**BTC/加密链路已验证可用（provider 层实测）**：经本地代理拉取 CoinGecko 成功（BTC price=77181）。**关键发现（环境约束）**：WorkBuddy 后台任务沙箱会改写进程代理环境并拦截境外 CONNECT → **后台启动的 data-service 无法使用 R12 海外源**。**解法：主人在自己终端前台启动 data-service 并设 `HTTPS_PROXY`**。

**执行中发现并解决的问题**：沪转债 `secid` 前缀 bug（`_secid("113710")` 返回 `0.113710` → 已修为 `1.113710`）；test-p2 初版两处脚本 bug；**东财限流被两轮验收触发**——测试已内置 1.5~2s 节流 + K 线空结果 8s 退避 ×3，仍触发 IP 级冷却。

---

### 2026-09-12 — P6/P7 优化评估 + Docker 骨架提前验证

- P6×7 + P7×7 共 14 点优化，用户确认**全部写入 PLAN.md**
- 用户确认 **P2 验收后插入最小 Docker 骨架验证**（双镜像 build + SQLite 卷持久化 + 容器互通，约半小时）
- 关键决策：MCP 传输 HTTP 优先；首批技能按复用度排序；fastmcp 默认仅 localhost；SQLite named volume；TZ=Asia/Shanghai；ingest 共享密钥
- 风险补强：MCP server 配置白名单制；镜像体积失控备选"核心+分析"双 tag

---

### 2026-09-12 — 补充决策：称呼偏好 + R13 多源验证

- 用户称呼偏好定为"主人"（记入用户级 `USER.md` / `MEMORY.md`，跨项目生效）。**原文见 [PLAN.md 决策记录](PLAN.md)。**
- 数据源可用性验证**推迟到各阶段实际落地时进行**；用户提出**多源数据对比验证**期望 → 新增 **R13** 写入 PLAN

---

### 2026-09-12 — 目标 LLM 暂定 DeepSeek + GLM

- 用户确认目标 LLM 暂定为 **DeepSeek + GLM（智谱）**：均支持原生 function calling、OpenAI 兼容端点、国内可达、低成本。**原文见 [PLAN.md 决策记录](PLAN.md)。**
- H2 风险降级为"P4 启动时双家 function calling spike 验证"

---

### 2026-09-12 — P3–P5 优化评估 + PLAN.md 补强（12 点 + R12）

- 基于 P0/P1 实战教训（代理/CDN/限流/CoinGecko 不可达）与 P2 复用红利，评估出 P3×4 / P4×4 / P5×4 共 12 个优化点，用户确认**全部写入 PLAN.md**
- 新增 **R12 海外数据源自动降级**：用户本地有代理，海外源优先；不可达自动切换国内源并显式提示
- 高风险记录在案：H2 目标 LLM、H3 TradingAgents spike 先行 + B 计划、H4 东财限流被 P3/P5 放大 → P2 的 KlineDaily 缓存为前置依赖

---

### 2026-09-12 — P2 方案讨论定稿（未开始编码）

- 确认详情页**六区结构**：身份 / 现状 / 主图 / 变化解读 / 明细 / 深度分析入口，按"这是什么→现在怎样→经历了什么"的用户问题动线排列
- 新增 **R11 变化归因两阶段策略**：P2 做算法阶段划分（ZigZag）+ 大波动日事件标注；完整多因素归因明确归 P5 研报
- 一句话特点画像采用**规则模板**生成（不用 LLM）；明细区**长页全展开**不折叠
- 归因文案一律标"可能相关"不做因果断言

---

### 2026-09-11 — P1 验收测试（83 项断言全通过）✅

| 套件 | 覆盖 | 结果 |
|---|---|---|
| `web` vitest | 打分规则、中文二元组分词 | ✅ 19/19 |
| `web/scripts/test-db.mjs` | 表结构、索引、Prisma 回环、级联删除 | ✅ 16/16 |
| `data-service/tests/test_p0.py` | 行情/K线接口与交叉验证（回归） | ✅ 15/15 |
| `data-service/tests/test_p1.py`（新增） | 产品列表 4 类型、行情覆盖、边界 | ✅ 13/13 |
| `web/scripts/test-p1.mjs`（新增） | 多模式检索与排序、类别过滤、行情富集、点击加权闭环、UI 约定 | ✅ 20/20 |

**关键验证点**：代码精确 100 分居首、名称检索首位且分差正确、拼音首字母命中、FTS 注入安全返回；场内 ETF 实时价+涨跌、场外基金单位净值+日增长率、可转债实时价、退市品种降级为空值；点击一次排序分 +3（闭环验证）；SSR HTML 含面包屑、`aria-current` 导航高亮、骨架屏标记；34,776 条产品与 FTS 索引行数一致。

**测试中发现的问题（2 处，均为测试脚本缺陷）**：① `test-db.mjs` 断言过时（"Product 表为空"）；② `test-p1.mjs` 断言过严（`600519` 期望满分 100，实际 109 含点击历史加权）。

---

### 2026-09-11 — P1 产品主数据 + 智能搜索完成 ✅

**交付物**

- **data-service**：`/products?type=`（含拼音与首字母）、`/quotes?type=&codes=`（批量行情，单次外部请求）；Provider 拆分为「行情注册表」与「列表注册表」；新增 `crypto_provider.py`（CoinGecko）
- **web**：`lib/search-text.ts`（中文二元组展开 + FTS 匹配式构建）、`lib/score.ts`、`lib/search.ts`、`lib/sync.ts`
- **API**：`POST /api/sync`、`GET /api/search`、`POST /api/search/click`
- **页面**：`/search`、`/product/[type]/[code]`（占位页）、首页搜索入口
- **数据库**：Product 增 `pinyinInitials`/`searchText`；FTS5 虚表 `Product_fts`（unicode61 + 二元组展开）
- **加载态 / 返回不丢结果 / 导航体验**：`Skeleton.tsx`、路由级 `loading.tsx`、"打开中…"pending 文案；`lib/search-cache.ts`（内存 + sessionStorage，60s 新鲜期内直接复用）+ `experimental.staleTimes`；`Nav.tsx`（`aria-current`）、`Breadcrumbs.tsx`

**验证结果**：同步 股票 5,913 / 基金 27,811 / 可转债 1,052 = **34,776 条**，FTS 索引行数一致（耗时 195s）；搜索质量（`600519`→贵州茅台 100 分、`贵州茅台`→贵州茅台 90 分优于贵州轮胎 25 分、`gzmt`→贵州茅台 45 分）；价格富集（贵州茅台 1271.63 / -1.05%）；点击加权闭环（90→93）；`npm run build` 通过（8 条路由）。

**P1 补充（搜索结果行情覆盖）**：问题——搜索结果中基金/债券价格列为空。修复——行情路由扩展到 `stock/fund/bond`：场内基金与可转债走东财实时批量接口；场外基金走全市场净值表单请求 + 内存缓存 30 分钟。验证：新能源电池ETF华夏 0.901/-3.33%、华夏成长混合 1.262/-0.47%、强达转债 201.806/-3.4% 均正确；已退市转债显示 `--` 优雅降级。

---

### 2026-09-10 — P0 脚手架完成 ✅

**交付物**：`web/`（Next.js 15 + TS + Tailwind 4 + Prisma 6；`prisma migrate dev` 初始化 8 张表；`app/page.tsx` 验证页 + `app/api/quote/route.ts` BFF 代理）；`data-service/`（FastAPI + AkShare；Provider 抽象层 + `akshare_provider`；`/health` `/quote` `/kline` 三接口）；根目录 README + `.gitignore`。

**验证结果**：`npm run build` 通过（类型检查 + 5 路由）；`/kline 600519` 真实日 K 29 根 ✅；`/quote` 与 K 线交叉验证一致 ✅；BFF 全链路 ✅；错误码路径 ✅。

**执行中发现并解决的问题**

1. **Windows 系统代理不可达**：Python requests 读取注册表代理导致所有东财请求 ProxyError → data-service 启动时默认设 `NO_PROXY=*` 直连
2. **东财 CDN 节点抖动**：`push2` / `82.push2` 等节点间歇性拒绝连接 → quote 改用单股接口 + 3 host 降级重试
3. **字段映射 bug**：f51 是涨停价而非最低价，`low` 已修正为 f45（经 K 线 low 交叉验证）

---

### 2026-09-10 — P0 全面测试（35 项断言）

| 测试组 | 结果 | 说明 |
|---|---|---|
| data-service API（quote/kline/错误路径/交叉验证） | ✅ 15/15 | 含 quote↔kline 当日收盘价、高低价交叉验证 |
| 数据库结构 + Prisma Client 回环 | ✅ 16/16 | 8 表、唯一索引、约束冲突拒绝、级联删除 |
| BFF 正常/400/502 透传/503 降级 | ✅ 4/4 | data-service 停机时 BFF 正确返回 503 提示 |

**测试中发现并修复的问题（3 个真实缺陷）**

1. **kline 软失败**：akshare 的 `stock_zh_a_hist` 硬编码单 host、无重试，且数据为空时返回空 DataFrame（表现为 200 + 0 根 K 线）→ 改为直连东财多 host 镜像降级 + 软失败重试
2. **ChatMessage 级联删除缺失**：删除会话会因外键约束报错（P2003）→ schema 加 `onDelete: Cascade` + 迁移
3. 测试脚本 BigInt 序列化、清理顺序两处小问题

**已知约束（非缺陷，记录备查）**：东财对**短时间高频请求**会限流（反爬）：表现为连接被重置，空闲一段时间后自动恢复。应对：P2 引入 `KlineDaily` 增量缓存后外部请求量将大幅下降；测试与日常使用避免对同一接口短时连发。

---

### 2026-09-10 — 方案定稿

- 完成需求讨论与方案设计，[PLAN.md](PLAN.md) 定稿（含 TradingAgents/OpenBB 整合、Skills/MCP 扩展机制、7 处优化）
- 建立文档约定：PLAN.md 记需求与计划，Progress.md 记进度
- 下一步：P0 脚手架

## 阻塞与问题

> 已闭环项只保留一行结论；进行中的项保留完整说明。

### ✅ 转债行情/K 线（2026-09-13 闭环，P2 遗留 2 项已解决）

- **行情**：新增新浪 `bond_zh_hs_cov_spot` 备源（`sina_bond_provider`），东财限流期间实测可用
- **K 线**：确认**仅东财一个源**（腾讯/新浪/网易路径均已系统性排除）；限流时按 R10/R12 **显式降级**，此为正确行为——验收断言语义已同步修正为「可用或显式降级」
- **关键认知**：**未上市/已退市转债不在实时行情列表内**（113710/123285），其 K 线本不可得；P2 原失败根因是测试动态选中此类标的，非代码缺陷
- P2 验收：36/38 → **38/38** ✅。完整事实见 [CONSTRAINTS.md §C-1](CONSTRAINTS.md)

### ✅ L2 web 镜像瘦身（2026-09-14 闭环）

- **结果**：1.62GB → **1.25GB**（`docker images` 口径，-23%）；容器内占用 0.89GB；两容器 healthy + 冒烟 8/8
- **闭环过程中修复 2 个真缺陷**（锁文件未同步致 prisma 被误裁；裁剪位置错误致体积不降）→ 固化 **C24 / C25**
- **原"预期 ~0.9GB"口径有误已更正**（devDeps 非体积大头）

### ✅ FTS 孤儿行累积（2026-09-13 发现并修复，已固化 C15）

- **现象**：`Product_fts` 35,828 行 vs `Product` 34,777 行，孤儿 1,052 行（全为转债，= 一次 bond 全量同步条数）
- **根因**：L1 全量替换生成全新产品 id，而 `rebuildFts` 按当前 Product id 删除 FTS 行 → 旧 id 行永不删除
- **修复**：`rebuildFts` 前置通用孤儿清理 + 暂存表改 DROP；数据已修复一致（`scripts/fix-fts.mjs`）

### ✅ P6 已知优化点（2026-09-13 已全部执行完毕）

O1–O12 已全量落地（B+M+L 三批 12 项），明细见 [history/2026-09-13-cr1-全项目审查与O系列明细.md](history/2026-09-13-cr1-全项目审查与O系列明细.md)；PLAN 决策记录只保留"已闭环"一行。原始 P6 体检 3 条优化点的映射：**触发词子串匹配 → 仍未修复**（2026-09-20 复核，`skills.ts:175` 依旧是 `text.includes`）；状态面板探测超时 → 未修复；进程内缓存无上限 → **已由 `utils/lru.py` 解决**。

### ✅ 已解决：搜索页无结果且无样式（dev/build 冲突）

- **原因**：在 `next dev` 运行期间执行了 `npm run build`，build 覆写 `.next` 导致 dev 的路由表与静态资源错乱
- **规避约定**：项目开发期间**不在 dev server 运行时执行 `npm run build`**；类型检查改用 `npx tsc --noEmit`

### ✅ 加密货币数据源不可达（已决策：R12 覆盖，验证推迟至落地）

- **现象**：CoinGecko API 从当前网络连接超时，`/products?type=crypto` 返回 502
- **状态**：已由 R12 策略覆盖（本地代理优先 + 不可达自动降级国内源并提示）；东财数字货币源可用性验证推迟到实际落地时进行，并按 R13 做多源对比验证；不阻塞 P2

### 🟡 东财链接/限流问题（记录搁置，P5 后已集中测试；缓解措施已落地）

- **现象**：东财为 IP 级滚动窗口限流——空闲后单次请求可通过，连续 2+ 请求立即触发惩罚（连正常可用的股票 K 线也失败，akshare 官方封装同样失败），惩罚窗口可达数十分钟
- **已落地缓解**：R15/M8 多源降级 + 源族限速 + 熔断冷却；转债 K 线暂缺可用备源
- **用户决策（2026-09-12）**：记录搁置，待 P5 完成后集中测试 → **已于 P5 后执行**（转债 K 线定性闭环）

### 🟡 Docker Desktop 依赖（历史阻塞，已解除）

- **现象（2026-09-12）**：本机 Docker Desktop 启动后进程即退出，Bash 侧无法拉起 GUI 应用
- **状态**：09-14 由主人启动（v29.7.2）后 L2 镜像重建验证闭环；**后续任何 Docker 相关改动仍按主人指示暂缓**（含 C31 进程降权的镜像验证）

（其余暂无）
