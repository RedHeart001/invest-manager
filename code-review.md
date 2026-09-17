# 第四轮全项目 Code Review（2026-09-15，修复完成 2026-09-16）

> **范围**：web/app 路由与页面层、web/lib + 脚本层、data-service Python 侧（三路并行审查 + 高优发现逐条人工验证）。
> **与前序关系**：项目已经过 3 轮 review（C1–C25 约束固化、O 系列 12 项优化全部执行）。本报告**不含已修复/既定约束项**，全部为第四轮新发现。
> **结论**：无 P0；P1 × 5、P2 × 12、P3 × 25。**功能现状可用**，各项为加固/优化。
> 编号记为 CR4-x（第四轮）。
>
> **最终状态（2026-09-16）**：**42 项全部处理完毕**——非 Docker 的 41 项已落地并经代码 grep 逐条核验 + 全量验证通过；仅 **#6（Dockerfile 进程降权）代码已写但按主人指示暂不推进 Docker 验证**。可复用规则已固化进 PLAN.md **C26–C33**，进度见 Progress.md 09-15/09-16 日志。

## 修复状态总览

| 分级 | 数量 | 状态 | 验证 |
|---|---|---|---|
| P1 | 5 | ✅ 全部修复 | 代码核验 + 集成套件 |
| P2 | 12 | ✅ 全部修复 | 代码核验 + 集成套件 |
| P3 | 25 | ✅ 24 项修复 + ⏸ #6 待 Docker 验证 | 代码核验；#18/#1 另做离线验证 |

**最终验证（全绿）**
- 静态/离线：tsc **0 错** / vitest **73/73** / data-service 离线 test_p2_m8 23 + test_p6_mcp 7 + test_p6_fund_report 15 / 迁移已应用
- 双服务集成实测：test-p1 **20/20**、test-p2 **38/38**、test-p3 **27/27**、test-p4 **19/19**、test-p5 **21/21**、test-p6 **21/21**、test-db **16/16**
- 过程记录：test-p5 首跑 1 失败（"当日已完成标的直接复用"）= 当天研报尚未生成的**时序**（非回归，生成后复跑 21/21）；test-p2 前次「分钟线 502」= 东财限流外因，本轮已恢复 38/38

**P3 逐项落地说明**

- ✅ **#1 openbb 代理注入**：核实 **yfinance 1.7.0 `Ticker` 原生支持 `session`**（此前"不支持"的评估有误）→ `_overseas_session()`（trust_env=False + 显式 proxies）注入全部 quote/kline/news；离线验证 `HTTPS_PROXY` 注入生效
- ✅ **#18 sourceUrls 按 topic 相关性**：新增 `_topic_urls()`（topic 标题+板块名与新闻 title+summary 的**字二元组**重叠打分取前 3，无命中回退首 3）；离线验证各 topic 命中各自新闻
- ✅ **#2/#3/#4/#5/#7/#8/#9/#10/#11/#12/#13/#14/#15/#16/#17/#19/#20/#21/#22/#23/#24/#25**：均已落地（明细见下文各条）
- ⏸ **#6 Dockerfile 降权（未验证）**：容器默认用户保持 root，仅 uvicorn 经 `setpriv` 降到 **uid 1000**（与 web node 同号，共享卷归属不受影响；setpriv 缺失回退 root 并告警）。**按主人指示暂不推进 Docker**——此项是全项目**唯一未经任何验证的改动**，启用前需 `docker compose build data-service && docker compose up -d` 并确认容器内进程 uid、两容器 healthy、`compose exec` 备份正常

---

## P1（5 项，全部修复）

### CR4-1 研报唯一键缺 type → 跨类型串研报（已实测确认）

