# Invest Manager 代码审查报告（第一轮·全项目）

> **审查对象**：当前工作树（`dev` 分支，含未提交改动）。
> **审查方式**：全量逐文件通读（web 服务端 lib/route、data-service 全部 py、前端组件、脚本、容器化、迁移），每条发现回到代码核对；另派三路独立复核代理交叉验证。**不采信注释中的"已修复"**——以当前代码实际行为为准。
> **严重度**：P0 阻塞 / P1 高 / P2 中 / P3 低。
> **三份文档分工**：本文件 = 排查结果（含处置结论）；优化方案见 [code-review-fix-plan.md](code-review-fix-plan.md)；执行记录见 [code-review-fix-progress.md](code-review-fix-progress.md)。
> **状态**：✅ **已全部处置完毕**（22 项代码风险 + 7 项需求缺口），并经双服务全量集成验收。
>
> ⚠️ **本行的「已全部处置」仅覆盖本报告（第一轮）的 `CR-xx`/`G-xx`/`V-x`。** **第二轮·全项目**审查（`CR7-*`，14 项）见本文件后半部的同名报告标题「Invest Manager 代码审查报告（第二轮·全项目）」——**该轮全部未修复，待主人逐项决策**。其中 CR7-3 对本节 G3 的「✅ 已实现」结论提出质疑（端点零调用方），CR7-14 记录了 PLAN/Progress 的两处文档失同步。

---

## 〇、处置结果总览

> 图例：✅ 已修复并验证 / 🔵 评估后保留（附理由）/ ⚪ 已显式裁剪 / ⏳ 待本地验证

| 编号 | 严重度 | 结论 | 处置位置 | 验证 |
|---|---|---|---|---|
| CR-01 | P1 | ✅ | `web/lib/chat-history.ts`（新增）+ `api/chat/route.ts` + `api/chat/sessions/route.ts` | `chat-history.test.ts` 9 项 |
| CR-02 | P1 | ✅ | `web/lib/llm.ts` | 集成 test-p4 |
| CR-03 | P1 | ✅ | `web/lib/research.ts` | — |
| CR-04 | P1 | ✅ | `web/lib/prisma.ts` | `prisma.test.ts` 5 项 |
| CR-05 | P2 | ✅ | `web/lib/kline.ts` | `kline-headtail.test.ts` 2 项 |
| CR-06 | P2 | ✅ | `data-service/app/utils/timeutil.py`（新增）+ tasks/adapter/pipeline/scheduler | `test_cr6_timeutil.py` 6 项 |
| CR-07 | P2 | ✅ | `api/sync/route.ts` + `api/market/refresh/route.ts` | — |
| CR-08 | P2 | ✅ | `web/lib/request-origin.ts`（新增）+ 三端点 | `request-origin.test.ts` 8 项 |
| CR-09 | P3 | ✅ | `web/lib/market-snapshot.ts` | `market-snapshot.test.ts` 5 项 |
| CR-10 | P3 | ✅ | `web/lib/events.ts` + `product/[type]/[code]/page.tsx` | `events.test.ts` +4 项 |
| CR-11 | P3 | ✅ | `schema.prisma` + 迁移 + `web/lib/hotspots.ts` | 迁移已应用 |
| CR-12 | P3 | ✅ | `web/lib/mcp.ts` | 集成 test-p6 |
| CR-13 | P3 | ✅ | `web/lib/mcp.ts` | 集成 test-p6 |
| CR-14 | P3 | ✅ | `api/research/start/route.ts` | — |
| CR-15 | P3 | ✅/🔵 | 见下「CR-15 逐项」 | 混合 |
| CR-16 | P2 | ✅ | `data-service/app/hotspot/pipeline.py` | `test_cr6_pipeline.py` 10 项 |
| CR-17 | P3 | ✅ | `data-service/app/providers/akshare_provider.py` | `test_p2_m8.py` |
| CR-18 | P3 | ✅ | `data-service/app/providers/sina_bond_provider.py` | — |
| CR-19 | P2 | ✅ | `data-service/app/providers/akshare_provider.py` | `test_p2_m8.py` |
| CR-20 | P3 | 🔵 | 评估后保留（有意双层设计，风险已由 CR-06 消除） | — |
| CR-21 | P3 | 🔵 | 运维风险（非缺陷，已有 note 标注） | — |
| CR-22 | P3 | ✅ | `data-service/app/utils/timeout.py` + `main.py` | `test_p2_m8.py` |
| G1 | — | ⚪ | 显式裁剪（PLAN M1 条目划除 + 决策记录） | — |
| G2 | — | ✅/⏳ | `data-service/app/sync_scheduler.py`（新增）+ `main.py` | 端点实测 |
| G3 | — | ✅ | `providers/chain.py` + `/quote/verified` | `test_g3_crosscheck.py` 8 项 |
| G4 | — | ✅ | `web/lib/llm.ts#chatJson` + `search.ts#llmFallback` | `search-fallback.test.ts` 4 项 |
| G5 | — | ✅ | `api/watchlist/route.ts`（新增）+ `WatchButton.tsx`（新增） | `watchlist/route.test.ts` 6 项 |
| G6 | — | ✅ | `data-service/app/providers/hk_provider.py`（重写：多 host 降级 + 分页 + 快慢路径分离）+ `tencent_provider.py`（腾讯备源） | `test_g6_hk.py` 28 项 + 3 反向验证 |

**验收过程中新发现并修复的 2 个缺陷**（单测未覆盖、集成才暴露）：
- **V1**（高）：`upsertCandles` 原生 INSERT 传 ISO 字符串 → `KlineDaily.date` 存为 text，与 Prisma 的整数毫秒存储不匹配 → 日期范围查询**静默漏行**（详见第五节）。
- **V2**（中）：G2 自动同步会**用降级备源缩小主数据**（转债 1052 → 329，详见第五节）。

---

## 一、代码隐藏风险

### P1（高）

