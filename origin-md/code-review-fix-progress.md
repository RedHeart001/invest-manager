# 优化计划执行进度

> 计划见 [code-review-fix-plan.md](code-review-fix-plan.md)，排查结果见 [code-review.md](code-review.md)。
> 每完成一项/一批，追加一条记录（含改动文件、验证结果）。

## 状态总览

| 批次 | 项 | 状态 | 本批验证 |
|---|---|---|---|
| **A** | A1–A6（CR-01/02/03/12/13/15-零风险） | ✅ 完成 | tsc 0 错 / vitest 101→135 / ds 离线全绿 |
| **B** | B1–B8（CR-04/05/07/08/09/11/16/19） | ✅ 完成 | tsc 0 错 / vitest 135/135 / ds 离线全绿 |
| **C** | C1–C9（CR-06/10/14/17/18/22 + CR-15 部分/CR-20 评估） | ✅ 完成 | tsc 0 错 / vitest 125/125 / ds 离线 42+10+18+15+7+6 |
| **D** | G1–G7 需求缺口处置 | ✅ 完成 | tsc 0 错 / vitest 135/135 / ds 离线 +test_g6_hk 9、test_g3_crosscheck 8 |
| **验收** | 双服务全量集成 + 冒烟 + 缺陷修复（V1/V2） | ✅ 完成 | tsc 0 错 / vitest **140/140** / 集成 7 套件全绿 / 冒烟 7/8 |
| **G6 补强** | 港股连通性排障 + 多host降级 + 分页 + 腾讯备源 | ✅ 完成 | test_g6_hk **28/28**（+3 反向验证）/ data-service 离线全绿 |

**最终状态**：四批 + 验收 + G6 补强全部完成，**改动尚未 git 提交**（用户自行提交）。

---

## 2026-09-19 — 批次 D 执行完成 ✅

**决策**（用户）：G2/G3/G4/G5/G6 实现；G1 显式裁剪；G7 由 B4 Origin 校验覆盖（完整鉴权留待上云前）。

### 批次 D 决策原表（G1–G7 · 2026-09-20 自 `PLAN.md` 并入）

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

> 上条「未闭环/前置项」中的 hk 两项（`POST /api/sync?type=hk`、`GET /quote?type=hk&code=00700`）已由本文件下文「2026-09-20 — G6 港股连通性排障」一节闭环；`/quote/verified` 的**接入**状态见 `code-review.md` 第二轮 `CR7-3`。

### D1 · G2 产品主数据每日自动同步
- **新增** `data-service/app/sync_scheduler.py`：APScheduler 每日 02:00（Asia/Shanghai，`SYNC_HOUR`/`SYNC_MINUTE` 可覆盖）+ 启动补跑，回调 web `POST /api/sync`；单飞；状态端点。
- **改** `data-service/app/main.py`：lifespan 启动/关闭、`/sync/status`、`/sync/run`。

### D2 · G6 港股 provider
- **新增** `data-service/app/providers/hk_provider.py`：东财 `stock_hk_spot_em`（列表 + 行情快照）、`stock_hk_hist`（日 K）；走东财源族限速（`_em_ak_request`）与看门狗；`secid=116.<code>`；币种 HKD；OHLC 缺失跳过（与其它 provider 同契约）。
- **改** `providers/__init__.py` 注册；`web/lib/sync.ts` 的 `SYNC_TYPES`、`web/lib/quote-enrich.ts` 的富集类型、`web/app/api/market/refresh/route.ts` 快照白名单、`web/app/search/search-client.tsx` 搜索 Tab 均纳入 hk。
- **新增** `data-service/tests/test_g6_hk.py`：9 项（注册/行情映射/列表/类型守卫）。

### D3 · G4 LLM 兜底召回
- **改** `web/lib/llm.ts`：新增 `chatJson`（非流式 JSON 调用，失败返回 null）。
- **改** `web/lib/search.ts`：抽出 `scoreQuery`；新增 `llmFallback`——首查无结果时用 LLM 抽关键词重查，失败静默返回空。
- **新增** `web/lib/search-fallback.test.ts`：4 项。

### D4 · G5 Watchlist 自选
- **新增** `web/app/api/watchlist/route.ts`（GET/POST/DELETE，type/code 白名单校验 + upsert 幂等）。
- **新增** `web/app/components/WatchButton.tsx`（详情页身份区「加自选」）。
- **改** `web/app/product/[type]/[code]/page.tsx` 挂载按钮。
- **新增** `web/app/api/watchlist/route.test.ts`：6 项。

