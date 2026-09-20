# 优化计划（第一轮代码审查产出）

> 依据 [code-review.md](code-review.md) 制定。执行进度见 [code-review-fix-progress.md](code-review-fix-progress.md)。
> **原则**：最小改动、按风险排序、可独立验证；不改需求功能（需求缺口单列，由决策确定补/裁）。
> **验证门槛**（每批后）：`npx tsc --noEmit` 0 错 + `npm test`（vitest）全绿 + 受影响集成套件全绿；data-service 侧改动加跑对应离线测试。
> **纪律**：测试失败最多重试 3 次，仍失败即停止并沟通。
>
> **执行状态：✅ 四批（A/B/C/D）全部完成 + 双服务全量集成验收通过。** 详见下「执行结果」。
>
> ⚠️ **本行的"全部完成"仅覆盖本报告（第一轮）。** **第二轮·全项目**的修复执行方案（`CR7-1…CR7-14`，分 A/B/C/D 四批）见文末同名标题——**状态 ⬜ 未开始，含 5 项待主人拍板的决策项**。

---

## 执行结果（2026-09-19/20）

### 批次完成情况

| 批次 | 项 | 状态 | 本批验证 |
|---|---|---|---|
| **A** | A1–A6（CR-01/02/03/12/13 + CR-15 零风险项） | ✅ 完成 | tsc 0 错 / vitest 101→135 |
| **B** | B1–B8（CR-04/05/07/08/09/11/16/19） | ✅ 完成 | tsc 0 错 / vitest 135 / ds 离线全绿 |
| **C** | C1–C9（CR-06/10/14/17/18/22 + CR-15 其余 + CR-20 评估） | ✅ 完成 | tsc 0 错 / vitest 125 / ds 离线全绿 |
| **D** | G1–G7 需求缺口处置（G2/G3/G4/G5/G6 实现，G1 裁剪，G7 部分） | ✅ 完成 | tsc 0 错 / vitest 135 / ds 离线含 test_g6_hk、test_g3_crosscheck |

### 决策项落地（用户确认）

| 决策项 | 用户选择 | 落地 |
|---|---|---|
| B1 `busy_timeout` | `connection_limit=1` | `prisma.ts#datasourceUrl` 注入；失败不再永久缓存 |
| B5 快照 null | 保留旧值 | `market-snapshot.ts` 改 `COALESCE(新值, 旧值)` |
| B4/G7 写鉴权 | Origin 校验（轻量） | `request-origin.ts` + 三端点；完整鉴权留上云前 |
| G1 webhook | 显式裁剪 | PLAN M1 划除 + 决策记录 |
| G2/G3/G4/G5/G6 | 全部实现 | 见上「批次完成情况」 |

### 验收中新发现并修复的 2 个缺陷（计划外，集成才暴露）

- **V1（高）** `upsertCandles` 原生 INSERT 日期格式与 Prisma 不一致 → KlineDaily 日期范围查询漏行 → 修复 + `kline-date-format.test.ts` + 反向验证。
- **V2（中）** G2 自动同步用降级备源缩小主数据（转债 1052→329）→ 加「降级缩水保护」+ `sync-shrink.test.ts` + 反向验证。

### 最终验证（全绿）

| 套件 | 结果 |
|---|---|
| `npx tsc --noEmit` | ✅ 0 错 |
| `npx vitest run` | ✅ **140/140**（24 文件） |
| 集成 verify-all（7 套件） | ✅ 全 exit=0：test-db 16、test-p1 20、test-p2 38、test-p3 27、test-p4 19、test-p5 21、test-p6 21 |
| 冒烟 smoke.mjs | ✅ 7/8（第 6 项容器内 health 于本地开发态不适用） |
| data-service 离线 | ✅ 42+6+10+18+9+8+15+7 全绿 |

### 未闭环 / 前置项

- **G7 完整身份鉴权**：上云/`WEB_PORT` 对外前必补（当前单机无暴露面；B4 的 Origin/Referer 校验已拦浏览器跨站简单表单）。
- **G6 港股连通性**：✅ 已闭环（本地验证通过）——排障发现三处实现缺陷（依赖 akshare 硬编码 CDN 节点 / 列表分页缺失 / 行情误用列表接口），已修复并补腾讯备源；详见 [code-review.md](code-review.md) V3 与「本地环境验证」。
- 集成套件依赖双服务启动（非 CI 自动）。

---

## 批次划分