- **证据**：[web/prisma/schema.prisma:66](web/prisma/schema.prisma#L66) `@@unique([code, date])`；[web/lib/research.ts:121-129](web/lib/research.ts#L121-L129)（findUnique 只按 code+date）、:162-166 / :198-211（upsert 同键，update 会覆盖 `type` 字段）
- **实测**：Product 表中 `000001` 同时存在 **平安银行（stock）** 与 **华夏成长混合（fund）**（A股与基金代码段大量重叠）
- **触发场景**：
  1. 在 `/product/fund/000001` 触发深度分析 → 落库 `(code=000001, date=今天, type=fund)`；
  2. 打开 `/product/stock/000001`，`getLatestReport(type=stock)` 查不到 → 显示"启动深度分析"；
  3. 点击后 `startResearch` 的 findUnique 命中**基金那行** → 返回基金研报 → **华夏成长的研报渲染在平安银行页面上**（反之亦然）。同日双类型 ingest 时后到的 upsert 直接改写对方行，先到研报静默丢失。
- **修复方案**：唯一键改 `@@unique([type, code, date])`（生成 migration，现有库先去重再建索引）；`startResearch` / `ingestResearch` / `getLatestReport` 的 where 条件全部加 `type` 作用域。

### CR4-2 sina_provider 裸 float() → NaN 进 6h 缓存，/kline 持续 500（C21 漏网）

- **证据**：[data-service/app/providers/sina_provider.py:58-70](data-service/app/providers/sina_provider.py#L58-L70)
- **问题**：`_series()` 对 open/high/low/close/volume 用裸 `float()`，`except (TypeError, ValueError)` **拦不住 NaN**（`float(nan)` 不抛异常），`close is None` 检查也不拦 NaN。NaN 进入 candles 后被**缓存 6 小时**（:73），期间每次经 sina 备源的基金 K 线请求，Starlette 序列化（`allow_nan=False`）抛 ValueError → 500。C21 明确禁止"K 线行裸 float()"，兄弟 provider 均已改，此处漏改。
- **触发场景**：akshare `fund_etf_hist_sina` 返回含 NaN 的行（停牌日等，pandas 数据极常见）。
- **修复方案**：改用 `to_float`（`app/utils/num.py` 现成，参考 `sina_bond_provider.py:79-94`），任一字段为 None 则跳过该行。

### CR4-3 MCP stdio 进程生命周期两个姊妹缺陷

- **证据**：[web/lib/mcp.ts:359-360](web/lib/mcp.ts#L359-L360)（ensureConnected）、[mcp.ts:119-151](web/lib/mcp.ts#L119-L151)（StdioClient.connect）
- **问题**：
  1. **子进程崩溃后永不重连**：`ensureConnected` 首行 `if (rt.client) return rt.client` 不检查活性；`alive` getter（:115）全项目只在 `connect()` 内部使用。子进程退出后 exit 回调只置 `closed=true` 并 reject in-flight，`rt.client` 仍指向死连接、`rt.state` 仍显示 `"connected"`。
  2. **握手失败泄漏子进程**：`connect()` 中 spawn 后若 `initialize` 超时/被拒，函数直接抛错，**已 spawn 的子进程无人 kill**；每次冷却（默认 60s）重试再 spawn 一个，长期运行累积孤儿进程。
- **触发场景**：① stdio server 崩溃/OOM → 所有 `mcp_*` 工具永久返回"连接已关闭"，状态面板仍显示 connected，需重启 web；② 配置了启动慢/握手不兼容的 server → 每 60s 泄漏一个进程。
- **修复方案**：
  1. `ensureConnected` 改为 `if (rt.client && (rt.client instanceof HttpClient || rt.client.alive)) return rt.client;`，否则 `rt.client.stop(); rt.client = null;` 后走重连流程（受 RETRY_COOLDOWN 约束）；
  2. `connect()` 内对 initialize 包 try/catch，失败时 `this.stop()`（kill 子进程）再向上抛。

### CR4-4 K 线头部缺口"成功但空响应"不设窗口标记（C11 漏网路径）

- **证据**：[web/lib/kline.ts:227-241](web/lib/kline.ts#L227-L241)
- **问题**：头部缺口分支（`minCached > start`）只检查 `withinFailWindow`（lastFailed），**不查 lastChecked**；回源成功只写 `lastChecked`（:235）而本分支不读它，空响应也不写 `lastFailed`。C11 修复覆盖了"回源失败进失败窗口"（catch 分支 :238）与整段回源的空响应（:206-210），但头部缺口"成功返回空/部分数据"这条路径漏了。
- **触发场景**：上市不足 1 年的基金/转债，用户选 1Y 区间——上游只返回已有历史，`minCached`（上市日）永远 > start，**每一次详情页加载都整段回源头部缺口**，持续捶打东财（R15 限流防线漏洞）。
- **修复方案**：头部缺口分支与尾部增量对称，加 `recentlyChecked`（lastChecked）判断；或对空响应 `lastFailed.set(cacheKey, Date.now())`（与整段回源分支口径一致）。

### CR4-5 东财限速器按 host 尝试计次 → 单次逻辑请求可触发全源族熔断

- **证据**：[data-service/app/providers/akshare_provider.py:177-194](data-service/app/providers/akshare_provider.py#L177-L194)（`_em_get` 2 轮 × 3 host）+ [:81-93](data-service/app/providers/akshare_provider.py#L81-L93)（`_em_request`）；kline 路径 :393-417 同构
- **问题**：每个 host 尝试都独立 `acquire()` + `on_failure()`。一次用户请求最多计 6 次失败；`failure_threshold=2` 意味着只要前两个 host 抖动（注释自承"单次成功率非 100%"），**全源族熔断 180s+**，期间所有东财请求直接 502 降级。同时多次 acquire 的 min_interval 等待串行叠加，极端情况超过 BFF 30s 超时；多 host 重试与熔断计次互相打架，第 3 个 host 几乎永远轮不到。
- **修复方案**：以"逻辑请求"为单位获取一次额度、回报一次结果——把多 host 循环包在单个 `_em_request` 闭包内（循环内部做状态码/JSON 校验，整体成功才 `on_success`）。

---

## P2（12 项，全部修复）

### 1. 工具循环跑满后，最后一轮工具结果被静默丢弃

- **证据**：[web/app/api/chat/route.ts:144-211](web/app/api/chat/route.ts#L144-L211)
- **问题**：`MAX_TOOL_ROUNDS = 4`。若第 4 轮模型仍请求工具：工具被执行、结果 push 进 messages、写入 SSE status 事件——但循环随即结束，**没有任何一轮把这些结果发给 LLM 做总结**，也无"已达上限"提示。用户看到工具都跑了，最终回答却只有截至第 3 轮的引导文本（常为空）。
- **修复方案**：循环结束后若 `lastToolCalls` 非空，追加一次不带 `tools` 的 `chatStream` 收尾调用（强制模型基于已有结果作答），或至少 `send("warn", { message: "已达工具调用上限" })`。

### 2. /api/chat 最终 assistant 消息重复落库

- **证据**：[route.ts:176-183](web/app/api/chat/route.ts#L176-L183) 与 [:213](web/app/api/chat/route.ts#L213)
- **问题**：工具轮内已逐轮 `safeAppend("assistant", roundText, { toolCalls })`（:183），循环结束后 :213 又把**历轮拼接的** `assistantText` 整体再写一次 → 中间轮文本在 DB 中存两遍。重新打开会话看到重复前缀；后续每轮对话的 LLM 上下文都携带重复文本（浪费上下文预算）。`lastToolCalls`（:177 赋值后从未使用）也暗示此处是未完成逻辑。
- **修复方案**：最终落库只写**最后一轮**的 roundText（在无工具调用的 break 分支记录 `finalRoundText` 并落库该值）；循环耗尽无终答时不再追加累积消息；顺带清理未用的 `lastToolCalls`（若按 P2-1 修复则被复用）。

### 3. CoinGecko 无失败负缓存，不可达时每次请求阻塞约 41 秒

- **证据**：[data-service/app/providers/crypto_provider.py:61-92](data-service/app/providers/crypto_provider.py#L61-L92)（`_request` 2 次尝试 × 20s 超时 + 1s sleep；`_fetch_markets` 仅成功才写 `_markets_ts`）
- **问题**：刷新失败后 `_markets_ts` 不更新，下一次请求立即重试全程。PLAN 已实测 CoinGecko 在当前网络不可达（R12），即**每个** crypto quote/kline/list 请求都占住 uvicorn 线程池 worker 约 41s；而 BFF 侧 `dsGet` 30s 超时，用户必见失败、worker 继续空烧。并发几个 crypto 请求即可显著消耗线程池。
- **修复方案**：参照 FamilyLimiter 思路加失败冷却（失败后 5–10 分钟内直接抛降级错误），或 `_markets_ts` 失败时也写入并区分 stale 复用。

### 4. LLM 流式读取无空闲超时，上游中途挂死会永久占住请求

- **证据**：[web/lib/llm.ts:86-97, 166-175](web/lib/llm.ts#L86-L97)
- **问题**：`fetch` 只有 `opts.signal`（路由层传 `req.signal`，仅客户端断开时触发）。LLM 供应商"连接已建立但停止吐字"（网关挂起、长 reasoning 卡顿）时，`reader.read()` 无限等待，SSE 请求与上游连接永久占用——对话永远停在转圈。
- **修复方案**：首字节设连接超时（`AbortSignal.timeout` 与 `opts.signal` 用 `AbortSignal.any` 合成）；读循环内加空闲看门狗（如 60s 无 chunk 即中止并走 SSE error 事件）。

### 5. tool_calls 的 function.name 累加拼装，供应商重复发全名时工具名损坏

- **证据**：[web/lib/llm.ts:150](web/lib/llm.ts#L150)
- **问题**：`acc.name += tc.function.name` 按 OpenAI 分片语义正确，但部分兼容端点（某些 GLM 版本/代理网关）在每个 tool_calls chunk 里**重复发完整 name**，累加得到 `get_quoteget_quote` → gateway 分派到"未知工具"。arguments 必须累加，name 宜"仅在为空时赋值"。
- **修复方案**：`if (tc.function?.name && !acc.name) acc.name = tc.function.name;`

### 6. 研报 running 状态无陈旧恢复 + 前端无限轮询

- **证据**：[web/lib/research.ts:127-129](web/lib/research.ts#L127-L129)（`existing?.status === "running"` 直接原样返回，不看 updatedAt）；[ResearchPanel.tsx:72-80, 106-112](web/app/product/[type]/[code]/ResearchPanel.tsx#L72-L80)（轮询只在 status≠running 时停，无上限）
- **问题**：data-service 任务注册表是**内存态**（PLAN M5 明确）；若其在任务执行中重启，任务与完成回调一起丢失，web 侧行永久停在 `running` → ① 该标的一整天无法再触发研究；② 打开详情页的每个客户端每 10s 轮询一次，永不停。
- **修复方案**：`startResearch`/`getLatestReport` 对 `running` 且 `updatedAt` 超过阈值（如 10 分钟，对齐 `RESEARCH_TASK_TIMEOUT_S` 480s + 回调节拍）的行按 failed 处理（写回 failed+error 或允许重新提交）；前端轮询加上限（如 10 分钟）后停止并提示。

### 7. ProductCharts 区间/对比加载无竞态防护

- **证据**：[web/app/product/[type]/[code]/ProductCharts.tsx:70-127](web/app/product/[type]/[code]/ProductCharts.tsx#L70-L127)
- **问题**：快速连点时间档位（或反复"叠加对比"）时多个 fetch 并发，完成顺序不定——后完成的旧请求会 `setKline/setPhases/setRangeKey/setCompare` 覆盖用户最后的选择；先到请求的 `finally` 提前 `setPending(false)`。同类问题在 search-client 已按 C13 用 `abortRef` 修复（search-client.tsx:113-116），此处漏改。
- **触发场景**：点「1Y」后立即改点「1M」，1Y 回源慢最后到达 → 界面定格在 1Y 数据 + 1Y 高亮，与用户操作不符。
- **修复方案**：照 search-client 模式加 `AbortController` ref（新请求 abort 旧请求，收尾仅当仍是当前请求），或单调递增请求序号丢弃过期响应。

### 8. ResearchPanel 轮询 interval 在卸载竞态下永久泄漏

- **证据**：[ResearchPanel.tsx:67-85](web/app/product/[type]/[code]/ResearchPanel.tsx#L67-L85)（初始 effect 内 async）、:106-112（trigger 内）
- **问题**：初始 effect 的 async IIFE 在 `await fetchOnce()` **之后**才 `setInterval`；cleanup 只清 `pollRef.current`。组件在首次 fetch 返回前卸载时，cleanup 先跑（pollRef 还是 null），随后 async 继续执行设置 interval——**再无人清理**，每 10s 轮询直到标签页关闭。`trigger()` 的 POST await 后同样无卸载检查。
- **修复方案**：effect 内加 `cancelled` 标志，await 后设置 interval 前检查；`trigger` 的轮询设置同样挂在带 cleanup 的 ref 生命周期上。

### 9. /api/quote 裸 fetch 无超时

- **证据**：[web/app/api/quote/route.ts:15-18](web/app/api/quote/route.ts#L15-L18)
- **问题**：全站其余 data-service 调用都走 `dsGet/dsPost`（内置 `AbortSignal.timeout`，data-service.ts:28/55），唯独此路由用裸 `fetch` 未传 `signal`。data-service 挂起时该请求悬挂到 OS TCP 超时（分钟级）。它是 P7 冒烟项之一，属正式 API 面。
- **修复方案**：加 `signal: AbortSignal.timeout(15_000)`，或直接改用 `dsGet`。

### 10. APScheduler 缺 misfire_grace_time，宿主机睡眠后当日任务静默丢失

- **证据**：[data-service/app/hotspot/scheduler.py:119-130](data-service/app/hotspot/scheduler.py#L119-L130)
- **问题**：APScheduler 3.x 默认 `misfire_grace_time=1` 秒、`coalesce=False`。宿主机（个人笔记本常态）在 08:30/16:30 处于睡眠时，唤醒后 job 被判 misfire 直接跳过；启动补跑 `_catch_up_if_needed` 只覆盖"服务重启"，不覆盖"睡眠唤醒"——盘前热点当天缺失且不补跑。
- **修复方案**：`add_job(..., misfire_grace_time=1800, coalesce=True)`（单飞锁已能兜住补跑与定时的并发）。

### 11. 线程 start 失败的两个状态泄漏点

- **证据**：[scheduler.py:74-79](data-service/app/hotspot/scheduler.py#L74-L79)；[research/adapter.py:83-87](data-service/app/research/adapter.py#L83-L87)
- **问题**：
  1. `request_run` 认领 `running=True` 后 `Thread.start()` 无保护——看门狗泄漏线程累积导致 OS 线程耗尽时 `start()` 抛 RuntimeError，`running` 永久卡 True（与上轮修复的死锁同症状，需重启）；
  2. `adapter._run_with_timeout` 在 `acquire()` 成功后才 `t.start()`，start 抛异常时信号量名额与 `_collect_live/_collect_inflight` 计数永久泄漏（释放逻辑在 `_target` 的 finally 里，线程根本没跑），4 次即耗尽全部采集名额。
- **修复方案**：两处 `t.start()` 均包 try/except——失败时分别回滚 `_state["running"]=False` / release 信号量并回滚计数。

### 12. 数值/健壮性小项打包（C21 同类漏网）

| 位置 | 问题 | 修复 |
|---|---|---|
| [hotspot/pipeline.py:394](data-service/app/hotspot/pipeline.py#L394) | 新浪板块涨跌幅裸 `float(pct)` → NaN 通过过滤，`sort` 对 NaN 比较结果未定，标题产出"XX领涨（+nan%）"污染落库 digest | 改 `to_float` 或补 `math.isfinite` |
| [crypto_provider.py:160-163, 101-116](data-service/app/providers/crypto_provider.py#L160-L163) | crypto K 线裸 `float(price)` + quote 原始 JSON 数值直出；上游返回非标准 `NaN`/`Infinity` 字面量时 → 序列化 500 | 统一过 `to_float` |
| [akshare_provider.py:423-435](data-service/app/providers/akshare_provider.py#L423-L435) | 东财 K 线行 `f = item.split(",")` 后直接取 `f[0]`–`f[6]`，上游截断/异常行 → IndexError 逃逸（非 ProviderError）→ 端点 500 | `if len(f) < 7: continue` |

---

## P3（25 项，逐条状态见下表）

> 状态：✅ 已修复并核验 ｜ ⏸ 代码已实现但未经验证（Docker）｜ 修复明细见各项"→"后的做法。

1. ✅ **openbb_provider 代理链路 dev 失效**：[openbb_provider.py:46-67](data-service/app/providers/openbb_provider.py#L46-L67) docstring 宣称"优先尝试环境代理"但无显式代理传递；`main.py:12-13` 的 `NO_PROXY=*` 使 yfinance 会话绕过一切 env 代理 → dev 下美股恒降级。→ **已修**：核实 yfinance 1.7.0 `Ticker` 原生支持 `session`，新增 `_overseas_session()`（trust_env=False + 显式 proxies）注入 quote/kline/news；离线验证代理注入生效（约束 C31 邻近项）。
2. ✅ **C17 漏挂（dev 环境）**：[events.ts:39](web/lib/events.ts#L39)、[kline.ts:49-50](web/lib/kline.ts#L49-L50) 的 LRU 缓存仍是模块级变量。HMR 后 `lastFailed` 限流窗口失效，叠加 CR4-4 形成突发回源。→ **已修**：按 gateway.ts 模式挂 `Symbol.for` globalThis（固化 C27）。
3. ✅ **trimContext 不计 system 体积**：[context-budget.ts:35-44](web/lib/context-budget.ts#L35-L44)：system（≈8K）在预算之外，实际峰值超预算约 1/3；硬截断只截 content，不处理 tool_calls.arguments。→ **已修**：`total` 以 `msgSize(system)` 初始化；新增 `shrinkMessage()` 对超限 tool_calls.arguments 一并截断。
4. ✅ **events 负缓存 TTL 与正缓存相同**（events.ts:68-97）：降级结果也"粘"10 分钟。→ **已修**：降级结果用 `DEGRADED_TTL_MS`(60s)。
5. ✅ **mcp.ts runtimeFor 无法 re-enable**（:336-345）：配置改回 `enabled: true` 后状态永远停 `"disabled"`；反向禁用时不停已运行的子进程。→ **已修**：hit 分支对称处理（可 re-enable 回 idle；禁用时 `client.stop()`）。
6. ⏸ **data-service Dockerfile 以 root 运行**；`.dockerignore` 未排除 `.env`。→ **部分已修**：`.dockerignore` 已补 `.env*`（✅）；Dockerfile 降权 **代码已实现但未经 Docker 验证**（`setpriv` 降 uid 1000，缺失回退 root；按主人指示暂不推进 Docker → 约束 C31）。
7. ✅ **tasks.py:69 WARNING 级调试日志**（含用户输入，P5 联调遗留）。→ **已修**：降为 `log.info`。
8. ✅ **backup_db.py 两处健壮性缺口**：restore 以读写模式打开备份（旁生 `-wal/-shm`）；校验失败残留损坏 dest。→ **已修**：改 `_connect_ro(backup_file)`；失败时 `os.remove(dest)`。
9. ✅ **跨产品导航 client state 残留（潜在）**：ProductCharts 用 `useState(initial…)` 无 props 重同步。→ **已修**：详情页 `ProductCharts`/`ResearchPanel` 加 `key={type:code}`。
10. ✅ **HotspotFeed trigger 轮询无卸载取消**（:143-173）。→ **已修**：循环内挂 `pollAliveRef`（固化 C32）。
11. ✅ **ECharts 无 resize 监听**。→ **已修**：注册 window resize 并在卸载时移除。
12. ✅ **/api/chat/sessions PUT 缺 role 运行时校验**（sessions/route.ts:24-43）。→ **已修**：`["user","assistant","tool"]` 白名单（固化 C33）。
13. ✅ **/api/search 无 q 长度上限**。→ **已修**：route 层 `slice(0,100)`。
14. ✅ **research start 缺 type/code 白名单校验**。→ **已修**：type 白名单 + code `[\w.-]{1,20}`。
15. ✅ **done 但 fullReport 超 200KB 被丢弃时 UI 状态矛盾**。→ **已修**：该分支渲染 summary + 说明，不再回到"启动深度分析"起始态。
16. ✅ **data-service rejected（非 todayDone）分支不登记 watcher**（research.ts:158-160，C8 承诺落空）。→ **已修**：该分支也 `watchResearch`。
17. ✅ **search-client 防抖窗口内旧响应瞬态写入**（search-client.tsx:142-181）。→ **已修**：cleanup 同时 `abort()` 在途请求。
18. ✅ **pipeline sourceUrls 各 topic 同质化**：所有 topic 都取相同的前 3 条新闻 URL。→ **已修**：新增 `_topic_urls()`（字二元组相关性打分，无命中回退首 3）；离线验证各 topic 命中各自新闻。
19. ✅ **engine.py:50 `_ask(..., timeout=120)` 死参**（从未传入 `chat_json`）。→ **已修**：`chat_json` 增加 `timeout` 参数，`_ask` 传入生效。
20. ✅ **pipeline `_tavily` 每次新建 Session 未关闭**。→ **已修**：`try/finally` 显式 `s.close()`。
21. ✅ **pipeline `finishedAt` 用裸 `datetime.now()`**，与模块 TZ 不一致。→ **已修**：改用 `datetime.now(TZ)`（Asia/Shanghai）。
22. ✅ **search-cache 内存 Map 无淘汰**。→ **已修**：换 `Lru(50)`。
23. ✅ **skills 缓存不清除已删目录**。→ **已修**：`loadSkills` 内清理 `root` 下不在当前扫描集里的缓存条目。
24. ✅ **sync 暂存表 `CREATE TABLE IF NOT EXISTS` schema 漂移风险**。→ **已修**：`ensureStageTable` 改 `DROP TABLE IF EXISTS` + `CREATE`（表名受 SYNC_TYPES 约束，无注入面）。
25. ✅ **verify-all.mjs 写 `verify-suites.txt` 未入 .gitignore**。→ **已修**：`.gitignore` 已加该条。

---

## 建议修复顺序（均已执行完毕，保留供追溯）

1. ✅ **P1 全修**：CR4-1（数据正确性）→ CR4-2（C21 漏网 + 缓存放大）→ CR4-3（进程生命周期）→ CR4-4（R15 防线）→ CR4-5（熔断口径）
2. ✅ **P2 用户可感知优先**：1（工具循环收尾）→ 2（重复落库）→ 6（running 陈旧）→ 7（图表竞态）→ 3（crypto 负缓存）→ 4（LLM 流超时）→ 其余 P2
3. ✅ **P3 全量**：25 项均处理（#6 Dockerfile 降权待 Docker 验证）
4. 回归门槛（本轮已达标）：`tsc --noEmit` 0 错 + vitest 全绿 + 受影响集成套件全绿；约束已固化进 PLAN.md C26–C33

## 本轮已核对无问题（防误报记录）

- C7 akshare 看门狗覆盖完整（全库 17 处调用点逐一核对）；C16 global 声明与信号量超时已落实；tasks.py RLock 已修；C22 备份校验/回滚已落实；所有 requests 调用均带 timeout
- C17 已挂 globalThis 的单例：sse clients、mcp runtimes、research watchers、market-snapshot inflight、gateway statusCache、sync inflight、prisma —— 均正确
- C3 SSE 尾帧 flush、tool_calls 按 index 拼装、C18 每轮重裁、工具循环上限 —— 已落实
- MCP in-flight 去重、请求级超时、白名单、工具名截断加哈希、${ENV} 占位 —— 均正确
- FTS 注入（双引号包裹 + 参数绑定）、XSS（无 dangerouslySetInnerHTML、react-markdown 无 rehype-raw、isSafeUrl 白名单）、分页/limit clamp —— 均安全
- C23 脚本污染：测试 deleteMany 均带 where 限定；fix-fts.mjs 可重复执行且安全
- ECharts dispose、SSE 取消（heartbeat 清理 + reader.cancel）、/api/health 与 /api/tools/status 的 C14 安全基线 —— 均落实

---

# 第五轮全项目 Code Review（CR5，2026-09-17，**仅审查、未修复**）

> **范围**：web/app 路由与页面层、web/lib 层、data-service Python 侧、Docker/编排/配置、既有测试脚本（单路串行通读 + 逐条人工验证）。
> **前置**：项目已经过 4 轮 review（C1–C33 约束 + O 系列 12 项 + CR4 的 P1×5/P2×12/P3×25）。本报告**只列第五轮新发现**，不重复既有约束项。
> **结论**：无 P0；**P1 × 2、P2 × 1、需求交付缺口 × 3、P3 加固 × 6**。前四轮修复质量高，本轮重点复查"多源链 / 缓存窗口 / 生命周期 / 降级路径"这些易留尾巴处，多数确已闭环。
> 编号记为 CR5-x。**本轮为只读审查，未改动任何源码/文档；修复方案待主人决策。**
>
> **编号口径变更（2026-09-17）**：原写作 `R5-x`，与 PLAN 既有**需求编号 R5**（加载反馈）冲突 → 经主人确认，第四、五轮审查编号全局改为 **CR4-x / CR5-x**（Code Review 前缀），需求编号 R5–R17 不变。本文件已同步；代码注释也一并修正（**已应用的 Prisma 迁移 `migration.sql` 内注释有意保留 `R4`**，改已应用迁移会致 `migrate deploy` checksum 报错）。

## 总览

| 分级 | 编号 | 一句话 | 状态 |
|---|---|---|---|
| P1 | CR5-1 | CoinGecko 失败负缓存从未写入 → CR4 修复实际失效，不可达时每请求仍空烧 ~41s | ✅ 已修 |
| P1 | CR5-2 | 研报**失败**广播被前端渲染成"已完成（中性）"假成功卡片 | ✅ 已修 |
| P2 | CR5-3 | 陈旧 `running` 研报在 UI 上是死路（CR4-6 只修了后端，前端无重试入口） | ✅ 已修 |
| 需求缺口 | CR5-D1 | R13（provider 层双源交叉验证）未实现，仅测试期断言 | ⏸ 暂不处理（需求 R13 保持原样） |
| 需求缺口 | CR5-D2 | M1 webhook 推送通道（企业微信/邮件）未实现 | ⏸ 暂不处理（需求条目保持原样） |
| 需求缺口 | CR5-D3 | M2 "FTS 无结果时 LLM 提关键词再查"未实现 | ⏸ 暂不处理（需求条目保持原样） |
| P3 | CR5-P1…P3、P5、P6 | 缓存未挂 globalThis / 错误码压平 / 入参无界 / 热点轮询漏刷新 / 依赖数组 | ✅ 已修（B 批） |
| P3 | CR5-P4 | 写接口无鉴权 | ⏸ 暂不处理（上云/`WEB_PORT` 对外前必须补） |

---

## P1（真实缺陷，建议优先修）

### CR5-1 CoinGecko 失败负缓存从未被写入 → CR4 的修复实际失效

- **证据**：[data-service/app/providers/crypto_provider.py:61-103](data-service/app/providers/crypto_provider.py#L61-L103)
  - `_markets_fail_ts` 仅在 `__init__`（[:64](data-service/app/providers/crypto_provider.py#L64)）置 0、在**成功**时置 0（[:102](data-service/app/providers/crypto_provider.py#L102)）；
  - 守卫 `if now - self._markets_fail_ts < CG_FAIL_COOLDOWN`（[:89](data-service/app/providers/crypto_provider.py#L89)）读取它——但**失败路径（`_request` 抛错，[:81](data-service/app/providers/crypto_provider.py#L81)）从不写入时间戳**，故 `_markets_fail_ts` 恒为 0，Unix 时间下该条件恒假。
- **问题**：第四轮 P2-3 声称"参照 FamilyLimiter 思路加失败冷却（失败后 5–10 分钟内直接抛降级错误）"并标记已修，但**负缓存是死代码，从未生效**。
- **影响**：CoinGecko 在当前网络实测不可达（PLAN R12 已记录）。此时**每一个** crypto `quote`/`kline`/`list` 请求仍会完整重试约 41s（`_request` 2 次 × 20s 超时 + 每次 sleep 1s），占住 uvicorn 线程池 worker——正是该修复要消除的问题。并发几个 crypto 请求即可显著消耗线程池，而 BFF 侧 `dsGet` 30s 超时必现失败、worker 继续空烧。
- **修复方案**：在 `_request` 失败抛出前（或 `_fetch_markets` 的调用点）写 `self._markets_fail_ts = time.time()`。注意 `_request` 被 quote/kline/list 共用，**负缓存粒度需明确**：建议把记账放到 `_fetch_markets` 的 except（市场列表是三者共同前置），或为 `_request` 增加"失败回调"参数按调用方分别记账。

### CR5-2 研报失败广播被前端渲染成"已完成"

- **证据**：
  - 后端失败分支广播 `{type, code, failed: true, error, sessionIds}`，**不含 `rating`/`summary`**：[web/lib/research.ts:252-271](web/lib/research.ts#L252-L271)
  - 前端监听器**不判断 `failed` 字段**，一律走成功分支：[web/app/chat/ChatUI.tsx:119-145](web/app/chat/ChatUI.tsx#L119-L145)（渲染在 [:133-139](web/app/chat/ChatUI.tsx#L133-L139)）
- **问题**：失败广播到达后，ChatUI 渲染 `📄 深度研究报告已完成：**${code}** 评级「${data.rating ?? "中性"}」`——`rating` 缺失回落 "中性"、`summary` 为空 → **发起会话实时看到一条"已完成 / 中性"的假成功卡片**。
- **影响**：服务端虽同时把 `failText` 落库（切走再回来能看到正确的失败文案，见 research.ts:255-262），但**实时那一条是错的**。金融场景把"研究失败"显示成"研究完成·中性评级"属可信度硬伤，与新固化的"失败必须显式、不粉饰"（C10/C19 精神）相悖。
- **修复方案**：ChatUI 的 `research` 监听器加 `if (data.failed) { 渲染失败说明 + error；return; }`；类型上把 `failed?: boolean; error?: string` 补进 `data` 断言。

---

## P2（真实缺陷）

### CR5-3 陈旧 `running` 研报是 UI 死路（CR4-6 只修了一半）

- **证据**：
  - 后端已能给出口：`startResearch` 对 `running` 且超过 `STALE_RUNNING_MS`(10min) 的行标记 failed 并允许重提（[web/lib/research.ts:135-145](web/lib/research.ts#L135-L145)）
  - 前端 `running` 分支**只有文案、无按钮**：[web/app/product/[type]/[code]/ResearchPanel.tsx:256-262](web/app/product/[type]/[code]/ResearchPanel.tsx#L256-L262)；触发按钮只在 `else`（起始态）分支（[:277-293](web/app/product/[type]/[code]/ResearchPanel.tsx#L277-L293)）
- **问题**：data-service 任务表是**内存态**（PLAN M5）；其在任务执行中重启会丢任务与完成回调 → web 侧行永久 `running`。CR4-6 给了后端"超阈值可重提"的能力，但前端在 `running` 时**没有任何可点入口**：轮询到上限（`POLL_LIMIT` 60 次 ≈ 10 分钟）只 `setError("研究状态查询超时…请刷新页面")`（[:88-91](web/app/product/[type]/[code]/ResearchPanel.tsx#L88-L91)），刷新后仍是 `running` 文案 → **用户被卡死**，须等次日或手动改库。
- **修复方案**：轮询超上限、或 `running` 分支检测到后端已可重提时，把 UI 切回"可重新提交"态（暴露 `trigger()`），并对 running 超阈值的展示"疑似中断，可重新发起"。

---

## 需求交付缺口（对照 PLAN，非代码 bug，建议澄清"实现 / 裁剪"）

| 编号 | PLAN 要求 | 现状 | 位置 |
|---|---|---|---|
| CR5-D1 | **R13**：关键行情指标（收盘价/净值）**在 provider 层**做双源交叉验证，差异超阈值显式标注来源与偏差，不做静默取舍 | **仅测试期有 quote↔kline 断言**；provider 层无运行时交叉校验、无偏差标注——多源链现在是"先成功即返回" | [PLAN.md:26](PLAN.md#L26)、[PLAN.md:396](PLAN.md#L396)；断言在 [web/scripts/test-p2.mjs:87](web/scripts/test-p2.mjs#L87) |
| CR5-D2 | **M1 推送为正式交付项**：② webhook 通道（企业微信/邮件，可配置开关） | 全仓无 webhook/企业微信/邮件代码与配置项；仅 ① 站内 SSE 完成 | [PLAN.md:99](PLAN.md#L99) |
| CR5-D3 | **M2 兜底**：FTS 无结果时 LLM 提取意图关键词再查 | 未实现；FTS+LIKE 无结果即返回空 | [PLAN.md:113](PLAN.md#L113)；[web/lib/search.ts:108-158](web/lib/search.ts#L108-L158) |

> 三项若属"有意裁剪"，建议在 PLAN 对应条目显式标注"未做/降级原因"，避免需求与实现长期口径不一致。

---

## P3（加固/优化，酌情）

1. **CR5-P1 缓存未挂 globalThis（C17/C27 漏网）**：[web/lib/score.ts:19](web/lib/score.ts#L19) 的 `tagCache`、[web/lib/skills.ts:46](web/lib/skills.ts#L46) 的 `cache` 仍是模块级 Map。dev HMR 会重置 → tags 解析缓存 / 技能 mtime 缓存失效（功能无碍，但与已固化约束口径不一致，且 O2 曾提技能缓存无界）。建议统一挂 `Symbol.for`。
2. **CR5-P2 错误码压平**：[web/app/api/quote/route.ts:21-27](web/app/api/quote/route.ts#L21-L27) 把 data-service 的 400（非法 type）/501（不支持）也映射为 **502**，前端无法区分"参数错"与"上游挂"。其余路由已按 501/502/503 分流，建议透传 `res.status`。
3. **CR5-P3 入参无界**：`/api/chat` 的 `message` 无长度上限（直接入库 + 送 LLM，[web/app/api/chat/route.ts:26-29](web/app/api/chat/route.ts#L26-L29)）；`/api/search/click` 的 `query/code` 无长度约束（[web/app/api/search/click/route.ts:13-20](web/app/api/search/click/route.ts#L13-L20)）。建议各加上限（如 2000 / 200 字符）。
4. **CR5-P4 写接口无鉴权**：`/api/sync`、`/api/market/refresh`、`/api/hotspots/run`、`/api/research/start` 无任何鉴权。单机当前可接受（compose 仅发布 web 端口、data-service 不发布），但若 `WEB_PORT` 暴露到局域网即成为触发重任务的 DoS 面。建议至少加 `INGEST_TOKEN` 同级的简单开关。
5. **CR5-P5 热点触发可能不刷新**：[web/app/HotspotFeed.tsx:148-180](web/app/HotspotFeed.tsx#L148-L180) 的轮询要求**先观测到 `running===true`** 才在结束时 `refresh()`；若 pipeline 在首个 3s 轮询前就完成（`sawRunning` 恒 false），循环直接 `break`，flash 停在"已提交后台抓取，执行中…"（8s 后自动消失）且不拉取结果——只能等 SSE 推或手动刷新。建议 `sawRunning` 为 false 时也 `refresh()` 一次。
6. **CR5-P6 依赖数组冗余**：[web/app/product/[type]/[code]/ResearchPanel.tsx:144](web/app/product/[type]/[code]/ResearchPanel.tsx#L144) 的 `trigger` 依赖含未使用的 `fetchOnce`（仅整洁问题）。

---

## 本轮已核对、确认无问题（防误报记录）

- 多 host 限速计次（C29/CR4-5）已正确包进单个 `_em_request`；`_em_get` / kline 的状态码 + JSON 校验均在闭包内（C6）。
- akshare 看门狗覆盖完整（akshare / tencent / sina / sina_bond / openbb / pipeline / adapter）；`to_float` 已在所有 provider 数值出口生效（全库 grep 无裸 `float()` 残留，仅 `utils/num.py` 内部一处合法调用）。
- C15 FTS 孤儿清理 + 暂存表 DROP、C20 同步单飞共享 Promise、C22 备份恢复校验/回滚/sidecar 还原、C17 globalThis（sse / mcp / kline / events / watchers / snapshot / sync / gateway）—— 逐条核对正确。
- `/api/kline` 头部缺口与尾部增量的窗口抑制已对称（C28/CR4-4）；`upsertCandles` P2002 按"已写入"处理。
- 前端竞态：`ProductCharts`（AbortController + 序号）、`search-client`（abort + 序号 + only-current 收尾）、`ResearchPanel`（cancelled 标志 + 轮询上限）、ECharts dispose + resize —— 均已落实（C32）。
- 注入面：FTS 查询参数绑定 + 双引号包裹、`isSafeUrl` 协议白名单、react-markdown 无 `rehype-raw`、research start 的 type 白名单 + code 正则（C33）—— 均正确。
- Docker：web base 阶段未设 `NODE_ENV`、裁剪在独立 `prod-deps` stage（C25）、双侧 `.dockerignore` 红线齐、compose 强制 `INGEST_TOKEN`、容器互访接线（`WEB_BASE_URL`/`WEB_API_BASE` 兼容）—— 符合 P7 定稿。
- MCP client：stdio 崩溃重连 + 握手失败清理子进程（CR4-3）、in-flight 去重、`${ENV}` 占位、工具名截断加哈希 —— 均正确。

## 建议处理顺序

1. **CR5-1**（负缓存死代码，直接推翻 CR4 结论，改动 ~3 行）
2. **CR5-2**（失败说成成功，可信度，改动 ~5 行）
3. **CR5-3**（陈旧 running 死路，UI 分支）
4. 澄清 **CR5-D1/D2/D3** 是"实现"还是"裁剪"
5. P3 逐条按收益排序

---

## 修复方案（CR5，待主人决策后实施；**本节仅为方案设计，尚未改动任何代码**）

> 统一验证门槛（沿用 R9 纪律与既有回归口径）：`tsc --noEmit` 0 错 + `vitest` 全绿 + 受影响集成套件（test-p2/p5 视改动而定）+ data-service 离线套件全绿；失败最多重试 2 次后停止沟通。

### CR5-1 修复方案（CoinGecko 失败负缓存）

**根因确认的补充（比原诊断更精确）**：`get_kline` / `get_quote` / `get_quotes` / `list_products` **全部先经** `_market_item` → `_fetch_markets()`（crypto_provider.py:105-110、112-113、140、193、208）。因此**在 `_fetch_markets` 的失败路径记账即可覆盖"CoinGecko 整体不可达"这一主导场景**——此前担心的"kline 仍空烧"不成立，kline 的第一步就落在 `_fetch_markets` 上。

**方案（推荐）**：

```python
def _fetch_markets(self) -> list[dict]:
    now = time.time()
    if self._markets is not None and now - self._markets_ts < MARKETS_TTL_SECONDS:
        return self._markets
    if now - self._markets_fail_ts < CG_FAIL_COOLDOWN:
        raise ProviderError("coingecko cooling down after recent failure; skip")
    try:
        self._markets = self._request("/coins/markets", {...})
    except Exception:
        self._markets_fail_ts = time.time()   # ← 新增：失败即进入冷却窗口
        raise
    self._markets_ts = time.time()
    self._markets_fail_ts = 0.0
    return self._markets
```

- **粒度选择**：放在 `_fetch_markets`（而非 `_request`）——`_request` 被 `market_chart` 共用，在 `_request` 内记账会让"仅 market_chart 失败"也污染市场列表缓存（误伤）。现方案语义精确。
- **残余缺口（可接受）**：`_fetch_markets` 成功但 `market_chart` 单独失败时无负缓存（每次 kline 仍重试 ~41s）。此路径在"网络不可达"场景下几乎不会走到（列表先挂），留作后续可选优化，不在本轮做。

**验证**：data-service 离线单测（新增/扩展 `tests/test_p2_m8.py` 或 crypto 专项）——monkeypatch `_request` 抛 `ProviderError`，连续调 `get_quote` 两次：断言第一次真实尝试、**第二次立即**抛 `cooling down`（不等待网络超时）；再用 `monkeypatch` 推 `time.time` 越过 `CG_FAIL_COOLDOWN`，断言可恢复重试。

**风险**：低。改动限于一个私有方法；失败冷却期最长 5 分钟，海外源本就不可达，可接受。建议同时把降级 note 明确为"冷却中，约 N 秒后重试"以便页面上可解释。

### CR5-2 修复方案（失败广播被渲染成"已完成"）

**根因**：广播 payload 与前端消费口径不对称——后端失败分支发 `failed:true`，前端只读 `rating`/`summary`（由 CR4 的"C8 失败也推送"补丁引入，属"补了一半"）。

**方案（推荐：前端最小收敛）**：

```ts
// ChatUI.tsx 的 "research" 监听器首行增加分支
const data = JSON.parse(...) as {
  type: string; code: string; failed?: boolean; error?: string;
  rating?: string; summary?: string; sessionIds?: string[];
};
const sid = sessionIdRef.current;
if (!sid || !data.sessionIds?.includes(sid)) return;   // 保留现有会话过滤
if (data.failed) {
  setItems((prev) => [...prev, mkMsg("assistant",
    `⚠️ 深度研究未能完成（**${data.code}**）：${data.error ?? "未知原因"}\n\n可稍后在详情页「深度分析」区重试。`)]);
  return;
}
// …原成功分支…
```

- **为什么不做"契约层判别联合"**（`{kind:"done"} | {kind:"failed"}`）：更干净，但触及 `broadcast` 调用方与类型定义，面更大；当前只有 ChatUI 一个消费点，最小收敛即可，判别联合留作后续重构。
- **注意保留** `sessionIdRef` 过滤（ChatUI.tsx:131-132）。
- **附带备注（非本次修）**：`HotspotFeed` 与 `ChatUI` 共用 `/api/hotspots/stream`，前者只监听 `digest` 事件故不受影响；但"一流多事件"的模式后续加事件时需留意消费者过滤。

**验证**：SSE 属运行时，SSR 覆盖不到。两条路径：
1. 手工：设 `RESEARCH_MAX_LLM_CALLS=0` 使引擎必失败 → 触发 → 断言会话内实时收到"未能完成"而非"已完成"；
2. 若可低成本在 test-p5 注入合成 `research` 事件（该套件已有 SSE 断言脚手架），补一条断言。

### CR5-3 修复方案（陈旧 running 是 UI 死路）

**根因**：后端已具备"running 超阈值可重提"能力（`STALE_RUNNING_MS`），但前端 `running` 是无出口终态——轮询到顶仅报错、无按钮。

**方案（推荐：前端按 `updatedAt` 判陈旧，叠加轮询到顶兜底）**：

1. `ResearchPanel` 的 `ReportRow` 类型补上 `updatedAt?: string`（`/api/research` 实际已返回该字段，见 `lib/research.ts` 的 `ReportRow.updatedAt`，只是前端类型没声明）。
2. 判定：`const stale = report?.status === "running" && report.updatedAt && Date.now() - new Date(report.updatedAt).getTime() > STALE_RUNNING_MS`。
3. 渲染：`running` 分支若 `stale` → 显示"疑似中断（执行方可能已重启），可重新发起" + 复用 `trigger()` 的按钮；否则维持"执行中…"。
4. 兜底：轮询到 `POLL_LIMIT` 时既有的 `setError(...)` 保留（不删），但把状态降级为可重提态。

- **常量复用**：`STALE_RUNNING_MS` 已从 `web/lib/research.ts` 导出，前端直接 import，避免两处阈值漂移。
- **不做"running 恒显示重试按钮"**：正常执行中给按钮语义暧昧（后端虽会以 running 判重拒掉、再续轮询，实际安全但不友好）。

**验证**：test-p2 补 SSR 断言——构造 `updatedAt` 为 20 分钟前的 running 行 → 详情页 SSR 含"重新发起"入口。纯 SSR 可覆盖，成本低。

### CR5-D1/D2/D3 方案与建议（需主人先定性）

| 编号 | 若要落地的推荐形态 | 代价 / 冲突 | 我的建议 |
|---|---|---|---|
| CR5-D1 R13 交叉验证 | **窄口径**：仅在"已有天然双数"的场景做运行时校验（如 quote 现价 vs 当日 K 线收盘），差异超阈值在响应 `note` 标注来源与偏差；**不**对每次 quote 都额外打备源 | 通用双源比对会让每次 quote 翻倍请求，**与 R15 限流直接冲突** | 按窄口径实现（低风险）；或显式记入 PLAN 为"降级为测试期验证" |
| CR5-D2 webhook 推送 | 在 `emit_ingest`（热点）/ research ingest 处挂一个可配置 webhook 分发（企业微信/邮件），含失败重试与开关 | 需外部凭据（webhook key）、失败重试语义、配置项；属"正式交付项" | 建议确认是否现在做；若不做则在 PLAN 标注裁剪 |
| CR5-D3 LLM 兜底召回 | `searchProducts` 空结果时，用 LLM 从 query 提取关键词再查一次 FTS/LIKE | 一次 LLM 调用（延迟 + 费用） | 建议确认是否要；搜索质量增强，非阻塞 |

### P3 修复方案（按收益排序，酌情）

1. **CR5-P1**：`score.ts` 的 `tagCache`、`skills.ts` 的 `cache` 换 `Symbol.for(...)` 挂 globalThis（与 C17/C27 口径一致）；`skills.cache` 可顺带换 `Lru` 加容量上限（O2 遗留）。**改动小、风险低**。
2. **CR5-P5**：`HotspotFeed.trigger` 轮询结束时，`sawRunning === false` 也执行一次 `refresh()`（覆盖"任务在首个轮询前就完成"）。**体验修复，1 行**。
3. **CR5-P2**：`/api/quote` 按 `res.status` 透传（400/501/502/503 分流），与其余路由口径一致。
4. **CR5-P3**：`/api/chat` 的 `message`、`/api/search/click` 的 `query`/`code` 加长度上限（如 2000 / 200）。
5. **CR5-P4**：对 `/api/sync`、`/api/market/refresh`、`/api/hotspots/run`、`/api/research/start` 加与 `INGEST_TOKEN` 同级的简单开关（默认关闭=兼容现状，开启即校验 header）。**单机可缓**。
6. **CR5-P6**：`ResearchPanel.trigger` 依赖数组移除未使用的 `fetchOnce`。**纯整洁**。

### 实施顺序建议（分两批）

- **A 批（真缺陷，1 次交付）**：CR5-1 → CR5-2 → CR5-3 + P5/P2/P3/P6 打包。门槛：tsc + vitest + data-service 离线 + test-p2/p5。
- **B 批（待定性）**：CR5-D1/D2/D3 按主人决策；CR5-P1/P4 视是否纳入。

> 待主人批复"实施哪些 / 分批方式"后，再进入编码；编码时同步把可复用规则固化进 PLAN 的 C 系列（如"C34 数值失败必须双向记账（成功/失败都写窗口）"），并在 Progress.md 记录。

### 决策定稿（2026-09-17，主人批复）

**选定范围：A + B 批共 8 项**（均属"补全已有意图 / 复用既有结构"，无新文件、无新依赖、无新配置项，合计约 38 行）：

| 项 | 最小实现形态（复用点） | 改动量 |
|---|---|---|
| CR5-1 | `_fetch_markets` 包 `try/except`，失败补写**已存在但从未被写入**的 `_markets_fail_ts` | ~4 行 |
| CR5-2 | ChatUI 监听器加 `if (data.failed)` 分支，消费后端**已经发出**的 `failed`/`error` 字段 | ~6 行 |
| CR5-3 | 用**已导出**的 `STALE_RUNNING_MS` 判 `staleRunning`，stale 的 running **落入现有起始态分支**（复用已有按钮） | ~10 行 |
| CR5-P5 | `HotspotFeed.trigger` 把 `await refresh()` 移出 `if (sawRunning)` | ~1 行 |
| CR5-P1 | `score.ts` `tagCache`、`skills.ts` `cache` 照抄**已有 8 处先例**的 `Symbol.for` globalThis 模式；`skills.cache` 顺带换**已有** `Lru` 类 | ~8 行 |
| CR5-P2 | `/api/quote` 按 `res.status` 透传，对齐其余路由分流口径 | ~3 行 |
| CR5-P3 | `/api/chat` 的 `message`、`/api/search/click` 的 `query`/`code` 加 `.slice(0, N)` 上限 | ~4 行 |
| CR5-P6 | `ResearchPanel.trigger` 依赖数组移除未使用的 `fetchOnce` | ~1 行 |

**接受的一处轻微重复（不为此改协议）**：CR5-2 前端失败文案与服务端 `research.ts` 的 `failText` 各存一份（跨进程无法共享），措辞保持一致即可，不为去重抽公共包或改广播协议。

**批量交付顺序**：CR5-1 → CR5-2 → CR5-3 → CR5-P5 → CR5-P1 → CR5-P2 → CR5-P3 → CR5-P6（一次交付，一轮回归）。
**验证门槛**：`tsc --noEmit` 0 错 + `vitest` 全绿 + data-service 离线套件全绿 + `test-p2` / `test-p5` 全绿；失败按 R9 最多重试 2 次后停止沟通。

**暂不处理（本轮不写代码，边界已明确）**：

| 编号 | 结论 | 理由 |
|---|---|---|
| CR5-P4 写接口无鉴权 | 暂不处理 | 改动面最大（新增开关+配置+4 路由校验+测试）；当前 compose 仅发布 web 端口、data-service 不发布，无真实暴露面。**预留**：`WEB_PORT` 对外/上云前必须补 |
| CR5-D1 R13 交叉验证 | 暂不处理（现状即"测试期已验证"） | 通用双源比对与 R15 限流直接冲突；窄口径亦需改 provider。PLAN 需求条目保留，实现留待需要时 |
| CR5-D2 webhook 推送 | 暂不处理 | 属新增能力（非修复），需外部凭据与重试语义 |
| CR5-D3 LLM 兜底召回 | 暂不处理 | 属新增能力；FTS+LIKE 当前满足需求 |

> 上述 4 项在 PLAN 中的需求条目**保持原样**（本轮不改 PLAN 需求，仅在本文档登记"暂不处理"结论），以免需求与实现口径被静默改写；后续如决定裁剪或实现，再单独更新 PLAN。

### 实施记录（2026-09-17 完成）

**8 项全部落地**，实际改动比预估略多 1 个新文件（CR5-3 抽零依赖模块，见下）。

| 项 | 落地位置 | 做法 |
|---|---|---|
| CR5-1 ✅ | `data-service/app/providers/crypto_provider.py` | `_fetch_markets` 内 `try/except`，失败写 `_markets_fail_ts`（与成功路径对称）；冷却提示补剩余秒数 |
| CR5-2 ✅ | `web/app/chat/ChatUI.tsx` | research 事件类型补 `failed?`/`error?`；新增 `if (data.failed)` 分支渲染失败文案 |
| CR5-3 ✅ | `web/lib/research-stale.ts`（新增）+ `ResearchPanel.tsx` + `research.ts` | 见下方"实现调整" |
| CR5-P5 ✅ | `web/app/HotspotFeed.tsx` | `await refresh()` 移出 `if (sawRunning)`；else 分支提示"已刷新热点列表"（不谎报复用旧 lastResult） |
| CR5-P1 ✅ | `web/lib/score.ts`、`web/lib/skills.ts` | `tagCache` 挂 globalThis；skills `cache` 换 `Lru(200)` + 挂 globalThis |
| CR5-P2 ✅ | `web/app/api/quote/route.ts` | `res.status` 透传 400/501，其余 502 |
| CR5-P3 ✅ | `web/app/api/chat/route.ts`、`web/app/api/search/click/route.ts` | `message` slice 4000；`query/type/code` slice 200/20/30 |
| CR5-P6 ✅ | `web/app/product/[type]/[code]/ResearchPanel.tsx` | `trigger` 依赖数组移除 `fetchOnce` |

**CR5-3 的实现调整（与方案的偏离，已记录）**：原方案设想 `ResearchPanel` 直接从 `@/lib/research` 导入 `STALE_RUNNING_MS`。实现时发现 **`ResearchPanel` 是 `"use client"` 组件，而 `@/lib/research` 牵连 `prisma`（服务端专属）**，打入客户端包会构建失败。故把常量与判定函数抽到**零依赖**的 `web/lib/research-stale.ts`（`STALE_RUNNING_MS` + `isStaleRunning(row, nowMs)`），`research.ts` 从该模块**重导出**常量保持单一来源，组件与单测均从零依赖模块导入。

**新增回归测试**：
- `data-service/tests/test_p2_m8.py` → `test_crypto_failure_negative_cache()`（6 项断言：首次失败如实抛错 / 冷却期内不再发起外部请求 / 说明含冷却提示 / 窗口过后可恢复）。**做过反向验证**：临时回退修复后该断言精确失败（`n:2` 证明又发了外部请求），恢复后通过——确保它不是"永远为真"的假断言。
- `web/lib/research-stale.test.ts`（6 项：超阈值 / 未超阈值 / 阈值边界严格大于 / 非 running 状态 / 缺 `updatedAt` / 非法日期）。

**验证结果（全绿）**：
- `tsc --noEmit` **0 错**；`vitest` **79/79**（11 文件，本轮 +6）
- data-service 离线：`test_p2_m8` **29/29**（+6）、`test_p6_mcp` 7/7、`test_p6_fund_report` 15/15
- 双服务集成：`test-p5` **21/21**；`test-p2` **37/38**——唯一失败「分钟线 502」为**东财 IP 级限流瞬时波动**（单发探测该接口返回 200 且 28013 字节真实数据；本轮未触碰 kline/分钟线路径），与 Progress.md 既有记录一致；按 R9 纪律未再重试

**过程中发现并修复的自伤**：CR5-3 抽模块时，漏删 `ResearchPanel` 内原有的本地 `isStaleRunning` 定义（它遮蔽了导入、且引用了已不再导入的 `STALE_RUNNING_MS`）→ `tsc` 报错。修复后 0 错。**教训：验证点必须晚于最后一次改动**。

**未做（与"暂不处理"一致的延伸）**：
- CR5-2 / CR5-3 的**集成级**断言未补——二者分别属 SSE 运行时与客户端首帧后行为，SSR 均覆盖不到；CR5-3 的判定逻辑已由 6 项单测覆盖（含边界）。为它们硬造集成测试的改动量会超过功能改动本身，违背本轮"少改动"原则。

- [x] 8 项全部实施完成
- [x] 可复用规则固化进 PLAN C 系列 → **C34（缓存窗口/计数必须与成功路径对称记账 + 此类修复必须附反向验证）**
- [x] Progress.md 追加当日日志（2026-09-17）
- [x] PLAN 需求表新增 **R16**（失败终态如实呈现）/ **R17**（长时运行态可退出），并补 CR5 修复的需求映射
- [x] 编号口径统一：审查编号 `R4-x`/`R5-x` → **`CR4-x`/`CR5-x`**（避免与需求 R5–R17 冲突）

> **状态：CR5 已全部闭环**（8 项修复 + 文档 + 需求映射 + 编号统一）。未闭环项：CR5-P4（上云前置）、CR5-D1/D2/D3（暂不处理，需求条目保持原样）。
>
> 全部改动**尚未 git 提交**（按主人指示暂不提交；Docker 相关按主人指示暂不推进）。