### D5 · G3 R13 双源交叉验证
- **改** `data-service/app/providers/chain.py`：新增 `verify_metric`（主源结果 + 备源比对，超阈值标注偏差，备源不可用不阻塞）。
- **改** `data-service/app/main.py`：新增 `/quote/verified`（R13 按需端点，**不叠加**普通 /quote，避免放大限流敏感请求）。
- **新增** `data-service/tests/test_g3_crosscheck.py`：8 项。

### D6 · G1 显式裁剪（webhook）
- **改** `PLAN.md`：M1 webhook 条目划除，文末新增「批次 D 决策记录」表。

### 验证结果（全绿）

| 套件 | 结果 |
|---|---|
| `npx tsc --noEmit` | ✅ 0 错 |
| `npx vitest run` | ✅ **135/135**（22 文件；D 批新增 10 项） |
| data-service 离线 | ✅ test_p2_m8 42/42、test_cr6_timeutil 6/6、test_cr6_pipeline 10/10、test_cr6_lru 18/18、test_p6_fund_report 15/15、test_p6_mcp 7/7、**test_g6_hk 9/9**、**test_g3_crosscheck 8/8** |

### 未做 / 前置项
- **集成套件（test-p1..p6、test-db）仍未跑**——需双服务启动。
- **G2/G3/G6 真实外部源连通性未在沙箱验证**（沙箱网络受限，港股东财接口实测报 ProxyError/ConnectionError）：需在本地环境实测 `POST /api/sync?type=hk`、`GET /quote/verified?type=stock&code=600519`、`GET /sync/status`。
- **G7 完整身份鉴权**留待上云前（已有 B4 Origin 校验）。

### 改动文件清单（D 批）
```
新增  data-service/app/sync_scheduler.py
新增  data-service/app/providers/hk_provider.py
新增  data-service/tests/test_g6_hk.py
新增  data-service/tests/test_g3_crosscheck.py
新增  web/app/api/watchlist/route.ts
新增  web/app/api/watchlist/route.test.ts
新增  web/app/components/WatchButton.tsx
新增  web/lib/search-fallback.test.ts
改    data-service/app/main.py
改    data-service/app/providers/__init__.py
改    data-service/app/providers/chain.py
改    web/lib/sync.ts
改    web/lib/quote-enrich.ts
改    web/lib/llm.ts
改    web/lib/search.ts
改    web/app/api/market/refresh/route.ts
改    web/app/search/search-client.tsx
改    web/app/product/[type]/[code]/page.tsx
改    PLAN.md
```

**收尾状态**：A+B+C+D 四批全部完成，**尚未 git 提交**。

---

## 2026-09-19/20 — 双服务全量集成验收（四批统一验收）

**环境**：本地开发态（data-service 127.0.0.1:8000 + web 3000），非容器。

### 集成套件（`node scripts/verify-all.mjs`，全部 exit=0）

| 套件 | 结果 |
|---|---|
| test-db | ✅ **16/16** |
| test-p1（搜索） | ✅ **20/20** |
| test-p2（详情页/K线缓存/R13） | ✅ **38/38** |
| test-p3（热点/SSE/调度） | ✅ **27/27** |
| test-p4（Agent/function calling） | ✅ **19/19** |
| test-p6（Skills/MCP） | ✅ **21/21** |
| test-p5（深度研报） | ✅ **21/21** |

### 冒烟（`scripts/smoke.mjs`）
✅ **7/8**——BFF 五项全绿（health/quote/kline/search/tools-status）；唯一失败为第 6 项"容器内 data-service health"，因本次为**本地开发态**（无 docker compose），该项**预期不适用**。

### 静态与单测
- `npx tsc --noEmit`：✅ **0 错**
- `npx vitest run`：✅ **140/140**（24 文件）
- data-service 离线：✅ 42+6+10+18+9+8+15+7 全绿

### 验收中发现并修复的 **2 个真实缺陷**（均为本轮改动引入，已修复 + 回归测试 + 反向验证）