| 批次 | 目标 | 项 | 风险 |
|---|---|---|---|
| **A** | 高价值/应急、低风险 | CR-01、CR-02、CR-03、CR-12、CR-13、CR-15(零风险项) | 低 |
| **B** | 中风险，需设计判断 | CR-04、CR-05、CR-07、CR-08、CR-09、CR-11、CR-16、CR-19 | 中 |
| **C** | 收尾/一致性/优化 | CR-06、CR-10、CR-14、CR-17、CR-18、CR-20、CR-21、CR-22、CR-15 其余、可优化项 | 低-中 |
| **D** | 需求缺口（需先决策） | G1–G7 | 取决方案 |

---

## 批次 A：高价值低风险修复

### A1 · 会话历史 tool 配对修复（CR-01，P1）
- **做法**（`web/lib/chat.ts` 的 `getMessages` 或 `web/app/api/chat/route.ts` 组装处）：
  - 重建历史时**丢弃无法配对的 tool 消息**（前面没有声明其 `tool_call_id` 的 assistant(tool_calls)），或丢弃缺 `toolCallId` 的 tool 行；
  - `tool_call_id` 缺失兜底由常量 `"call"` 改为"跳过该条"；
  - `PUT /api/chat/sessions` 对 `role:"tool"` 强制要求 `toolCallId`（否则 400）。
- **验证**：新增单测（构造"窗口首条为孤儿 tool""assistant 有 tool_calls 但 tool 缺失"两种历史，断言发给 LLM 的消息无孤儿）。
- **风险**：低。

### A2 · LLM 流超时语义修正（CR-02，P1）
- **做法**（`web/lib/llm.ts:90-107`）：连接超时只约束**握手/首字节**——用 `AbortSignal.timeout(CONNECT_TIMEOUT_MS)` 单独控 `fetch` 的**响应头到达**（acquire `res`），拿到 `res.body` 后**清掉该 timeout**，body 读取仅由 `IDLE_TIMEOUT_MS` 空闲看门狗 + 用户 `opts.signal` 约束。
  - 实现要点：不能用同一个 signal 覆盖整段流；可在 `fetch` 前设一个短时 timer，`await fetch()` resolve 后 `clearTimeout`；body 阶段改由 `withIdle` 保护。
- **验证**：单测/手测——模拟"header 快、body 持续吐字 >60s"，断言不被中途 abort；模拟"header 迟迟不回"，断言 60s 超时。
- **风险**：低（改动集中，有现成 `withIdle`）。

### A3 · running 复用分支登记 watcher（CR-03，P1）
- **做法**：`web/lib/research.ts:145` 的 `else` 分支 `return` 前调用 `watchResearch(type, code, watcherSessionId)`，与 409 路径一致。
- **验证**：新增单测（库内存在未陈旧 running + 传 `watcherSessionId`，断言已登记）。
- **风险**：极低。

### A4 · `mcp.stopAllMcp` 竞态加固（CR-12，P3）
- **做法**：`web/lib/mcp.ts:537-546` 增加"停止代际"标记（如 `rt.generation++`），`ensureConnected` 完成后若代际已变则丢弃结果并 `client.stop()`；`stopAllMcp` 不置 `connecting=null`（或置后由代际判定防复活）。
- **验证**：单测（连接进行中调用 `stopAllMcp`，断言最终 state 非 connected、子进程被 kill）。
- **风险**：低（当前仅测试调用，生产不受影响）。

### A5 · `callMcpTool` 降级语义修正（CR-13，P3）
- **做法**：`web/lib/mcp.ts:469-508`——先按已加载的 `rt.tools` 判定工具是否存在于**任一**已配置 server；若存在但其 server degraded/未连接 → 返回"该 MCP 源当前不可用（已降级）"而非"未知 MCP 工具"；仅当所有已配置 server 都无此工具名时才报"未知"。
- **验证**：单测（server 降级时调用其工具 → summary 含"不可用/降级"）。
- **风险**：低。

### A6 · 低危打包（CR-15 中的零风险项）
- `.gitignore` 补 `*.db-wal`、`*.db-shm`（CR-15 / 原 CR6-07）。
- `web/scripts/db-stat.mjs:4` 移除不存在的 `syncState`（或建表，见 D）。
- `web/lib/context-budget.ts` 移除 `overflow` 死变量；`data-service/.../tasks.py:187` 移除 `_ = started`。
- `web/lib/kline.ts:86-89` 移除死条件。
- **验证**：tsc 0 错 + vitest 全绿 + data-service 离线全绿；`git status` 无 WAL 噪声。
- **风险**：无。