#### CR-01 · 会话历史中的孤儿 tool 消息会让该会话永久 400
- **文件**：`web/lib/chat.ts:53-71`、`web/app/api/chat/route.ts:100-117`、`web/app/api/chat/sessions/route.ts:35-46`
- **现象**：`getMessages` 取"最近 200 条"后反转直接送 LLM，**重建历史时不做 `tool_calls` ↔ `tool` 配对校验/修复**；`tool_call_id` 缺失时兜底为常量 `"call"`（`route.ts:113`）。
- **触发场景**（任一）：
  1. 会话消息数 > 200，第 200 条边界落在 `assistant(tool_calls)` 与其 `tool` 结果之间 → 窗口首条是孤立 `role:"tool"` → OpenAI 兼容端点返回 400（"tool message must be a response to a preceding message with tool_calls"）；此后**该会话每次提问都失败，用户无法自愈（只能删会话）**。
  2. `PUT /api/chat/sessions` 允许 `role:"tool"` 且**不写 `toolCallId`**（只校验 role 白名单）→ 落库 `toolCallId=null` → 下次对话该条 id 变 `"call"`，与 assistant 声明的 `tool_calls[].id` 不一致 → 同样 400。
  3. 同类：`safeAppend` 单条失败被允许继续（`route.ts:126-144`），可能只落 assistant 或只落 tool，制造同样孤儿。
- **影响**：**单会话级永久不可用**（用户侧不可自愈）。

#### CR-02 · "首字节连接超时"实际把整个 LLM 流截到 60s
- **文件**：`web/lib/llm.ts:90-107`（常量 `:43-44`）
- **现象**：`AbortSignal.timeout(CONNECT_TIMEOUT_MS)`（60s）并入 `connectSignals` 传给 fetch 的 `signal`。**fetch 的 signal 作用于整个请求生命周期（含响应体流）**，不只握手/首字节——与注释"首字节连接超时"不符。
- **触发场景**：某轮 `chatStream` 流式输出持续 > 60s（长回答、reasoning 模型、慢供应商）→ 60s 到点 body 被 abort → 用户端 delta 截断 + error 事件；真正的"无数据才超时"保护 `IDLE_TIMEOUT_MS`（`:177-201`）形同失效。工具循环每轮新建 60s 计时器，多轮反复出现。
- **影响**：长回答静默/报错截断。

#### CR-03 · 研报"执行中"复用分支不登记会话 watcher（推送承诺落空）
- **文件**：`web/lib/research.ts:137-146`
- **现象**：库内已有 `running` 行且未超陈旧阈值时，`return { status: "running", reason: "研究任务执行中" }`——**未调用 `watchResearch(type, code, watcherSessionId)`**。
- **触发场景**：用户在会话 A 说"深度分析 600519"，任务已由会话 B（或详情页按钮）启动且仍在执行 → 会话 A 收到"已启动"提示，但任务完成时**不会推送到 A**。
- **对照**：409 并发去重路径（`:167`）却登记了 watcher——同一语义两处不一致。

#### CR-04 · SQLite `busy_timeout` 为连接级，多连接下防护不完整
- **文件**：`web/lib/prisma.ts:20-36`
- **现象**：`ensureSqlitePragmas()` 仅执行一次 `PRAGMA busy_timeout=5000`，**`busy_timeout` 是连接级参数**，只在执行它的那个连接生效；未配置 `connection_limit=1` 时其余连接为 0（立即 SQLITE_BUSY）。代码注释自留"跨重连是否保持见 Progress 待验证项"，风险已知但未闭环。
- **附带**：该 Promise 失败后缓存进 `globalThis`，**失败后不再重试**（WAL/busy_timeout 永久降级）。
- **影响**：WAL 已缓解大部分读写冲突，但 busy_timeout 未覆盖全连接池，防护不完整。

### P2（中）

#### CR-05 · kline 头/尾缺口共用 `lastChecked`，头部补全顺带压制尾部增量
- **文件**：`web/lib/kline.ts:247-298`（关键 `:273` 写、`:282-285` 读同一 key）
- **现象**：`lastChecked` 以 `${type}:${code}` 为键，被"头部缺口补全"与"尾部增量"共享。头补成功即 `lastChecked.set(now)` → 同请求紧接的尾部分支 `recentlyChecked=true` → **跳过尾部增量**。
- **触发场景（必现）**：库内已有 [minCached,maxCached]，请求区间同时向左、向右扩展（先查 90 天再查 1 年）→ 头补成功、尾不补；本次拿不到"今天"的 K 线，note 显示"增量复查窗口内（30 分钟）"，最长 30 分钟后自愈。
- **影响**：K 线图短期落后一日（非永久）。

#### CR-06 · 日期口径跨服务不一致：web 用北京时间，data-service 全部用本地 `date.today()`
- **文件（data-service 侧全部命中）**：
  - `data-service/app/research/tasks.py:133`（研报 `date` 与回调 payload）
  - `data-service/app/research/tasks.py:57,83`（`_daily_done` 每日限额判断）
  - `data-service/app/research/adapter.py:342`（`research_date()`）
  - `data-service/app/hotspot/pipeline.py:605`（digest `date`）
  - `data-service/app/hotspot/scheduler.py:94,108`（补跑判断的"今天"）
  - web 侧对照：`web/lib/research.ts:126,216`、`web/lib/hotspots.ts` 的 `dayStart` 用北京时间
- **现象**：web 用北京日期建/查 `(type,code,date)`，`ingestResearch` 优先信任 `payload.date`；data-service 全部用**本地时区**的 `date.today()`。compose 设了 `TZ=Asia/Shanghai`，但**本地开发/异机部署未设 TZ**。
- **触发场景**：TZ≠Asia/Shanghai（或 UTC）时，北京时间 00:00–08:00 区间：① web 记录 running 行日期 D，data-service 回调带 D-1 → upsert 命中 D-1，**D 行永久 running**（前端无限轮询，仅靠 10 分钟陈旧逻辑救），并额外产生 D-1 重复行；② `_daily_done` 每日限额错位（当天可能放行 2 次或误拒）。
- **标注**：**待验证**（取决于部署 TZ；dev `.env` 未设 TZ，当前本机环境恰好为 CST 时不触发）。

#### CR-07 · 同步/快照超长请求，无 `maxDuration`/超时约束
- **文件**：`web/lib/market-snapshot.ts:94-123`、`web/lib/sync.ts:193-202`、`web/app/api/sync/route.ts:15`
- **现象**：stock/bond 每 100 只固定 `sleep(1500)`；stock 约 2.9 万只 → 光 sleep ≈7 分钟；`syncType` 末尾每类型再跑一次快照；`syncAll` 串行 4 类型 → 单次 `/api/sync` 可达 20+ 分钟。路由未设 `maxDuration`，无"同步中"状态。而 `/api/hotspots/run` 设了 `maxDuration=300`——口径不一致。
- **触发场景**：反代/客户端先超时断开，调用方以为失败而重试；重试需等前一次单飞结束后再跑一整轮。
- **影响**：运维层面不可控长请求。