#### 1. **[高] C4 批量写把 KlineDaily.date 存成文本 → 日期范围查询漏行**
- **现象**：test-p2 的 R13 交叉验证失败（`kline=1266.98` vs `quote=1257.12`）。
- **根因**：C4 把 `upsertCandles` 改为原生 `INSERT OR IGNORE` 时，日期参数传了 ISO 字符串；而 Prisma 对 SQLite DateTime 存的是 **Unix 毫秒整数**（`typeof=integer`）→ 文本行与 Prisma 生成的 `date >= ? / <= ?`（数字比较）不匹配，在日期范围查询中被**静默漏掉**（实测 3 行）。
- **修复**：`web/lib/kline.ts` 改传 `dayStart(c.date).getTime()`；数据修复脚本 `web/scripts/fix-kline-date.mjs` 转换已污染行（3 行 → 0）；**新增回归测试** `web/lib/kline-date-format.test.ts`（含反向验证：回退修复后精确失败）。
- **效果**：test-p2 37/38 → **38/38**。

#### 2. **[中] G2 自动同步会用降级备源"缩小"主数据**
- **现象**：test-p1 失败（`bond=329 < 500`），而此前全量为 1052。
- **根因**：G2 新增的每日同步在 00:xx 已自动跑过一次（`/sync/status` runs=1），当时东财限流 → 转债列表降级到**新浪 cov_spot（约 320 只）**，而全量替换语义会用这 329 条**覆盖**原有 1052 条 → 主数据静默劣化。
- **修复**：`web/lib/sync.ts` 在空载荷保护（C1）之外增加**降级缩水保护**——新载荷 < 现有 70% 时保留旧数据并显式报错（`payload shrunk ...`），等主源恢复后再全量更新；**新增回归测试** `web/lib/sync-shrink.test.ts`（4 项 + 反向验证）。数据已重新同步恢复（bond 1053）。
- **效果**：test-p1 19/20 → **20/20**。

### 验收中修正的 **2 处测试脆弱性**（非产品缺陷，口径修正）

1. **test-p5 `sources.length >= 2`**：`meta.sources` 按**来源名去重**，行情/K线/新闻恰好同源（均为 akshare）时塌缩为 1 项 → 误报。改为断言 `meta.dimensions`（新增字段，已采集维度）——更精确地表达"采到行情与新闻两个维度"。
2. **test-p5 对"当日已有研报"的环境依赖**：跨天（北京时间 00:00 后）首次运行必然失败。改为按当日实际状态分流断言（当日有 done → 必须复用；当日无 → 触发新建属合法）。

### 待本地验证（沙箱网络受限）
- **G6 港股真实连通性**：沙箱内港股市值表接口报 `eastmoney cooling down (rate-limited)` / `RemoteDisconnected`，与同源族 A股/基金/转债的限流同因；**代码链路已由离线单测 9/9 覆盖**。对照：同时刻 A股 `/quote` 可返回（走腾讯备源），港股目前**无备源** → 显式 502 + 降级说明（符合 R10/R15"可用或显式缺口"语义）。
- 建议本地验证：`POST /api/sync?type=hk`、`GET /quote?type=hk&code=00700`。

### 改动文件清单（验收轮）
```
新增  web/lib/kline-date-format.test.ts
新增  web/lib/sync-shrink.test.ts
新增  web/scripts/fix-kline-date.mjs
改    web/lib/kline.ts
改    web/lib/sync.ts
改    data-service/app/research/engine.py
改    web/scripts/test-p5.mjs
```

**收尾状态**：四批改动 + 验收修复已全部落地并**通过全量验证**，**尚未 git 提交**。

---

## 2026-09-20 — G6 港股连通性排障 + 备源补强（用户本地验证驱动）

### 背景与根因

用户本地 `POST /api/sync?type=hk` 返回 `RemoteDisconnected`。排查（对照探测各 CDN 节点）：

| 节点 | 结果 |
|---|---|
| `72.push2.eastmoney.com`（**akshare `stock_hk_spot_em` 硬编码**） | ❌ `RemoteDisconnected` |
| `81.push2` / `push2` / `82.push2` | ❌ 同上 |
| **`push2delay.eastmoney.com`** | ✅ HTTP 200（真实港股数据 `89988 阿里巴巴-WR`） |
| **`7.push2.eastmoney.com`** | ✅ HTTP 200 |

**结论：根因非"港股被封"，而是 akshare 硬编码单一 CDN 节点不可达**——初版 `hk_provider` 复用了 akshare 封装，等于绕过了本项目已有的多 host 降级能力。

### 修复 1 · `hk_provider` 改直连 + 多 host 降级

- 不再套用 akshare `stock_hk_*`；直连东财，`HK_SPOT_HOSTS` / `HK_HIST_HOSTS` 按序降级，走同一源族限速器 + 看门狗，全失败才抛 `ProviderError`。