---

## 批次 B：中风险（需设计判断/确认）

### B1 · busy_timeout 真正覆盖连接池（CR-04）
- **候选**（需确认）：
  1. **推荐**：`DATABASE_URL` 追加 `?connection_limit=1`——单连接使 PRAGMA 覆盖唯一连接；SQLite 写本就串行，但**需实测读请求排队对 TTFB 的影响**。
  2. 每次查询前经 `$extends` 中间件设 PRAGMA（有开销）。
  3. 仅保留 WAL（读不阻塞写），接受 busy_timeout 不完整，文档化。
- **附带修复**：`ensureSqlitePragmas` 失败不应永久缓存结论（允许下次重试）。
- **验证**：并发压测（一边 `/api/market/refresh`，一边反复 GET 详情页），确认无 SQLITE_BUSY。
- **风险**：中（方案 1 影响读并发）。

### B2 · kline 头/尾缺口拆分复查窗口（CR-05）
- **做法**：`web/lib/kline.ts` 的 `lastChecked` 由单一 key 拆为 `lastCheckedHead` / `lastCheckedTail`（或头部分支写独立 key），使头补不再压制尾增量。
- **验证**：单测/集成——库内 [90d,今天-1] 场景请求 1Y 区间，断言同时补齐头尾。
- **风险**：中（限流窗口语义，需回归 R15 保护）。

### B3 · 长请求 `maxDuration` + 超时（CR-07）
- **做法**：`/api/sync`、`/api/market/refresh` 显式设 `maxDuration`（与 `/api/hotspots/run:11` 口径一致）；评估是否需"同步中"返回（当前靠单飞串行）。
- **验证**：路由编译 + 现有测试全绿。
- **风险**：中（涉及部署平台限制）。

### B4 · 写端点鉴权（CR-08 / G7）
- **做法**：为 `/api/sync`、`/api/market/refresh`、`/api/hotspots/run`、`/api/research/start`、`/api/chat/sessions` 增加**共享密钥/Origin 校验**（复用 `INGEST_TOKEN` 模式或新增 `ADMIN_TOKEN`）；至少加 Origin/Referer 校验防 CSRF 简单表单。
- **验证**：无 token 请求被拒；带 token 通过。
- **风险**：中（需与前端调用点同步传 header）。

### B5 · 快照 null 覆盖语义（CR-09）
- **做法**：确认业务后二选一——① `COALESCE(新值, 旧值)` 保留旧值（推荐，防劣化）；② 保持清空。
- **验证**：单测（price 有值/changePct null → 只更新 price）。
- **风险**：中（语义变化）。

### B6 · 热点去重加唯一索引（CR-11）
- **做法**：评估为 `HotspotDigest` 加 `@@unique([date, title])` + ingest 改 upsert（需迁移；注意历史重复行需先清理）。当前 `_single_flight` 已缓解，可择机。
- **验证**：迁移应用 + test-db/p3 回归。
- **风险**：中（迁移）。

### B7 · 热点 pipeline 超时预算覆盖全流程（CR-16）
- **做法**：`run_pipeline` 把 `deadline` 传入 `fetch_news`（限制各源看门狗总预算）与 `structure_topics`（LLM 超时取 `min(60, 剩余预算)`）；或对 `run_pipeline` 整体套看门狗。
- **验证**：单测——构造 `HOTSPOT_PIPELINE_TIMEOUT_S=1` + 慢源（monkeypatch），断言整体在预算内返回并标注降级。
- **风险**：中（涉及 pipeline 主流程）。

### B8 · 场外基金净值表加失败负缓存（CR-19）
- **做法**：`akshare_provider._fund_nav_table` 增加 `_fund_nav_fail_ts` 与冷却窗口（对齐 `crypto_provider.CG_FAIL_COOLDOWN` 模式），失败写入、成功清零。
- **验证**：单测——失败后冷却期内二次调用不再触发外部请求（并做反向验证，防"死代码"）。
- **风险**：低。

---

## 批次 C：收尾 / 一致性 / 优化