#### CR-08 · 三个重载写端点无鉴权、可被跨站简单表单触发（CSRF + 资源耗尽）
- **文件**：`web/app/api/sync/route.ts`、`web/app/api/market/refresh/route.ts`、`web/app/api/hotspots/run/route.ts`
- **现象**：三者均不读请求体/Content-Type，无 token、无 Origin 校验。简单表单 POST（`enctype=text/plain`）不触发预检，可直接打到 `http://localhost:3000/api/...`。
- **触发场景**：用户浏览含 `<form action="http://localhost:3000/api/sync" method="post">` 的页面 → 触发全量同步（数分钟 + 反复捶打东财）。对照：ingest 端点有 `INGEST_TOKEN`。
- **影响**：安全 + 可用性（与需求缺口 G7 同源，此处是具体可触发路径）。

#### CR-16 · 热点 pipeline 整体超时只约束 `build_items`，`fetch_news`/`structure_topics` 不在预算内
- **文件**：`data-service/app/hotspot/pipeline.py:591-602`（`deadline` 仅在 `build_items` 内被检查）
- **现象**：`HOTSPOT_PIPELINE_TIMEOUT_S`（默认 300s）算出 `deadline` 后，`fetch_news()`（Tavily 25s 超时 + cls/em 各 45s 看门狗 + 多轮）与 `structure_topics()`（LLM 60s 超时）都在检查**之前/之外**执行，不受 `deadline` 约束。
- **触发场景**：新闻源挂起（多个 45s 看门狗叠加）+ LLM 慢（60s）→ 实际耗时显著超预算；若外部源持续挂起，`_state["running"]` 占用时间远超预期，期间所有手动/定时触发被拒。
- **影响**：超时防线不完整（R15 防线漏网）。

#### CR-19 · `akshare_provider._fund_nav_table` 缓存失败不写负缓存
- **文件**：`data-service/app/providers/akshare_provider.py:320-331`
- **现象**：全市场净值表单 30 分钟缓存，失败时直接抛 `ProviderError`，**无失败负缓存**（对比 `crypto_provider` 有 `CG_FAIL_COOLDOWN`）。限流期一次失败后，后续每个场外基金请求都会重新整表拉取（60s 看门狗）。
- **影响**：限流期反复捶打天天基金（R15 防线漏网，与 CR-04/CR-05 同类）。

### P3（低）

#### CR-17 · 转债备源降级时交易所归属依赖数字前缀推断（脆性）
- **文件**：`data-service/app/providers/akshare_provider.py:867-877`
- **现象**：新浪 cov_spot 备源取 code 时若命中 `symbol` 分支（`sh113xxx`→`113xxx`），丢掉了 `sh`/`sz` 前缀，改由 `_exchange(纯数字)` 推断。经核验当前前缀规则恰好覆盖（11→SH、12→SZ），**实际不触发错误**——仅指出该路径依赖隐含约定，脆性较高。

#### CR-18 · `sina_bond_provider` 快照刷新失败静默沿用旧数据
- **文件**：`data-service/app/providers/sina_bond_provider.py:64-69`
- **现象**：刷新失败时 `return self._rows`（旧快照）并仅 `log.warning`；响应 `source` 仍标 `sina-bond`，**无"数据陈旧"标注**，与 R10/R16"降级须显式标注"语义不完全一致。

#### CR-20 · 每日限额在 web 与 data-service 双侧各判一次
- **文件**：`data-service/app/research/tasks.py:83-87`、`web/lib/research.ts:130-147`
- **现象**：每日限 1 次在两处各判（web 查库 done，data-service 查内存 `_daily_done`）；data-service 重启后 `_daily_done` 清空，仅靠 web 侧兜底。依赖同一日期口径（见 CR-06），跨 TZ 时可能重复消耗额度。

#### CR-21 · 研报技术面维度依赖 web 回读（运维风险，非缺陷）
- **文件**：`data-service/app/research/adapter.py:118-147`
- **现象**：回读 `web/api/kline` 失败时返回 `{ok:False,note}` 进 `gaps`，属**正确的显式降级**（R10）。仅提示：`WEB_BASE_URL` 配置错误会整体降级技术面（已有 note 标注）。

#### CR-22 · `timeout.py` 看门狗放弃的线程无回收，仅靠上游自然结束
- **文件**：`data-service/app/utils/timeout.py:42-49`、`research/adapter.py:59-99`
- **现象**：Python 无法强杀线程；看门狗超时后线程继续存活到上游恢复。研报采集侧有信号量限额（`RESEARCH_MAX_COLLECT_THREADS`）+ `collect_stats` 可观测，但 **provider 端点（quote/kline/hotspot）的看门狗线程无任何限额**，理论上大量超时请求可累积线程。
- **影响**：极端情况下线程累积（当前每次 45s、有内存缓存前置，实际风险低）。

#### CR-09 · 行情快照批量写会把缺失字段覆盖为 NULL（既有行为，非回归）
- **文件**：`web/lib/market-snapshot.ts:98-107`（过滤）、`:39-57`（批量写）
- **现象**：只要某行 `price != null || changePct != null` 就纳入批量写，`CASE` 会把另一为 null 的字段写成 NULL，覆盖上一轮有效快照值。改单条 CASE 之前（原逐行 `updateMany`）行为相同——**既有语义，非本次引入**。
- **影响**：快照列被局部破坏（仅用于排序，展示层有实时富集兜底）。

#### CR-10 · 事件"挑选日期"逻辑是死代码（大波动日/转折点筛选未生效）
- **文件**：`web/lib/events.ts:59-73`（定义）、`:75-108`（未调用）
- **现象**：`pickEventDates`（转折点 + 单日 |涨跌|>3%）**只被单测引用**，`fetchEvents` 生产路径从未调用——R11 设计要求的事件筛选未落地。

#### CR-11 · 热点 digest 去重"先读后写"，无唯一索引（并发重复）
- **文件**：`web/lib/hotspots.ts:175-212`；`web/prisma/schema.prisma:35-50`
- **现象**：去重键 `(date,title)` 无唯一索引，去重是应用层 read-then-write。**缓解事实**：data-service 侧 `_single_flight` 保证同一时刻只有一个 pipeline 在跑，故同一批 ingest 不会并发；风险仅在"多 web 实例/多 worker 共享同库"时成立。故降为 P3。