### 修复 2 · 分页缺陷 + 快/慢路径分离（**实测新发现的第 2 个真实缺陷**）

- **分页**：东财港股 `clist/get` **忽略大分页参数**（`pz=100/1000/10000` 均只返回 100 条），港股 `total≈4707` → 初版单次请求**只拿到 100 条**，`00700` 根本不在其中。改为按 `total` 分页遍历（实测取满 **4707 只**）。
- **快/慢路径分离（关键）**：发现"行情复用列表快照"会导致**查单个港股耗时约 4 分钟**（拉全量 4700 条）。重构为：
  - 单股行情 → `/api/qt/stock/get`（1 次请求）
  - 批量行情 → `/api/qt/ulist.np/get`（1 次请求）
  - 全量列表 → `clist/get` **分页，仅每日同步调用**
- 新增单测 `test_quote_does_not_trigger_list_paging` **把"行情不得触发列表分页"锁为红线**（含反向验证）。

### 修复 3 · 腾讯港股备源（用户选定方案 A：东财主源 + 腾讯备源）

- **扩展 `tencent_provider`**（不新建文件，复用其解析路径）：
  - `_hk_symbol(code)`：5 位补零 → `hkXXXXX`；非数字或 >5 位返回 `None`
  - `_symbol_for(type_, code)`：按**类型显式分派**（港股 5 位数字与 A 股前缀规则冲突，**禁止复用 `_symbol`**，也禁止"按长度猜类型"的隐式约定）
  - 三处调用点改用 `_symbol_for`
  - `register_chain(["hk"], _provider, position=1)`
- **实测可行性依据**（沙箱内已验证）：行情 `qt.gtimg.cn/q=hk00700` → 78 字段，字段位置与 A 股一致；日 K `…fqkline/get?param=hk00700,day,,,N,qfq` → `{"data":{"hk00700":{"day":[…]}}}`，现有 `qfqday or day` 回退已覆盖；复权口径与主源一致（均前复权）。
- **端到端降级实测通过**：链顺序 `['akshare-hk','tencent']`；强制主源失败 → 自动切腾讯（`price=419.0 腾讯控股`，note 标注降级链）；港股 K 线降级取到 14 根。
- **港股列表无备源**（腾讯无全量港股列表接口）→ 显式降级（R10）。

### 修复 4 · BFF 同步超时不足（核对中发现，同属 V3 系列）

- **现象/根因**：`web/lib/sync.ts` 拉取 `/products` 的超时为 **180s**，而港股列表分页实测约 **236s**（48 页 × 源族限速 5s）→ **港股同步必然超时**（即便服务端分页已修好）。
- **修复**：超时放宽至 **600s**（`/api/sync` 的 `maxDuration=800` 覆盖）；PLAN 记录同步耗时特征与"同步期间其它东财请求排队"的 R15 设计语义。

### 验证

| 项 | 结果 |
|---|---|
| `test_g6_hk.py` | ✅ **28/28**（新增：多 host 降级、腾讯符号映射含边界、行情不触发分页红线、腾讯港股行情/K线解析、链顺序） |
| 反向验证 | ✅ 3 处（削弱多 host / 移除类型分派 / 行情改用列表接口）均精确失败 |
| data-service 离线回归 | ✅ test_p2_m8 42、test_g3_crosscheck 8、test_cr6_pipeline 10、test_cr6_lru 18、test_p6_mcp 7、test_p6_fund_report 15、test_cr6_timeutil 6 |
| web 静态与单测 | ✅ tsc 0 错 / vitest **140/140**（24 文件） |

### 待用户本地验证
- `POST /api/sync?type=hk`（应同步约 4700 只，耗时数分钟——分页 48 次受源族限速）
- 搜索页「港股」Tab / `GET /quote?type=hk&code=00700`

### 改动文件（本轮）
```
改    data-service/app/providers/hk_provider.py（重写：多 host 降级 + 分页 + 快慢路径分离）
改    data-service/app/providers/tencent_provider.py（_hk_symbol/_symbol_for + hk 备源注册）
改    data-service/tests/test_g6_hk.py（9 → 28 项）
改    web/lib/sync.ts（/products 超时 180s → 600s）
改    PLAN.md（M8 港股三行 + 四条实测约束 + G6 追加记录）
改    code-review.md（V3 三缺陷 + 本地验证结论）
```