- **C1 · CR-06**：data-service 回调日期改用北京时间（`TZ=Asia/Shanghai` 已设，但代码用 `date.today()`）→ 统一为北京时间日期，消除"昨天"错位；补回归测试。
- **C2 · CR-10**：接通 `pickEventDates`——`fetchEvents` 增加 `candles`/`phaseEndDates` 入参或在页面侧过滤，落地 R11 设计。
- **C3 · CR-14**：为 `/api/research/start` 增加可选 `sessionId` 透传或文档显式说明（口径统一）。
- **C4 · CR-15 其余项**：逐个评估（kline 批量写、N+1、search 候选偏斜、PUT 长度上限、watchers TTL、llm decoder 收尾、DELETE 错误码、rebuildFts 日志、进程内单飞多副本说明、research-target 误判）。
- **C5 · CR-17**：转债备源交易所归属改为显式传递 `sh/sz` 前缀，不依赖数字前缀推断。
- **C6 · CR-18**：`sina_bond_provider` 刷新失败沿用旧快照时，在响应 `note`/`source` 标注"数据陈旧"。
- **C7 · CR-20**：评估每日限额单一权威源（建议 data-service `_daily_done` 为主、web 库为持久兜底），消除双侧重复判断。
- **C8 · CR-22**：provider 端点看门狗线程加计数并暴露到 `/health` 或日志阈值告警。
- **C9 · 可优化项 1–7**：随其它改动顺带处理。

---

## 批次 D：需求交付缺口（✅ 已决策并执行，见上「执行结果」）

> 下表为**计划期建议**（决策依据留档）。**实际决策**：G2/G3/G4/G5/G6 实现、G1 裁剪、G7 部分实现（Origin 校验）——见开头「执行结果」与 [code-review.md](code-review.md) 第三节「处置结论」。

| 编号 | 缺口 | 建议 | 优先序 |
|---|---|---|---|
| **G2** | 产品主数据无自动同步 | **补**（APScheduler 增每日 sync，或 web 侧定时） | 高 |
| **G6** | `hk` 类型无 provider | **实现港股源** 或 **移除枚举** | 高 |
| **G7** | 写接口无鉴权 | **补**（= B4，上云前必做） | 高 |
| **G1** | M1 webhook 推送未实现 | **补** 或 **裁剪** | 中 |
| **G3** | R13 生产层双源交叉验证未落地 | **补**（与 R15 限流需协调） | 中 |
| **G4** | M2 LLM 兜底召回未实现 | **补** 或 裁剪 | 低 |
| **G5** | Watchlist 只读不通写 | **补**（API+UI）或 裁剪 | 低 |

> 每项：**实现** 或 **显式裁剪（并更新 PLAN）** 二选一，不留"声明了但没做"的模糊态。

---

## 执行顺序建议

1. **批次 A**（半天内，零/低风险，其中 CR-01/CR-02 是 P1 应立即修）。
2. **批次 B** 需先确认 B1/B5 方案再实施。
3. **批次 C** 择机顺带。
4. **批次 D** 先决策，按 G2>G6>G7>G1>G3>G4>G5 推进。

---

## 待确认项（✅ 均已由用户决策，见上「决策项落地」）

1. ~~**B1**：`connection_limit=1` 还是仅文档化？~~ → **已决策：`connection_limit=1`**
2. ~~**B5**：快照缺失时保留旧值还是清空？~~ → **已决策：保留旧值（COALESCE）**
3. ~~**G 组**：实现还是裁剪？~~ → **已决策：G2/G3/G4/G5/G6 实现，G1 裁剪，G7 部分（Origin 校验）**
4. ~~是否立即执行批次 A？~~ → **已执行（A/B/C/D 四批全部完成）**

---
---

# 优化计划（第二轮代码审查产出 · `CR7-*`）