#### CR-12 · `mcp.stopAllMcp` 竞态：清 `connecting` 可复活已停止 server / 重复 spawn
- **文件**：`web/lib/mcp.ts:537-546`
- **现象**：`stopAllMcp` 把 `rt.connecting` 置 null 且不复位进行中的连接：正在 connect 的 Promise 之后仍执行 `rt.client=client; rt.state="connected"`，把"已停止"的 server 复活；清空 `connecting` 又允许并发 `ensureConnected` 再 spawn。当前仅测试用，生产未调用。

#### CR-13 · `callMcpTool` 目标 server 降级时误报"未知 MCP 工具"
- **文件**：`web/lib/mcp.ts:469-508`
- **现象**：目标 server degraded/未连接时一路 `continue`，最终报"未知 MCP 工具"——把"工具存在但源不可用"误导为名字错误；且为匹配工具名会对前面每个 server 尝试连接（可能 spawn 无关子进程）。

#### CR-14 · `/api/research/start` BFF 路径不登记 watcher（会话语义不一致）
- **文件**：`web/app/api/research/start/route.ts:31`、`web/lib/research.ts:120`
- **现象**：详情页走 BFF 不传 `watcherSessionId`。详情页场景本身无会话（可接受），但与聊天路径推送语义不一致，属口径不统一。

#### CR-15 · 其他低危项（打包）
| 项 | 文件:行 | 说明 | 处置 |
|---|---|---|---|
| kline 死条件 | `web/lib/kline.ts:86-89` | `dayStart(e)<dayStart(s)` 在上一行已 return，永不触发 | ✅ 已删 |
| kline 上游 400 映射成 503 | `web/app/api/kline/route.ts:37-43` | 无法区分"参数错"与"上游挂" | 🔵 保留（`e.status===502?502:e.status===501?501:503` 已按上游码分流，400 场景由上游不返回，暂无实证触发） |
| kline 逐行 `create` | `web/lib/kline.ts:146-168` | 首次回源 5 年约 1200 次往返，无批量写 | ✅ 改分块 `INSERT OR IGNORE`（见 V1） |
| `isUsableCandle` 不校验 volume | `web/lib/kline.ts:114-126` | NaN volume 入列 | 🔵 保留（SQLite 存 NULL，无实证异常） |
| 热点 N+1 查询 | `web/lib/hotspots.ts:151-160` | `resolveRelated` 每 item 2 次查库 | 🔵 保留（量小，收益低） |
| 状态缓存忽略 `connect` | `web/lib/gateway.ts:101-110` | 首次 `connect:false` 污染后续 30s | ✅ 已按 `connect` 分键 |
| MCP 配置每次热读 | `web/lib/mcp.ts:73-90,441-465` | 每次 chat 请求 `readFileSync`+`parse` | 🔵 保留（配置小，读取代价低） |
| PUT 写消息无长度上限 | `web/app/api/chat/sessions/route.ts:24-48` | `/api/chat` 已限 4000，此路径未限 | ✅ 限 20000 |
| watchers 无 TTL | `web/lib/research.ts:100-118` | 任务永不回调时长期驻留 | 🔵 保留（单机量小，已有 failed 分支清理） |
| llm 死变量 + 无 decoder 收尾 flush | `web/lib/llm.ts:122-123,224-228` | `finish` 被 void；末尾多字节字符可能丢失 | ✅ 已删死变量 + 补 `decoder.decode()` |
| search 单字符候选偏斜 | `web/lib/search.ts:53-79` | 可能把名称命中挤出候选 | 🔵 保留（`orderBy code asc` 已保证确定性） |
| sync 行 `type` 取自 payload | `web/lib/sync.ts:119-139` | provider 返回异类型条目会写进该分区 | 🔵 保留（provider 契约保证同类型） |
| DELETE 吞异常成 404 | `web/app/api/chat/sessions/[id]/route.ts:28-34` | DB 错误被掩成"会话不存在" | ✅ 区分 P2025(404) / 其他(500) |
| `rebuildFts` 半更新无日志 | `web/lib/sync.ts:229-246` | 三条语句同 try/catch，中途失败静默 | ✅ 分步 try/catch + 日志 |
| 单飞锁仅进程内 | `web/lib/sync.ts:14-18` | 多副本共享 SQLite 时暂存表互相清空 | 🔵 保留（当前单容器部署不触发，已注明） |
| `research-target` 误判 6 位数字 | `web/lib/research-target.ts:14-20` | 如"净利润 862810 万元"被当成标的 | 🔵 保留（仅在意图词命中后调用，收紧会破坏合法识别） |
| `db-stat.mjs` 引用不存在模型 | `web/scripts/db-stat.mjs:4` | `syncState` 恒 ERR | ✅ 已移除 |
| `.gitignore` 漏 WAL 边车 | `.gitignore:18-20` | 未忽略 `*.db-wal`/`*.db-shm` | ✅ 已补 |
| 死代码 | `web/lib/context-budget.ts:69,102`、`tasks.py:187` | `overflow`/`_ = started` 无效变量 | ✅ 已删 |

---

## 二、可优化项

| # | 项 | 处置 |
|---|---|---|
| 1 | **`gatherCandidates` FTS→IN 补全**可合并为单查询 | 🔵 保留（当前正确，收益有限） |
| 2 | **`callMcpTool`** 可缓存 tool-name → binding 映射 | ✅ 已按 `mcp_<server>_` 前缀定位目标 server（不再遍历全部，见 CR-13） |
| 3 | **`mcp.ts` 配置**可缓存（按 mtime 失效） | 🔵 保留（配置小） |
| 4 | **`rebuildFts`** 可评估按 type 增量维护 | 🔵 保留（34k 行可接受） |
| 5 | **`kline.ts` 批量 upsert** 替代逐行 create | ✅ 已实现（分块 `INSERT OR IGNORE`） |
| 6 | **研报采集泄漏线程阈值告警** | ✅ 已实现（`abandoned_count()` + `/health` 暴露，见 CR-22） |
| 7 | **`sync.ts`/`market-snapshot.ts` 的 EM 限速常量**抽公共配置 | 🔵 保留（重复度低） |
| 8 | **ChatUI 研报推送**可评估独立成 `/api/events/stream` | 🔵 保留（现状可用） |
| 9 | **`DELETE` 等路径的异常吞并**应改为区分错误码 | ✅ 已实现（见 CR-15） |

---

## 三、需求交付缺口（处置结论）