### ⚠️ 待用户操作（核对时发现的关键事实）

**运行中的 data-service 仍是旧代码** —— 证据：其返回的报错串 `hk spot table failed` 在重写后的 `hk_provider.py` 中**已不存在**（新代码的报错串为 `hk eastmoney request failed on all hosts` 等）。同时库内 `hk` 产品数为 **0**，说明港股尚未成功同步过。

**需重启 data-service 后再执行**：
```powershell
# 在 data-service 终端 Ctrl+C 后重启
.venv/Scripts/uvicorn app.main:app --port 8000

# 另开终端：触发港股同步（预计 4~8 分钟：列表分页 236s + 快照刷新）
curl.exe -X POST "http://localhost:3000/api/sync?type=hk"
```

**收尾状态**：G6 连通性 + 备源补强完成，**尚未 git 提交**。

---

## 2026-09-19 — 批次 C 执行完成 ✅

### C1 · 日期口径统一为北京时间（CR-06）
- **新增** `data-service/app/utils/timeutil.py`：`beijing_now/beijing_today/beijing_today_date/beijing_shift_days`。
- **改** `research/tasks.py`（5 处 `date.today()` → `beijing_today()`：daily_done、限额判断、回调 payload、状态输出）、`research/adapter.py`（`research_date()`）、`hotspot/pipeline.py`（digest date）、`hotspot/scheduler.py`（补跑判断日期）；同步清理不再使用的 `date` 导入。
- **新增** `data-service/tests/test_cr6_timeutil.py`：6 项。

### C2 · 接通事件日期筛选（CR-10）
- **改** `web/lib/events.ts`：新增纯函数 `narrowByDates`（把全量事件收窄到指定日期）。
- **改** `web/app/product/[type]/[code]/page.tsx`：kline 就绪后用 `pickEventDates`（转折点 + 大波动日）收窄事件——**此前 `pickEventDates` 只被单测引用、生产未接线**。
- **改** `web/lib/events.test.ts`：新增 `narrowByDates` 4 项（含与 `pickEventDates` 联动）。

### C3 · `/api/research/start` 可选 sessionId（CR-14）
- **改** `web/app/api/research/start/route.ts`：接受可选 `sessionId` 并透传给 `startResearch`（统一入口会话语义；详情页不传属预期）。

### C5 · 转债备源交易所显式传递（CR-17）
- **改** `data-service/app/providers/akshare_provider.py`：新增 `_sina_symbol_exchange`（`sh/sz/bj` 前缀 → SH/SZ/BJ）；`_build` 优先用调用方显式 `exchange`，新浪备源从 `symbol` 带出，不再依赖数字前缀推断。
- **改** `data-service/tests/test_p2_m8.py`：新增 3 项 CR-17 断言。

### C6 · 转债快照陈旧显式标注（CR-18）
- **改** `data-service/app/providers/sina_bond_provider.py`：刷新失败沿用旧快照时记录 `_stale_note`（含旧快照时点），`get_quote`/`get_quotes` 在响应 `note` 标注；刷新成功清除。

### C8 · 看门狗放弃线程可观测（CR-22）
- **改** `data-service/app/utils/timeout.py`：新增 `abandoned_count()` 计数与阈值告警（默认 20）；`run_with_timeout` 在超时放弃时 +1、该线程真正结束时 -1。
- **改** `data-service/app/main.py`：`/health` 返回 `abandonedWatchdogs`。
- **改** `data-service/tests/test_p2_m8.py`：新增 3 项 CR-22 断言。

### C4 · kline 批量写入（CR-15 部分）
- **改** `web/lib/kline.ts`：`upsertCandles` 由逐行 `await create` 改为分块 `INSERT OR IGNORE`（50 行/批），首次回源 5 年从 ~1200 次往返降为 ~24 次；`OR IGNORE` 天然吸收并发唯一冲突（移除 `isUniqueViolation`）。新增 `randomId()`（原生 INSERT 需显式主键）。

### C7 · 每日限额双侧判断（CR-20）— 评估后**保留现状**
- 结论：web 查库（持久兜底）+ data-service 内存 `_daily_done`（快速判断）是**有意的双层设计**；主要风险（日期口径错位）已由 C1 消除。不额外改动，风险已降级。