> **依据**：[code-review.md](code-review.md) 后半部「Invest Manager 代码审查报告（第二轮·全项目）」的 14 项发现（`CR7-1…CR7-14`）。执行进度记到 [code-review-fix-progress.md](code-review-fix-progress.md) 新增的第二轮章节。
> **原则**（与第一轮一致）：最小改动、按风险排序、每项可独立验证、不改需求功能——需要改**需求口径**的项单列为决策项，不夹带进代码改动。
> **验证门槛（每批完成后）**：`npx tsc --noEmit` 0 错 + `npx vitest run` 全绿 + 受影响集成套件全绿（`node web/scripts/verify-all.mjs`）；data-service 侧改动加跑对应离线测试。**开发期不跑 `npm run build`。**
> **反向验证（C34）**：下表标 🔁 的项，须**临时回退修复 → 确认新断言精确失败 → 恢复后通过**，并把失败原文记进 progress（本轮 P1/P2 有 7 项适用）。
> **重试纪律**：测试失败最多重试 **3** 次（PLAN.md R9 现行口径；本文件第一轮头部原写 2，已于 2026-09-20 对齐为 3。`.workbuddy/memory/MEMORY.md:13` 仍写 2，见 D4-⑤）。
> **约束继承清单**（改前逐条自查）：C1 空载荷保护 · C9 浏览器只与 web 通信 · C11 空响应进失败窗口 · **C17/C27 进程内单例挂 `globalThis`** · C21/C30 禁止裸 `float()`/非有限值 · C26 跨类型唯一键含 `type` · C29 限速按逻辑请求计次 · C34 负缓存对称 + 反向验证。
> ⚠️ 前置：C18–C23 / C26–C34 的完整定义当前**只存在于 `git show HEAD:PLAN.md`**（工作树副本已删除）——先做 **D4-①** 恢复，否则后续改动无法自查约束。
> **状态**：⬜ **未开始**，待主人批准批次与决策项。

## 批次划分（总览）

| 批次 | 目标 | 项 | 风险 | 前置 |
|---|---|---|---|---|
| **A** | 产出正确性（P1 + R17 缺口） | A1=`CR7-1`、A2=`CR7-2`、A3=`CR7-5` | 低 | 无（建议先 D4-①） |
| **B** | 需求闭环（**须先决策**） | B1=`CR7-3`、B2=`CR7-4` | 低–中 | 主人选定 B1 方案、B2c 文案 |
| **C** | 额度与调度（**须先实测**） | C1=`CR7-7`、C2=`CR7-8`、C3=`CR7-9`、C4=`CR7-10`、C5=`CR7-6` | 中 | C0 实测同步总耗时 |
| **D** | 回归防线 / 观测 / 文档 | D1=`CR7-11`、D2=`CR7-12`、D3=`CR7-13`、D4=`CR7-14` | 低 | D4-① 建议最先做 |

---

## 批次 A：产出正确性

### A1 · 技术分析师 `dataBased` 加真实数据门控（`CR7-1`，P1）🔁
- **做法**（`data-service/app/research/engine.py:120-133`）：
  1. 新增 `kline_available = payload["kline"].get("ok")`（与 `:137` `fund_available`、`:161` `news_available` 同构）；
  2. append 改为 **spread 在前、门控字段在后**：`analysts.append({**r1, "role": "技术分析师", "view": r1["view"], "dataBased": bool(r1.get("dataBased", True)) and kline_available})`——顺带修掉"`**r1` 在后会覆盖硬编码值"的顺序问题；
  3. `:249` 归一化默认值 `a.get("dataBased", True)` → `bool(a.get("dataBased"))`（**fail-closed**：现有三处角色都显式赋值，行为不变；只防未来新增角色漏赋值时默认"有数据"）。
- **验证**：新增离线测试 `data-service/tests/test_cr7_engine_databased.py` 3 项——① kline 不可用 → 技术分析师不进 `debate_input.analysts` 且出现在「缺口说明」；② kline 可用 → 正常进；③ 模型自返 `dataBased:false` 时不被翻真。反向验证：临时改回 `True` → ①精确失败。
- **风险**：低（纯判定，不改 LLM 调用次数与预算）。

### A2 · 研报回读 `/api/kline` 的日期契约（`CR7-2`，P1）🔁
- **A2-①（必做，低风险）**：`data-service/app/research/adapter.py:30-36` 的 `_iso_days_ago` / `_today_iso` 由 `strftime("%Y%m%d")` 改为 `"%Y-%m-%d"`（web `normalizeRange` 的契约）。**注意勿误改** `ak_stock_disclosures`（`:304-305`）——akshare 入参确实要紧凑 8 位；在两个函数上各加一行注释标明"web 契约=带连字符 / akshare 契约=8 位"。
- **A2-②（建议，需确认）**：`web/lib/kline.ts:86-99` `normalizeRange` 区分「参数缺失」（回落默认）与「格式非法」（返回 `{error}`）。行为变更：`/api/kline?start=20260101` 由静默回落变 400。现有调用方（`ProductCharts`、`page.tsx`、修后的 `adapter`）都传 ISO，不受影响。
- **验证**：web 侧扩 `kline.test.ts`（非法格式 → error；缺失 → 回落）；ds 侧断言 `collect_kline_with_phases` 发出的 `start` 含 `-`（monkeypatch `requests.get` 捕获 params）。反向验证：改回 `"%Y%m%d"` → ds 断言失败。
- **风险**：A2-① 低；A2-② 中（改公共校验语义，须过 test-p2 38 项回归）。