| 编号 | 需求出处 | 处置 | 落地位置 |
|---|---|---|---|
| **G1** | M1 webhook 通道（企业微信/邮件） | **⚪ 显式裁剪**（站内 dashboard + SSE 已覆盖核心；与本地单机定位不匹配） | `PLAN.md` M1 条目划除 + 文末决策记录 |
| **G2** | M2 每日全量同步产品列表 | **✅ 实现** | `data-service/app/sync_scheduler.py`（每日 02:00 北京时间 + 启动补跑）+ `/sync/status`、`/sync/run` |
| **G3** | R13 双源交叉验证 + 差异标注 | **✅ 实现** | `providers/chain.py#verify_metric` + `/quote/verified`（按需端点，不叠加普通 /quote） |
| **G4** | M2 FTS 无结果时 LLM 兜底召回 | **✅ 实现** | `web/lib/llm.ts#chatJson` + `web/lib/search.ts#llmFallback` |
| **G5** | Watchlist 只读不通写 | **✅ 实现** | `web/app/api/watchlist/route.ts` + `web/app/components/WatchButton.tsx` |
| **G6** | `hk` 类型无 provider | **✅ 实现** | `data-service/app/providers/hk_provider.py`；web 侧 `SYNC_TYPES`/搜索 Tab/富集/快照白名单纳入 hk |
| **G7** | 写接口鉴权（上云前置） | **⚠ 部分实现**：B4 Origin/Referer 校验已拦浏览器跨站简单表单；**完整身份鉴权留待上云前** | `web/lib/request-origin.ts` + 三端点 |

---

## 四、验收中发现并修复的缺陷（计划外）

> 以下 2 项由**全量集成测试**暴露，单测覆盖不到——修复改动本身引入的回归。经修复 + 回归测试 + **反向验证**（回退修复确认断言失败）闭环。

### V1（高）· KlineDaily 原生写入的日期格式与 Prisma 不一致 → 日期范围查询静默漏行
- **发现于**：test-p2 的 R13 交叉验证断言失败（`kline=1266.98` vs `quote.price=1257.12`，偏差 0.784%）。
- **根因**：为优化逐行写（CR-15 项），`upsertCandles` 改为原生 `INSERT OR IGNORE` 时**日期参数传了 ISO 字符串**；而 Prisma 对 SQLite DateTime 存的是 **Unix 毫秒整数**（实测 `typeof(date)='integer'`）。文本行与 Prisma 生成的 `date >= ? / <= ?`（数字比较）不匹配 → 这些行在**带日期范围的查询中被静默漏掉**（实测污染 3 行）。
- **影响**：K 线数据"写了但读不到"，详情页少一根 K 线、缓存天数虚高、R13 交叉验证失败。**属静默数据不一致**（最危险的一类）。
- **修复**：`web/lib/kline.ts` 改传 `dayStart(c.date).getTime()`；一次性数据修复脚本 `web/scripts/fix-kline-date.mjs`（文本行 → 毫秒整数，3 行 → 0，幂等）。
- **回归防线**：`web/lib/kline-date-format.test.ts`（断言 INSERT 第 4 个绑定参数为 `number` 且等于 `getTime()`）；**反向验证**：临时回退为 `toISOString()` → 断言精确失败（`expected 'string' to be 'number'`）→ 恢复后通过。
- **效果**：test-p2 37/38 → **38/38**。

### V2（中）· G2 自动同步会用降级备源"缩小"主数据
- **发现于**：test-p1 失败（`bond=329 < 500`），而此前全量为 1052。
- **根因**：G2 新增的每日同步在凌晨自动执行过一次（`/sync/status` runs=1），当时东财限流 → 转债列表降级到**新浪 cov_spot（约 320 只）**；而全量替换语义（先删后插）会用这 329 条**覆盖**原有 1052 条 → **主数据静默劣化**。这是 G2 落地后与 R15 降级的**交互副作用**（原手动同步低频、不易撞上限流，自动每日同步放大了命中概率）。
- **修复**：`web/lib/sync.ts` 在空载荷保护（C1）之外增加**降级缩水保护**——新载荷 < 现有条数 70% 时保留旧数据并显式报错（`payload shrunk (N < M 的 70%)…`），等主源恢复后再全量更新。
- **回归防线**：`web/lib/sync-shrink.test.ts`（4 项：缩水保留 / 正常替换 / 首同步不触发 / 空载荷仍走 C1）；**反向验证**：回退修复 → 断言失败 → 恢复通过。
- **数据修复**：主源恢复后重新同步 bond（1053 条），总数恢复 34778。
- **效果**：test-p1 19/20 → **20/20**。

---

### V3（高）· 港股 provider 三处实现缺陷（2026-09-20 用户本地验证驱动发现）

> 由用户本地 `POST /api/sync?type=hk` 失败驱动排查，属**集成/真实环境**才暴露的问题。

- **V3-a 依赖 akshare 硬编码 CDN 节点**：`hk_provider` 初版复用 akshare `stock_hk_spot_em`，而其**硬编码 `72.push2.eastmoney.com`**——该节点在用户网络不可达（`RemoteDisconnected`），同族 `push2delay`/`7.push2` 却返回 200 真实数据。**等于绕过了本项目已有的多 host 降级能力**。→ 改为直连东财 + 多 host 按序降级。
- **V3-b 列表分页缺失**：东财港股 `clist/get` **忽略大分页参数**（`pz=100/1000/10000` 均只返回 100 条），港股 `total≈4707` → 初版单请求**只拿到 100 条**，`00700` 腾讯控股根本不在其中。→ 按 `total` 分页遍历（实测取满 4707 只）。
- **V3-c 行情路径误用列表接口（性能红线）**：初版 `get_quote` 复用列表快照 → **查单个港股需拉全量 4700 条、耗时约 4 分钟**。→ 快/慢路径分离：单股 `stock/get`、批量 `ulist.np`（各 1 次请求）、全量列表 `clist/get` **仅每日同步调用**；并由单测 `test_quote_does_not_trigger_list_paging` **锁为红线**。
- **修复**：`hk_provider.py` 重写；**新增腾讯港股备源**（`tencent_provider` 的 `_hk_symbol`/`_symbol_for` + `register_chain(["hk"], …, position=1)`）——用户选定方案 A（东财主源 + 腾讯备源）。
- **回归防线**：`test_g6_hk.py` 9 → **28 项**（多 host 降级 / 腾讯符号映射含边界 / 行情不触发分页红线 / 腾讯港股行情与 K 线解析 / 链顺序）；**3 处反向验证**（削弱多 host、移除类型分派、行情改用列表接口）均精确失败。
- **端到端实测**：链路 `['akshare-hk','tencent']`；强制主源失败 → 自动切腾讯（`419.0 腾讯控股`，note 标注降级链）；港股 K 线降级取到 14 根；分页取满 4707 只。