### C9 · CR-15 其余项收尾
- **改** `web/app/api/chat/sessions/route.ts`：PUT content 长度上限 20000（此前无界）。
- **改** `web/app/api/chat/sessions/[id]/route.ts`：DELETE 区分 P2025（404）与真实 DB 故障（500），此前一律吞成 404。
- **改** `web/lib/sync.ts`：`rebuildFts` 三条语句分步 try/catch + 日志（此前半更新态静默）。
- **改** `web/lib/llm.ts`：收尾 `decoder.decode()` flush（防末尾多字节字符丢失）；移除死变量 `finish`。
- **改** `web/lib/gateway.ts`：状态缓存按 `connect` 分键（防未探测结果污染探测结果）。
- **评估后不改**（记录理由）：`research-target` 的 6 位数字误判（仅在意图词命中后调用，收紧会破坏合法识别）；`search` 单字符候选偏斜（`orderBy code asc` 已保证确定性，改召回策略引入复杂度）；`sync` 行 type 取自 payload（provider 契约保证同类型）；进程内单飞多副本（当前单容器部署不触发，已在报告注明）。

### 验证结果（全绿）

| 套件 | 结果 |
|---|---|
| `npx tsc --noEmit` | ✅ 0 错 |
| `npx vitest run` | ✅ **125/125**（20 文件；C 批新增 4 项） |
| data-service 离线 | ✅ test_p2_m8 **42/42**、test_cr6_timeutil **6/6**、test_cr6_pipeline 10/10、test_cr6_lru 18/18、test_p6_fund_report 15/15、test_p6_mcp 7/7 |
| Python 语法 | ✅ 9 个改动文件 `py_compile` 通过 |

### 未做
- 集成套件（test-p1..p6、test-db）未跑——需双服务启动。

### 改动文件清单（C 批）
```
新增  data-service/app/utils/timeutil.py
新增  data-service/tests/test_cr6_timeutil.py
改    data-service/app/research/tasks.py
改    data-service/app/research/adapter.py
改    data-service/app/hotspot/pipeline.py
改    data-service/app/hotspot/scheduler.py
改    data-service/app/providers/akshare_provider.py
改    data-service/app/providers/sina_bond_provider.py
改    data-service/app/utils/timeout.py
改    data-service/app/main.py
改    data-service/tests/test_p2_m8.py
改    web/lib/events.ts
改    web/lib/events.test.ts
改    web/lib/kline.ts
改    web/app/product/[type]/[code]/page.tsx
改    web/app/api/research/start/route.ts
改    web/app/api/chat/sessions/route.ts
改    web/app/api/chat/sessions/[id]/route.ts
改    web/lib/sync.ts
改    web/lib/llm.ts
改    web/lib/gateway.ts
```

**收尾状态**：A+B+C 批改动已落地并验证，**尚未 git 提交**。


---

## 2026-09-19 — 批次 B 执行完成 ✅

**决策项已确认**（用户）：B1 = `connection_limit=1`；B5 = 快照保留旧值（COALESCE）；B4 = Origin/Referer 校验（轻量）。

### B1 · busy_timeout 覆盖连接池（CR-04）
- **改** `web/lib/prisma.ts`：新增 `datasourceUrl()`——向 `DATABASE_URL` 注入 `connection_limit=1`（经 Prisma `datasourceUrl`，dev/容器两种 URL 统一生效；已显式配置时不覆盖），使唯一连接承载 `busy_timeout`。
- 附带修复：`ensureSqlitePragmas` 失败**不再永久缓存**（失败清空缓存，后续可重试）；导出供测试。
- **新增** `web/lib/prisma.test.ts`：5 项（追加/`&` 拼接/不覆盖显式配置/容器路径/无 env）。

### B2 · kline 头/尾缺口拆分复查窗口（CR-05）
- **改** `web/lib/kline.ts`：新增独立 `lastCheckedTail`（`Symbol.for("invest-manager.kline.lastCheckedTail")`，挂 globalThis）；尾部分支读写该键，不再被头部补全压制。
- **新增** `web/lib/kline-headtail.test.ts`：2 项（头+尾同时缺口 → 两次回源；仅头缺口 → 一次）。

### B3 · 长请求 maxDuration（CR-07）
- **改** `web/app/api/sync/route.ts`、`web/app/api/market/refresh/route.ts`：显式 `export const maxDuration = 800`（与 `/api/hotspots/run` 口径一致）。