### A3 · ChatUI 180s 中断必须可感知、有出口（`CR7-5`，P2，R17）
- **做法**：`web/app/chat/ChatUI.tsx:321-349`——① 删/真正使用 `terminated`（现为只读不写的死守卫）；② 在 `done` 事件处置 `gotDoneRef.current = true`；③ while 退出后若 `!gotDone` 则 `setError("回答在 180s 处中断，本条可能不完整——可直接重新发送")`（保留已渲染内容，给出重发出口）；④ 为可测性把判定抽成零依赖纯函数 `web/lib/chat-stream-exit.ts`（`{gotDone, expired}` → `interrupted`），**与 `research-stale.ts` 同一套路**（客户端组件不得 import 牵连 prisma 的模块）。
- **验证**：新增 `chat-stream-exit.test.ts`（done+未到期=正常 / 未 done+到期=中断 / 未 done+未到期=异常退出）。前端组件行为手测一次：把 deadline 临时调到 3s 触发。
- **风险**：低。

---

## 批次 B：需求闭环（**先决策后动手**）

### B1 · R13 双源交叉验证：接入 or 改判（`CR7-3`，P2）
现状：`/quote/verified` + `verify_metric` 已实现并有 8 项离线测试，但 **web/MCP/工具三层零调用方**。三选一：
| 方案 | 做法 | 代价 |
|---|---|---|
| **①（推荐）详情页按需核对** | 现状区加「双源核对」按钮 → 新 BFF `GET /api/quote?verify=1` → `/quote/verified`，偏差写入展示的 `note` | 每次多 1 发备源请求，受 R15/C29 额度约束；须"按需"不得默认开 |
| ② 仅 Agent 侧 | `tools.ts` 的 `get_quote` 增可选 `verify?: boolean`（默认 false），LLM 需要核验时才走 | 用户界面看不到"标注"，R13 的"显式标注"仅体现在回答文本 |
| ③ 改判不接入 | 把 PLAN R13 与 `code-review.md` G3 的 ✅ 更正为「能力已具备、未接入生产链路」并说明理由 | 零代码；但 R13 交付度下降 |
- **验证**：选 ①/② 则 test-p2 增一条断言（构造偏差 > 阈值 → `note` 含"双源偏差"）；选 ③ 仅文档同步。
- **需主人拍板**：①/②/③。

### B2 · 港股消费侧接通（`CR7-4`，P2）
- **B2a 工具枚举**：`web/lib/tools.ts:35,54,73,116` 四处 `enum` 各写各的（`hk` 全缺、`us` 只在两处）→ 抽 `export const PRODUCT_TYPE_ENUM = ["stock","fund","bond","crypto","hk","us"]` 单一来源，四处共用。**须核对 test-p4 19 项**（P4 兼容红线只锁工具**名**不锁 enum，但 LLM 行为可能变化）。
- **B2b 身份画像**：`web/lib/profile.ts:58-81` 补 `hk`（交易所=HK、币种、市值/PE/PB）与 `us` 分支；`profile.test.ts` 加 2 项（港股标的不为"暂无画像数据"）。
- **B2c 币种落地**：`web/lib/data-service.ts` 的 `Quote` 类型补 `currency?: string`（provider 侧 `hk_provider`/`openbb_provider`/`sina_bond_provider` 早已返回该字段，只是 TS 契约漏了）→ 详情页现状区/指标卡、搜索结果、`tools.ts` 的 `toolGetQuote` summary 在 `currency ∉ {CNY, null}` 时追加单位。**待确认文案**：`419.00 港币` / `HK$419.00` / `419.00 HKD`。
- **验证**：单测 + 手测一只 `00700` 详情页；test-p2 增"港股身份区非空且含币种"1 条。
- **风险**：低；B2a 需回归 test-p4/test-p6。

---

## 批次 C：额度与调度（**先实测 C0**）

### C0 · 前置实测（不改代码）
记录一次 `POST /api/sync`（全 5 类型）与 `POST /api/market/refresh?type=fund` 的**分类型耗时**与令牌桶占用（`/sync/status` 的 `results[].tookMs` + `snapshot updated=/failedBatches=`），作为 C1/C3/C4 的参数依据。第一轮报告里的"约 15 分钟起"是本轮按参数**推算**值，不得当作实测。