## 五、验收结论

### 集成套件（`node web/scripts/verify-all.mjs`，全部 exit=0）

| 套件 | 结果 |
|---|---|
| test-db | ✅ 16/16 |
| test-p1（搜索/富集/UI 约定） | ✅ 20/20 |
| test-p2（详情页/K 线缓存/R13/六区 SSR） | ✅ 38/38 |
| test-p3（热点/SSE/调度补跑） | ✅ 27/27 |
| test-p4（Agent/function calling/多轮上下文） | ✅ 19/19 |
| test-p5（深度研报全链路） | ✅ 21/21 |
| test-p6（Skills/MCP/Gateway） | ✅ 21/21 |

### 冒烟（`node scripts/smoke.mjs`）
✅ **7/8** —— BFF 五项全绿（health/quote/kline/search/tools-status）；第 6 项"容器内 data-service health"因本次为**本地开发态**（无 docker compose）**预期不适用**。

### 静态与单测
- `npx tsc --noEmit`：✅ **0 错**
- `npx vitest run`：✅ **140/140**（24 文件）
- data-service 离线：✅ test_p2_m8 42、test_cr6_timeutil 6、test_cr6_pipeline 10、test_cr6_lru 18、test_g6_hk 9、test_g3_crosscheck 8、test_p6_fund_report 15、test_p6_mcp 7（全绿）

### 验收中顺带修正的测试脆弱性（非产品缺陷）
1. **test-p5 `sources.length >= 2`**：`meta.sources` 按来源名去重，行情/K线/新闻同源（均 akshare）时塌缩为 1 项 → 误报。改为断言新增的 `meta.dimensions`（已采集维度），更精确表达意图。
2. **test-p5 对"当日已有研报"的环境依赖**：跨天（北京时间 00:00 后）首次运行必失败。改为按当日实际状态分流断言（有 done → 必须复用；无 → 触发新建合法）。
3. **test_cr6_pipeline 浮点边界断言**：`deadline = t0 + 300` 与断言处 `monotonic()` 存在微秒差，`<= 300` 过严 → 放宽为 `<= 300.5` 并注明原因。

### 本地环境验证（✅ 已由用户完成）

- **G6 港股连通性**：✅ **用户本地实测通过**（`POST /api/sync?type=hk` 正常）。
  - 排障过程与根因见上「V3」：根因非"港股被封"，而是 akshare 硬编码 CDN 节点不可达 + 列表分页缺失 + 行情误用列表接口三处实现缺陷，均已修复；并补腾讯备源（方案 A：东财主源 + 腾讯备源）。
- **G7 完整身份鉴权**：仍待上云/`WEB_PORT` 对外前补齐（当前单机无暴露面；B4 的 Origin/Referer 校验已拦浏览器跨站简单表单）。

---

## 六、已核验排除的误报

- `browse.ts` 的 `orderBy: { …, nulls: "last" }`：Prisma 6 类型支持 `SortOrderInput`，SQLite ≥3.30 支持 `NULLS LAST`——非问题。
- `sync.ts` 单飞返回同一 in-flight Promise（含 finally 清理）、`_syncTypeInner` 不 reject——正确。
- `market-snapshot.ts` 的 CASE UPDATE 绑定参数顺序与占位符逐个数对齐（2N+2N+1+N）——无错位。
- `kline.ts` 双向失败窗口判断（`lastFailed`/`lastChecked`）当前自洽（唯 CR-05 的头尾共键是新发现）。
- `chat/route.ts` 每轮重新 `trimContext`、工具循环耗尽后追加无 tools 收尾调用、assistant 单次落库——正确。
- `llm.ts` 尾帧 flush、tool_calls 按 index 拼装、name 仅首片赋值——正确（唯 CR-02 的 signal 语义是新发现）。
- `mcp.ts` 运行时挂 `globalThis`、in-flight 去重、exit hook、listTools 失败 kill 子进程——正确。
- `limiter.py`/`timeout.py`/`num.py`/`backup_db.py`——语义与单测一致，正确。
- `lru.ts`、`score.ts`、`search-text.ts`（FTS 引号转义）、`phases.ts`（脏数据过滤）、`time.ts`、`quote-enrich.ts`、`context-budget.ts` 整轮裁剪——未发现可触发缺陷。

---

## 七、覆盖清单

- **web 服务端**：`web/lib/*.ts`（31）、`web/app/api/**/route.ts`（20）
- **web 前端**：`web/app/**/*.tsx`、`web/app/components/*.tsx`
- **data-service**：`app/**/*.py`（providers/hotspot/research/utils/main/mcp_server/config）
- **脚本**：`web/scripts/*.mjs`、`scripts/smoke.mjs`
- **容器化/配置**：两侧 `Dockerfile`/`.dockerignore`、`docker-compose.yml`、`.gitignore`、`.gitattributes`、`.env.example`、`web/.env.example`、`mcp.json`
- **迁移与 schema**：`web/prisma/schema.prisma` + 全部 `migrations/**`
- **测试**：`web/lib/*.test.ts`、`data-service/tests/*.py`

---

# Invest Manager 代码审查报告（第二轮·全项目）

> **编号说明**：本报告（第二轮）使用命名空间 `CR7-*`——**前缀数字仅为避免与第一轮报告的 `CR-01…CR-22` 撞号，不代表轮次**；轮次以标题为准（本报告 = 第二轮）。与第一轮的 `V-x`（验收中新发现）、`G-x`（需求交付缺口）亦不冲突。
> **审查对象**：当前工作树（`dev`，HEAD=`4905095`，75 个未提交路径）。
> **审查方式**：全量逐文件通读——data-service 27 个源文件（5.5k 行）+ `web/lib` 29 个非测试文件 + 21 个 `route.ts` + 18 个 tsx + `PLAN.md`（R1–R17 / M1–M8 / C 系列）+ 容器化与迁移。每条发现回代码用 `grep`/`sed` 取行号证据。
> **两条纪律**：① **不采信注释与文档中的"已修复"**，以当前代码实际行为为准；② **本轮未运行任何测试/构建**，故文中引用的"140/140 全绿"等是**第一轮报告「五、验收结论」记录的文档值**，非本轮实测。
> **去重**：已显式避开第一轮报告的「二、可优化项」（1–9）与「三、需求交付缺口」（G1–G7）已登记条目。
> **状态**：⏳ **全部未修复，待主人逐项决策**（本轮仅出报告，未改任何代码）。