### B4 · 写端点 Origin 校验（CR-08）
- **新增** `web/lib/request-origin.ts`：`checkRequestOrigin`——校验 Origin（缺失回退 Referer）host 是否同站或 `ALLOWED_ORIGINS` 白名单；无来源（curl/测试）放行。
- **改** `/api/sync`、`/api/market/refresh`、`/api/hotspots/run`：入口先校验，跨站返回 403。
- **新增** `web/lib/request-origin.test.ts`：8 项（同源/跨站/无来源/Referer 回退/Origin 优先/端口不同/非法值）。

### B5 · 快照保留旧值（CR-09）
- **改** `web/lib/market-snapshot.ts`：抽出纯函数 `buildSnapshotUpdate`；SQL 改为 `COALESCE(CASE …, "lastPrice")`——新值为 null 时保留旧值。
- **新增** `web/lib/market-snapshot.test.ts`：5 项（COALESCE 语义/参数顺序/参数计数/占位符一致/空集）。

### B6 · 热点去重唯一索引（CR-11）
- **改** `web/prisma/schema.prisma`：`HotspotDigest` 增 `@@unique([date, title])`。
- **新增** 迁移 `20260919000000_hotspot_digest_unique_date_title/migration.sql`：先清理历史重复行（按 rowid 保留最早），再建唯一索引（**已 `migrate deploy` 应用**）。
- **改** `web/lib/hotspots.ts`：`create` 捕获 P2002 → 归为"跳过"，兜住并发 ingest 的"先读后写"竞态（新增 `isUniqueViolation`）。

### B7 · 热点 pipeline 超时覆盖全流程（CR-16）
- **改** `data-service/app/hotspot/pipeline.py`：`fetch_news(deadline=)`（预算耗尽跳过后续新闻源）、`structure_topics(deadline=)`（LLM 超时取剩余预算，不足则直接关键词回退）；`run_pipeline` 传入 deadline。
- **改** `data-service/tests/test_cr6_pipeline.py`：mock 签名同步；顺带修正一处浮点边界断言（`<=300` → `<=300.5`，本轮暴露）。

### B8 · 净值表失败负缓存（CR-19）
- **改** `data-service/app/providers/akshare_provider.py`：新增 `_fund_nav_fail_ts` + `FUND_NAV_FAIL_COOLDOWN`（5 分钟）；失败写时间戳（与成功路径对称），冷却期内直接降级。
- **改** `data-service/tests/test_p2_m8.py`：新增 5 项 CR-19 断言（首次失败抛错/确实发请求/冷却期不重试/降级提示）。

### 验证结果（全绿）

| 套件 | 结果 |
|---|---|
| `npx tsc --noEmit` | ✅ 0 错 |
| `npx vitest run` | ✅ **121/121**（20 文件；B 批新增 20 项） |
| data-service 离线 | ✅ test_p2_m8 **36/36**、test_cr6_pipeline 10/10、test_cr6_lru 18/18、test_p6_fund_report 15/15、test_p6_mcp 7/7 |
| Prisma 迁移 | ✅ `migrate deploy` 应用成功（含 B6 唯一索引）+ `prisma generate` |

### 未做
- 集成套件（test-p1..p6、test-db）未跑——需双服务启动。

### 改动文件清单（B 批）
```
新增  web/lib/request-origin.ts
新增  web/lib/prisma.test.ts
新增  web/lib/market-snapshot.test.ts
新增  web/lib/request-origin.test.ts
新增  web/lib/kline-headtail.test.ts
新增  web/prisma/migrations/20260919000000_hotspot_digest_unique_date_title/migration.sql
改    web/lib/prisma.ts
改    web/lib/kline.ts
改    web/lib/market-snapshot.ts
改    web/lib/hotspots.ts
改    web/prisma/schema.prisma
改    web/app/api/sync/route.ts
改    web/app/api/market/refresh/route.ts
改    web/app/api/hotspots/run/route.ts
改    data-service/app/hotspot/pipeline.py
改    data-service/app/providers/akshare_provider.py
改    data-service/tests/test_p2_m8.py
改    data-service/tests/test_cr6_pipeline.py
```

**收尾状态**：A+B 批改动已落地并验证，**尚未 git 提交**。


---

## 2026-09-19 — 批次 A 执行完成 ✅

**范围**：CR-01、CR-02、CR-03、CR-12、CR-13，以及 CR-15 中的零风险项。