### C1 · 启动补跑冲突（`CR7-7`，P2，R15/R10）
- **做法**（择一，倾向 a）：**(a)** `sync_scheduler._catch_up_if_needed` 触发前查 `GET /hotspots/status`，若热点 pipeline 正在跑或当日尚未产出 → 延迟到其结束后再跑同步（同进程内也可直接读 `limiter.get_limiter("eastmoney").state()` 判忙）；**(b)** 把同步补跑改为"仅当 web 侧当日 `Product.updatedAt` 早于今天"才跑（需 web 暴露只读状态端点，改动更大）。禁止引入跨进程锁（单进程即可）。
- **验证**：扩 `test_cr6_pipeline.py` 一条"源族被占用时 pipeline 仍在 `HOTSPOT_PIPELINE_TIMEOUT_S` 预算内返回并标注降级"；手测：清 `lastDate` 后同时起双服务，观察热点是否仍降级。
- **风险**：中（涉及调度时序）。

### C2 · 场外基金净值表：空/列缺失必须进失败窗口（`CR7-8`，P2，C11）🔁
- **做法**：`akshare_provider.py:338-369`——① `_fund_nav_table` 拿到 `None`/`len(df)==0` 时视同失败：写 `_fund_nav_fail_ts` 并抛 `ProviderError`（不得缓存空表 30min）；② `_fund_nav_quotes` 定位不到"单位净值"或"日增长率"列时**上抛**而非 `return {}`（列名变更是上游契约破坏，必须显式降级并带 `note`）。
- **验证**：`test_p2_m8.py` 增 2 项（空 df → 冷却生效且不发第二次全表请求；列缺失 → ProviderError）。反向验证：回退 → 断言失败。
- **风险**：低。

### C3 · `/api/sync` 时长与超时口径（`CR7-9`，P3，依赖 C0）
- **做法**：① 按 C0 实测重设 `web/app/api/sync/route.ts:8` 的 `maxDuration`（或注明"自托管下仅声明性"）与 `data-service/app/sync_scheduler.py:67` 的 `timeout=1800`（建议 ≥ 实测 P95 × 1.5）；② 修 `web/app/api/market/refresh/route.ts:7` 的注释事实错误（"stock 约 2.9 万只" → 实为 `fund 27811 / stock 5913 / bond 1052 / crypto 250`，见 `Progress.md:195`）；③ 读超时不得直接记"失败"——改为 `note: "回调超时，同步可能仍在 web 侧完成，请查 /api/sync 结果或 Product.updatedAt"`（现状会把已成功的同步写成 error，且 `lastDate` 已置位不再重跑，状态失真）。
- **风险**：低（③ 属语义更正）。

### C4 · `/sync/run` 异步化（`CR7-10`，P3）
- **做法**：照 `hotspot/scheduler.request_run`（`:68-85`）改 `sync_scheduler.run_now`——认领 `running` 后起后台线程、立即返回 `{accepted}`；线程启动失败须回滚 `running`（CR4 已有同类修复）。同步更新 `main.py:259` 的返回体与 `README`/PLAN 的端点说明。
- **验证**：`/sync/status` 的 `running` 转换可观测；手测 `POST /sync/run` 立即返回。
- **风险**：中（状态语义变化，消费方仅运维/手动）。

### C5 · GET 取数端点 code 校验前移（`CR7-6`，P2，R15）
- **做法**：抽 `web/lib/validate.ts` 的 `isValidCode()`（正则沿用 `^[\w.-]{1,20}$`，与 `watchlist`/`research/start` 统一），在 `api/kline/route.ts`、`api/quote/route.ts` 于**调用 data-service 之前** 400（当前只判非空 → 任意串都会消耗一发东财令牌）。同时给 `type` 加白名单。
- **验证**：`validate.test.ts` + 两个路由的边界断言（非法 code 不产生 dsGet 调用——用注入/spy 或断言响应码）。
- **风险**：低（需确认无现存调用方传带前缀代码，如 `sh600519`——正则含 `.`/`-` 但不含下划线前的市场前缀？实测各源均用纯数字/字母代码）。

---

## 批次 D：回归防线 / 观测 / 文档