## 处置总览

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
| **CR7-14** | P3 | 文档/注释漂移：`PLAN.md:257` 优化点 3 已被 `Lru` 推翻；`providers/__init__.py` 注释与注册表语义不符 | 文档同步纪律 | 见下「CR7-14 逐项」 |

## 详述 · P1

### CR7-1（P1）· 技术分析师 `dataBased` 恒为真，破坏「辩论仅采信有真实数据支撑角色」
- **现象**：`engine.py:133` 为 `analysts.append({"role": "技术分析师", "dataBased": True, **r1})`——**硬编码 True**；另两个角色都有真实数据门控：`:154` `bool(r2.get("dataBased")) and fund_available`、`:175` 同理 `news_available`。
- **根因**：A 方案补基本面维度时只给 r2/r3 加了 `*_available` 门控，r1 漏了（`payload["kline"].get("ok")` 从未参与判定）。叠加两层放大：`:189` 用 `dataBased` 筛辩论输入、`:249` 归一化时 `a.get("dataBased", True)` 又对缺失字段**默认 True**。
- **影响**：K 线不可用时 `_compact_kline` 只送"（K 线不可用）"，模型仍可能给出 view → 被当作有数据支撑 → **进入多空辩论并成为 `:224` 评级依据**。直接违反 PLAN「M5 落地定稿·话语约束强化」与 R16（失败/缺口不得渲染成有据结论）。属本项目反复出现的「修复只做了一半」类（C11→CR4-4、CR4-6→CR5-3）。
- **次要问题**：`{..., "dataBased": True, **r1}` 的 spread 在最后，若模型自行返回 `dataBased` 字段会覆盖硬编码值——而该角色 prompt 并未要求输出这个字段，语义随机。
- **建议**：与 r2/r3 对称改为 `bool(r1.get("dataBased", True)) and kline_available`，并把 spread 调整为 `{...r1, dataBased: ...}`。按 C34 做反向验证（临时置 `kline` 不可用 + 断言该角色不出现在辩论输入里）。

### CR7-2（P1）· `/api/kline` 日期格式契约不匹配 → `days` 参数静默失效
- **现象**：`adapter.py:123` 以 `start=_iso_days_ago(120)`、`end=_today_iso()` 回读 web `/api/kline`，而 `:32`/`:36` 两个函数都 `strftime("%Y%m%d")`（无连字符）。web 侧 `kline.ts:90-92` 的 `normalizeRange` 只接受 `/^\d{4}-\d{2}-\d{2}$/`，**不匹配即回落默认值**（`start=today-90`、`end=today`），既不报错也不写 `note`。
- **影响**：研报的 K 线/阶段维度**永远是 90 日口径**，`collect_kline_with_phases(days=...)` 整个参数是装饰品；「研报与详情页归因同源」这一契约在窗口长度上并不成立（详情页可切 1Y，研报恒 90d）。因两侧都有数据返回，集成测试不会失败——与 **V1 同族**（跨语言日期格式无断言守护）。
- **建议**：① `adapter` 侧改传 ISO 带连字符；② 更根本的是让 `normalizeRange` 区分「参数缺失」（回落）与「格式非法」（返回 `{error}`），否则任何调用方写错格式都是静默降级。补一条断言：研报回读请求的 `start` 必须等于 `days` 推得的日期。

## 详述 · P2

### CR7-3（P2）· G3/R13 交付成「零调用方的端点」
`main.py:112` 定义 + `chain.py:45` 实现 + `test_g3_crosscheck.py` 8 项，但 **web 全仓 grep `quote/verified` / `verify_metric` / `crossChecked` 命中 0**：无 BFF 路由、无 UI 消费、不在 MCP 工具集、也不是 L1 工具参数。R13 原文要求「差异超阈值时**显式标注来源与偏差**」——"标注"需出现在用户可见路径。批次 D 自订原则：每项**实现**或**显式裁剪**，不留模糊态。
**需主人定调**（三选一）：接详情页现状区（低成本，但每次多一发外部请求）/ 作为 `get_quote` 的可选 `verify` 参数（仅 Agent 路径）/ 把 R13 改写为"验证能力已具备、暂不接入生产链路"并同步 PLAN 与 G3 处置标记。

### CR7-4（P2）· 港股三处消费侧断链
| 断链点 | 证据 | 后果（4707 只新标的） |
|---|---|---|
| Agent 无法寻址 hk | `tools.ts:35,54,73` 枚举为 `stock/fund/bond/crypto`，`:116` 有 `us` 无 `hk` | 用户问"腾讯控股现在多少钱"时 schema 层不给 hk 选项 |
| 身份区无 hk/us 模板 | `profile.ts:58-81` 仅四个分支，其余落到 `:84` | 详情页「一句话画像」恒为"暂无画像数据（字段缺失）" |
| 币种从未落地 | provider 已返回 `currency`（hk=HKD / us=USD / sina-bond=CNY），但 `grep -rn currency web/app web/lib` **零命中**，`data-service.ts` 的 `Quote` 类型也没有该字段 | 港股在列表与详情页显示成无单位数字（100 实为 100 港币），与 R8/R12 的「标注来源」同级要求缺口 |

### CR7-5（P2）· ChatUI 180s 上限静默截断（违反 R17）
`ChatUI.tsx:321` `let terminated = false;` **此后从未被赋值**（仅 `:323` 读取）——死守卫，与 CR5-1「负缓存恒假」同类。deadline 到点退出 while 后直接 `reader.cancel()` + `finally`，既不 `setError` 也不提示"回答可能不完整"，界面回到可输入态，用户看到的是一半的 assistant 回答被当作正常结束。R17 要求"长时运行态必须可退出、且如实呈现"。

### CR7-6（P2）· GET 取数端点无 code 校验 → 可被耗尽外部额度
`CODE_SET = /^[\w.-]{1,20}$/` 目前只用在 `watchlist` 与 `research/start`。`/api/kline`（`route.ts:10-13` 只判非空）与 `/api/quote` 把任意 `code` 直传 data-service → 落到 `_em_get`/`_em_request`，**每次消耗一个 `min_interval=5s`、`rate_per_min=12` 的源族名额**。`checkRequestOrigin` 只挂在 POST 上，而用户浏览任意网页时页面内的 `<img>`/no-cors GET 即可持续消耗该额度，与 R15 的目标（用户侧永不空白）直接冲突。**建议**：GET 侧同口径校验，非法 code 在进令牌桶之前 400。