### A1 · 会话历史 tool 配对修复（CR-01，P1）
- **新增** `web/lib/chat-history.ts`：零依赖纯函数 `repairToolPairing`——丢弃孤立 tool 消息（无前置 assistant 声明或缺 toolCallId）；把 `assistant.tool_calls` 收窄到"确有 tool 结果回应"的子集（全无回应则剥离 tool_calls，有文本保留文本，否则整条丢弃）。
- **改** `web/app/api/chat/route.ts`：`getMessages` 结果先过 `repairToolPairing` 再映射；tool 消息 `tool_call_id` 兜底由常量 `"call"` 改为 `""`（修复后不应再出现无 id 的 tool）。
- **改** `web/app/api/chat/sessions/route.ts`：`PUT` 对 `role:"tool"` 强制要求 `toolCallId`（否则 400），并透传 `toolCallId`/`name`。
- **新增** `web/lib/chat-history.test.ts`：9 项（完整配对/孤立 tool/缺 id/部分回应收窄/剥离/整条丢弃/重复 id/多轮混合/空）。

### A2 · LLM 流超时语义修正（CR-02，P1）
- **改** `web/lib/llm.ts`：连接超时改用独立 `AbortController` + `setTimeout`，仅约束"响应头到达"；`fetch` resolve/失败后 `clearTimeout`，body 读取阶段改由 `IDLE_TIMEOUT_MS` 空闲看门狗 + 用户 `opts.signal` 约束。不再把 60s 超时信号覆盖整条流。

### A3 · running 复用分支登记 watcher（CR-03，P1）
- **改** `web/lib/research.ts:144`：未陈旧 running 分支在 `return` 前调用 `watchResearch(type, code, watcherSessionId)`，与 409 并发去重路径一致。

### A4 · `mcp.stopAllMcp` 竞态加固（CR-12，P3）
- **改** `web/lib/mcp.ts`：`ServerRuntime` 增 `generation`；`ensureConnected` 捕获启动代际，完成时若代际已变则丢弃结果并关闭连接（防复活已停止 server）；`stopAllMcp` 自增代际；`finally` 仅在 `connecting` 仍指向本次连接时清空（用 holder 对象规避 TDZ）。

### A5 · `callMcpTool` 降级语义修正（CR-13，P3）
- **改** `web/lib/mcp.ts`：按工具名前缀 `mcp_<server>_` 定位目标 server，**只连它一个**（此前为匹配工具名会逐连所有 server，可能 spawn 无关子进程）；源降级/禁用时返回"该 MCP 源当前不可用（已降级）/已禁用"，而非误报"未知 MCP 工具"。

### A6 · 零风险打包（CR-15 部分）
- `.gitignore` 补 `*.db-wal`、`*.db-shm`。
- `web/scripts/db-stat.mjs` 移除不存在的 `syncState` 模型。
- `web/lib/context-budget.ts` 移除 `overflow` 死变量。
- `data-service/app/research/tasks.py` 移除 `_ = started`。
- `web/lib/kline.ts` 移除 `normalizeRange` 中的死条件（`dayStart(e) < dayStart(s)` 在上一行已 return）。

### 验证结果（全绿）

| 套件 | 结果 |
|---|---|
| `npx tsc --noEmit` | ✅ 0 错 |
| `npm test`（vitest） | ✅ **101/101**（16 文件；含新增 chat-history 9 项） |
| data-service 离线 | ✅ test_p2_m8 **31/31**、test_cr6_lru 18/18、test_cr6_pipeline 10/10、test_p6_fund_report 15/15、test_p6_mcp 7/7 |

### 未做（留待后续批次）
- 集成套件（test-p1..p6、test-db）未跑——需双服务启动；建议 B 批开始前或收尾时统一复跑。
- CR-01 的"窗口边界切割"场景未做集成复现（单测已覆盖纯函数逻辑）。

### 改动文件清单
```
新增  web/lib/chat-history.ts
新增  web/lib/chat-history.test.ts
改    web/app/api/chat/route.ts
改    web/app/api/chat/sessions/route.ts
改    web/lib/llm.ts
改    web/lib/research.ts
改    web/lib/mcp.ts
改    web/lib/context-budget.ts
改    web/lib/kline.ts
改    web/scripts/db-stat.mjs
改    data-service/app/research/tasks.py
改    .gitignore
```

**收尾状态**：A 批改动已落地并验证，**尚未 git 提交**。

---

## 附录 · O 系列执行结果（2026-09-13）

> 2026-09-20 自 `PLAN.md:553-568` 并入。计划正文见 `code-review-fix-plan.md` 文末「优化计划（历史：O 系列）」，优化点本体见 `code-review.md`「可优化点登记册」。

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