### D1 · 补回归盲区（`CR7-11`，P3）
- `web/lib/llm.ts`：SSE 尾帧 flush（C3）、连接超时只约束首字节 / 空闲超时逐块（CR-02）、`tool_calls` name 仅首片赋值（CR4）——三条语义目前**只靠集成测试间接覆盖**。
- `web/lib/tools.ts`：`numOrNull`（**C4 唯一防线**：缺价不得上报 0 元）、9 个工具的成功/降级双分支。
- `web/lib/hotspots.ts`：`(date,title)` 200 字截断去重 + P2002 竞态分支（CR-11）。
- `data-service/scripts/backup_db.py`：**C22 三条加固（integrity_check / `-wal -shm` 还原 / 失败回滚）目前零自动化回归**，而它是全项目唯一破坏性覆盖线上库的脚本——用 tmp 目录构造库 + 损坏备份做离线测试。

### D2 · `_abandoned` 计数竞态（`CR7-12`，P3）
`timeout.py:66-70`：`t.is_alive()` 判定与置 `box["_abandoned"]` 之间线程跑完 `finally` → 只增不减。改为由 runner 在 `finally` 内用 `threading.Event`/标志位统一裁决（或主线程 +1 后二次确认 `is_alive()`）。仅影响 CR-22 观测可信度，低优先。

### D3 · 分页与慢路径护栏（`CR7-13`，P3）
`hk_provider.py:287` 加分页上限（对照 `akshare_provider.py:785` 的 `min(pages, 100)`），超限抛 `ProviderError`；`mcp_server.py:91` 的 `list_products` 对 `hk`/超大列表加显式耗时说明或经 `run_with_timeout` 包裹（外部 MCP 客户端视角不应表现为无响应卡死 4 分钟）。

### D4 · 文档失同步（`CR7-14`，P3）——**建议最先做 D4-①②**
1. **恢复 `PLAN.md` 的 C18–C23 / C26–C34 定义**（现只存在于 `git show HEAD:PLAN.md`；工作树副本 −145 行未恢复）。PLAN 自定"唯一需求来源"，这些标着"不得回退"的约束不在其中即失效。
2. **`Progress.md` 补记** 09-19/20 那一整轮（第一轮审查 + 批次 A/B/C/D + V1/V2/V3 + G6 本地验证闭环）**与本轮（第二轮）**——当前最新日志停在 09-17 CR5，`grep '09-19|09-20|批次 D'` = 0。
3. `PLAN.md:257`「M7 已知优化点 3：进程内缓存无上限」已被 `utils/lru.py` + `Lru(512)/Lru(256)` 推翻 → 改记「已闭环」。
4. `data-service/app/providers/__init__.py` 注释与实际注册语义对齐（`us` 经 `register_chain(position=0)`，`_QUOTE_REGISTRY` 内无 `us` → `get_provider("us")` 抛 `KeyError` 而 `get_provider_chain("us")` 正常）。
5. `.workbuddy/memory/MEMORY.md:13` 重试次数 2 → 3（与 R9 对齐）。

---

## 执行顺序建议

1. **D4-①②**（恢复约束与补进度，使后续改动可自查 C 系列）；
2. **批次 A**（P1 优先，A1/A2 各配 🔁；半天内可完成）；
3. **批次 B**——待主人定 B1 方案与 B2c 文案；
4. **C0 实测 → C1/C2/C3/C5 → C4**（额度与调度一次改齐，避免反复试）；
5. **D1**（紧随 A/B 补上：本轮 P1 两项目前都只有新写的测试在守，回归面要成对）；D2/D3/D4-③④⑤ 择机顺带。

## 待确认项（请主人拍板后我再动手）

1. **B1**：R13 走 ①（详情页按需核对，推荐）/ ②（仅 Agent）/ ③（改判不接入）？
2. **B2c**：币种展示文案——`419.00 港币` / `HK$419.00` / `419.00 HKD`？
3. **A2-②**：`normalizeRange` 是否改为"格式非法即 400"（推荐，但属公共语义变更）？
4. **C4**：`/sync/run` 是否值得异步化（当前仅运维手动用）？
5. **批次范围**：是否只做 A + D4-①②，把 B/C 留到下一轮？

## 本轮不做（显式排除，避免反复讨论）

- `CR7-*` 之外的**已核验排除 8 项**（见 `code-review.md` 第二轮节末表）——已证伪，不改。
- 第一轮「二、可优化项」中标 🔵 保留的 5 项（1/3/4/7/8）——维持原决策。
- **G7 写接口完整身份鉴权**：上云 / `WEB_PORT` 对外前再补（当前单机无暴露面）。
- **C31 Dockerfile 进程降权验证** 与任何 Docker 相关改动：按主人指示暂不推进。