### CR7-7（P2）· 启动补跑冲突（同步挤掉热点）
`sync_scheduler._catch_up_if_needed`（`:98-112`，sleep 8s）与 `hotspot/scheduler._catch_up_if_needed`（`:92-118`，sleep 5s）在同进程同时起跑，**共用东财一个令牌桶**。同步侧的分页取数 + 各类型快照批量会长时间占满 `min_interval=5s`，而 pipeline 的 `_EM.acquire(timeout=15)`（`:159`、`:255`、`:498`）拿不到名额即抛 `cooling down`，同时 `HOTSPOT_PIPELINE_TIMEOUT_S=300` 预算被等待吃光 → 当日热点产出为 `degraded`（板块名单/成分映射缺失）。触发条件很日常：**错过 02:00 后白天才启动服务**。建议二者串行（或热点优先、同步延后），或在同步窗口内给 pipeline 预留额度。

### CR7-8（P2）· 场外基金净值表缓存"成功但空"
`akshare_provider.py:350-358` 只要 `_ak_request` 不抛异常就写 `_fund_nav` + `_fund_nav_ts`；`:362-369` 对 `len(df)==0` 或**定位不到"单位净值"列**时 `return {}`——无 `note`、无失败计数、不进冷却，而那份额外全市场表会在 30 分钟内让**所有场外基金静默失去净值**。与 C11（kline 的"空响应必须进失败窗口"）口径不一致；且该表列名是中文后缀匹配，正是最易被上游改列名打断的位置。**建议**：空表 / 列缺失 → 记 `_fund_nav_fail_ts` 并抛 `ProviderError`（走显式降级）。

## 详述 · P3

- **CR7-9**：`market/refresh/route.ts:7` 注释"stock 约 2.9 万只 → 单类型即数分钟"把量级安错了类型——实测 `Progress.md:195` 为 `fund 27811 / stock 5913 / bond 1052 / crypto 250`。按代码参数（`BATCH=100` + 每批 1 发 EM 令牌 + 5s 间隔）推算 5 类型串行约 15 分钟起、熔断日 40 分钟+；而路由声明 `maxDuration=800`、`sync_scheduler.py:67` 的 `requests.post(timeout=1800)` 会**把已成功的同步记为失败**（`lastDate` 仍置位故不重跑，仅状态失真）。建议实测一次总耗时再定这两个数，不要按注释 tuning。
- **CR7-10**：`main.py:259` `/sync/run` → `run_now` 在请求线程内同步跑完整同步（15min+），占 uvicorn 线程池；热点在 M4 已改成 `request_run`（认领后后台线程 + 立即返回，并修过"线程内二次 single_flight 致 running 永久卡死"）。同类操作两种口径。
- **CR7-11**：回归盲区与修复热点不重叠。`web/lib` 有 23 个 test 文件，但缺 `llm.ts`（C3 尾帧 flush、CR-02 连接/空闲双超时语义、CR4 name 仅首片）、`tools.ts`（`numOrNull` 是 C4 唯一防线、9 个工具的降级分支）、`hotspots.ts`（`(date,title)` 去重 + CR-11 的 P2002 竞态分支）、`browse.ts`/`quote-enrich.ts`。`data-service/scripts/backup_db.py` 的 **C22 三条加固（integrity_check / `-wal -shm` 还原 / 失败回滚）无任何自动化回归**，而它是全项目唯一会破坏性覆盖线上库的脚本。
- **CR7-12**：`timeout.py:66-70`——`t.is_alive()` 判定与 `box["_abandoned"] = True` 赋值之间，若采集线程刚好跑完其 `finally`（此时读不到该标志，故不递减），主线程随后 +1 → 计数**只增不减**，CR-22 的 20 阈值告警会被缓慢推高。仅影响观测，不影响降级功能。
- **CR7-13**：`hk_provider.py:287` 的 `range(2, pages + 1)` 无页数上限（对照 `akshare_provider.py:785` 有 `min(pages, 100)`），若上游把 `total` 返回成异常大值会长时间捶打源族；`mcp_server.py:91` 的 `list_products` 对 hk 会**无超时**地跑约 4 分钟（外部 MCP 客户端视角是卡死）。
- **CR7-14 逐项（文档/注释漂移，不改行为但会误导下一次改动）**：
  1. `PLAN.md:257`「M7 已知优化点 3：进程内缓存无上限——技能缓存、`_news_cache`/`_fund_report_cache` 等为无界 Map」已被 `data-service/app/utils/lru.py` + `Lru(512)/Lru(256)` 落地推翻，条目应删或改记为「已闭环」。
  2. `providers/__init__.py` 注释称 openbb 为"美股 provider"，但 `us` 是经 `register_chain(position=0)` 注册的，`_QUOTE_REGISTRY` 内并无 `us`——`get_provider("us")` 会 `KeyError` 而 `get_provider_chain("us")` 正常，命名与注册表语义易误读（`_primary()` 依赖 `[0]` 即源于此）。
  3. 上一轮读码已报、**至今未处理**的两条：`Progress.md` **完全没有 09-19/20 这一轮的记录**（最新日志停在 09-17 CR5，`grep '09-19|09-20|批次 D'` = 0，git 显示该文件未修改），而按 `MEMORY.md` 的文档同步纪律，结论应进 Progress.md；`PLAN.md` 工作树副本仍**删除了 C18–C23 / C26–C34 的完整定义**（−145/+31），这些标着"后续修改不得回退"的约束现在只存在于 `git show HEAD:PLAN.md`。
  4. `.claude/settings.local.json` 与 `.workbuddy/memory/MEMORY.md` 属工具配置/记忆，不入本轮范围。

## 已核验排除（本轮怀疑过但证伪，勿重复提）
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

## 建议处置顺序（待主人批准）
1. **CR7-1、CR7-2**（产出错误、零设计变更，各配反向验证）；
2. **CR7-5**（R17 缺口，改动局限于一个组件）；
3. **CR7-4**（G6 收尾：三处消费侧接通，含 `Quote.currency` 类型补齐）；
4. **CR7-6**（校验前移，一行式改动）；
5. **CR7-7 + CR7-8 + CR7-9 + CR7-10** 合并为一次「额度与调度」改动，改前须实测同步总耗时；
6. **CR7-3 需先定调**（补接入 / 改写 R13 / 裁剪）后再排期；
7. **CR7-11** 建议紧随 1–3 补上（P1 两项都应有回归防线，按 C34 反向验证口径）；CR7-12/13/14 择机顺带。
