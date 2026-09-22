# 修复账本（FIX-LEDGER）

> **职责**：记录**每一项发现修了没有、怎么验的**。未闭环项置顶，一眼可见。
> 另设「待评估的优化候选」（非缺陷的改进想法，编号 `OPT-n`）与「待拍板决策」两节。
> 审查发现原文见 [CODE-REVIEW.md](CODE-REVIEW.md)；被压缩掉的过程材料见 [history/](history/)。
>
> **维护规则**：
> ① 看板用**稳定编号 + 一行状态**，不藏进 prose；关闭时同步回写 [PLAN.md](PLAN.md) 对应需求条目的三态标记。
> ② 已闭环轮次的正文**只压缩、不重写**——防止在"重述"中引入新错误。
> ③ 修"失败负缓存 / 限流计数 / 熔断计数 / 复查窗口"类问题时必须附**反向验证**（C34）。

---

## 🔴 未闭环看板

| 编号 | 事项 | 严重度 | 状态 | 前置 / 卡点 |
|---|---|---|---|---|
| **CR7-1** | 技术分析师 `dataBased` 恒真 → 无 K 线仍进辩论并参与评级 | P1 | ⬜ 未修 | 无（建议先做） |
| **CR7-2** | 研报回读 `/api/kline` 日期格式不匹配 → `days` 参数静默失效 | P1 | ⬜ 未修 | A2-② 需你拍板（见下） |
| **CR7-3** | R13/G3 交付成「零调用方端点」 | P2 | ⬜ 未修 | **需你定调**：①详情页按需核对 / ②仅 Agent / ③改判不接入 |
| **CR7-4** | 港股消费侧三处断链（工具枚举 / 身份画像 / 币种） | P2 | ⬜ 未修 | B2c 文案需你拍板 |
| **CR7-5** | ChatUI 180s 静默截断，`terminated` 是死守卫 | P2 | ⬜ 未修 | 无 |
| **CR7-6** | GET 取数端点无 code 校验，可被耗尽东财额度 | P2 | ⬜ 未修 | 无 |
| **CR7-7** | 启动补跑冲突：同步与热点争抢同一源族令牌桶 | P2 | ⬜ 未修 | 需先做 C0 实测 |
| **CR7-8** | 场外基金净值表缓存"成功但空"，全体静默无值 | P2 | ⬜ 未修 | 无（🔁 反向验证） |
| **CR7-9** | `/api/sync` 耗时基线写错 + ds 侧超时把成功记成失败 | P3 | ⬜ 未修 | 依赖 C0 实测 |
| **CR7-10** | `POST /sync/run` 在请求线程内同步跑 15min+ | P3 | ⬜ 未修 | C4 需你拍板 |
| **CR7-11** | 回归盲区：`llm.ts`/`tools.ts`/`hotspots.ts`/`backup_db.py` 无单测 | P3 | ⬜ 未修 | 建议紧随 CR7-1~5 |
| **CR7-12** | `timeout.py` 的 `_abandoned` 计数窄竞态 | P3 | ⬜ 未修 | 无 |
| **CR7-13** | `hk_provider` 分页无上限 / MCP `list_products("hk")` 无超时 | P3 | ⬜ 未修 | 无 |
| **CR7-14** | 文档/注释漂移 | P3 | 🟡 部分闭环 | ①③ 已处置；② 待办 |
| **G3（CR6 遗留）** | R13 端点零调用方 | — | ⬜ 未闭环 | 同 CR7-3，**同一件事** |
| **G6 消费侧（CR6 遗留）** | 港股取数侧已闭环，消费侧仍断链 | — | 🟡 部分闭环 | 同 CR7-4，**同一件事** |
| **G7（CR6 遗留）** | 写接口完整身份鉴权 | — | ⬜ 未闭环 | **上云 / `WEB_PORT` 对外前必补**；当前单机无暴露面 |
| **C31 验证** | Dockerfile 进程降权（`setpriv`）的镜像构建/运行验证 | — | ⏳ 未验证 | 主人指示暂不推进 Docker；启用前必须先验证容器内 uid、两容器 healthy、`compose exec` 备份正常 |
| **C31 关联** | 任何 Docker 相关改动 | — | ⏸ 暂缓 | 同上 |

### ⚠️ 待你拍板的 5 项（CR7 批次 B/C 的前置）

1. **CR7-3 / B1**：R13 走 ①详情页按需核对（推荐）/ ②仅 Agent 侧可选参数 / ③改判不接入？
2. **CR7-4 / B2c**：币种展示文案——`419.00 港币` / `HK$419.00` / `419.00 HKD`？
3. **CR7-2 / A2-②**：`normalizeRange` 是否改为"格式非法即 400"（推荐，但属公共语义变更）？
4. **CR7-10 / C4**：`/sync/run` 是否值得异步化（当前仅运维手动用）？
5. **批次范围**：是否只做 A + D4-①②，把 B/C 留到下一轮？

### 🧪 待评估的优化候选（非缺陷，未拍板）

> 与上面的**缺陷**看板分开：这里放"**可以更好**"的想法，不是"**坏了**"的问题。
> 每条必须写明**来源**与**采用前要查证什么**；**未查证完不升级为 PLAN 的设计**。

| 编号 | 候选 | 针对 | 状态 | 卡点 |
|---|---|---|---|---|
| **OPT-1** | 用**类型化判断原语**替代技能触发词子串匹配——不写死子串，而把"这句话属于哪个技能"作为一次**结构化判断**交给模型，代码只消费结果 | M7 优化点 1（[PLAN.md](PLAN.md)），`web/lib/skills.ts:175` | ✅ **已拍板**（2026-09-22）：改走「路线 C · `load_skill` 工具化加载」 | 评估证据与实施要点见下 |

**OPT-1 来源**（2026-09-21 登记）：第三方技能 [`typesafe-ai`](../.claude/skills/typesafe-ai/SKILL.md)——TypeSafe System One / Jev，`Choice`/`Noul`/`Score` 三原语。其主张 "**select instead of generate**" 与 "**route and fill known arguments**" 与本优化点同构。

**OPT-1 评估与拍板（2026-09-22）**——三条路线查证结论：

1. **TypeSafe Jev（SaaS）→ 作废**。登记时自设的三条卡点两条不成立：①唯一形态是境外托管 API（`api.typesafe.ai`，Bearer key，Cloudflare 托管），聊天内容须出境、按 CONSTRAINTS §C 走代理；②新增凭据 + SDK + SaaS 可用性依赖，违反「白名单 + 不自动安装」口径（`web/mcp.json`）。另有登记时未预见的硬伤：官方明示英文为主、CJK 效果不保证，而本负载是纯中文；且调用点在每条消息 SSE 流开始前的同步路径（`route.ts` → `buildSystemPrompt`），境外 RTT 直接打进 TTFT。成本本身可忽略（$0.042/Mtok 输入、输出免费）。
2. **Laya（[github.com/NandhaKishorM/laya](https://github.com/NandhaKishorM/laya)，自托管）→ 未采纳，留作备选**。与 Jev 同构三原语（choice/score/noul）但本地推理：Apache-2.0、无凭据零外呼、模型卡明确支持 zh（mmBERT-base 322M，T4 约 33ms/问），翻盘了 SaaS 的卡点。未采纳原因：Python/torch 依赖与 web（Node）侧同步调用点架构错配；权重 + torch 显著撑大 P7 容器镜像；单人作者、基准自报、成熟度未验证。
3. **路线 C · 主 LLM 工具化加载 → ✅ 拍板采用**。技能 meta（name+description）本已常驻 system prompt，注册内置工具 `load_skill(name)` 由主模型自主拉取正文——"候选在代码、选择交给模型、代码消费结果"。用现有 LLM，零新依赖、零数据出境。

**实施要点（2026-09-22 与主人确认）**：

- **每请求闭包** `createSkillLoader()`（`def`/`run`/`loaded`），加载计数随请求生灭——不进全局注册表，避开 C17/C27 类单例并发坑；技能目录为空时 `def=null` 不注册
- **失败即引导**：未知名返回可用候选列表让模型下一轮自愈；`name` 白名单校验（C33）；正文截断复用 `maxBodyChars`（2400）
- **`SKILL_ROUTER` 三档开关**：`keyword`（现状原样保留）/ `llm`（**默认**）/ `hybrid`——改 env 即回滚
- **已知代价**：技能相关提问 +1 次 LLM 往返（决定→加载→作答）；`MAX_TOOL_ROUNDS` 维持 4（轮次耗尽有强制总结兜底，已有测试）
- **测试改造**：`test-p6.mjs` 的 meta.skills 确定性命中断言改到 keyword 档跑（llm 档只断言工具列表含 `load_skill`）；`meta.skills` 移到 `done` 事件汇报实际加载（前端只读 sessionId，无感）；新增 `eval-skill-router.mjs`（真实 LLM、手动跑、不进 verify-all）
- **验收门槛**：明确命中消息加载率 ≥90%、明确无关消息误加载率 ≤10%；不达标退 `hybrid` 档

---

## CR7 · 修复计划（⬜ 未开始，待批准）

> **依据**：[CODE-REVIEW.md](CODE-REVIEW.md) 的 14 项发现（`CR7-1…CR7-14`）。
> **原则**（与 CR6 一致）：最小改动、按风险排序、每项可独立验证、不改需求功能——需要改**需求口径**的项单列为决策项，不夹带进代码改动。
> **验证门槛（每批完成后）**：`npx tsc --noEmit` 0 错 + `npx vitest run` 全绿 + 受影响集成套件全绿（`node web/scripts/verify-all.mjs`）；data-service 侧改动加跑对应离线测试。**开发期不跑 `npm run build`。**
> **反向验证（C34）**：下表标 🔁 的项，须**临时回退修复 → 确认新断言精确失败 → 恢复后通过**，并把失败原文记进本账本。
> **重试纪律**：测试失败最多重试 **3** 次（PLAN.md R9 现行口径）。
> **约束继承清单（改前逐条自查）**：C1 空载荷保护 · C9 浏览器只与 web 通信 · C11 空响应进失败窗口 · **C17/C27 进程内单例挂 `globalThis`** · C21/C30 禁止裸 `float()`/非有限值 · C26 跨类型唯一键含 `type` · C29 限速按逻辑请求计次 · C34 负缓存对称 + 反向验证。
> ✅ **原「D4-① 前置：C18–C34 定义只存在于 git」已被证伪**——实测 34 条定义全在工作树，无需恢复。详见 [CODE-REVIEW.md](CODE-REVIEW.md) 附录。

### 批次划分

| 批次 | 目标 | 项 | 风险 | 前置 |
|---|---|---|---|---|
| **A** | 产出正确性（P1 + R17 缺口） | A1=`CR7-1`、A2=`CR7-2`、A3=`CR7-5` | 低 | 无 |
| **B** | 需求闭环（**须先决策**） | B1=`CR7-3`、B2=`CR7-4` | 低–中 | 主人选定 B1 方案、B2c 文案 |
| **C** | 额度与调度（**须先实测**） | C1=`CR7-7`、C2=`CR7-8`、C3=`CR7-9`、C4=`CR7-10`、C5=`CR7-6` | 中 | C0 实测同步总耗时 |
| **D** | 回归防线 / 观测 / 文档 | D1=`CR7-11`、D2=`CR7-12`、D3=`CR7-13`、D4=`CR7-14` | 低 | 无 |

### 批次 A：产出正确性

**A1 · 技术分析师 `dataBased` 加真实数据门控**（`CR7-1`，P1）🔁

- **做法**（`data-service/app/research/engine.py:120-133`）：
  1. 新增 `kline_available = payload["kline"].get("ok")`（与 `:137` `fund_available`、`:161` `news_available` 同构）；
  2. append 改为 **spread 在前、门控字段在后**：`analysts.append({**r1, "role": "技术分析师", "view": r1["view"], "dataBased": bool(r1.get("dataBased", True)) and kline_available})`——顺带修掉"`**r1` 在后会覆盖硬编码值"的顺序问题；
  3. `:249` 归一化默认值 `a.get("dataBased", True)` → `bool(a.get("dataBased"))`（**fail-closed**：现有三处角色都显式赋值，行为不变；只防未来新增角色漏赋值时默认"有数据"）。
- **验证**：新增离线测试 `data-service/tests/test_cr7_engine_databased.py` 3 项——① kline 不可用 → 技术分析师不进 `debate_input.analysts` 且出现在「缺口说明」；② kline 可用 → 正常进；③ 模型自返 `dataBased:false` 时不被翻真。反向验证：临时改回 `True` → ①精确失败。
- **风险**：低（纯判定，不改 LLM 调用次数与预算）。

**A2 · 研报回读 `/api/kline` 的日期契约**（`CR7-2`，P1）🔁

- **A2-①（必做，低风险）**：`data-service/app/research/adapter.py:30-36` 的 `_iso_days_ago` / `_today_iso` 由 `strftime("%Y%m%d")` 改为 `"%Y-%m-%d"`（web `normalizeRange` 的契约）。**注意勿误改** `ak_stock_disclosures`（`:304-305`）——akshare 入参确实要紧凑 8 位；在两个函数上各加一行注释标明"web 契约=带连字符 / akshare 契约=8 位"。
- **A2-②（建议，需确认）**：`web/lib/kline.ts:86-99` `normalizeRange` 区分「参数缺失」（回落默认）与「格式非法」（返回 `{error}`）。行为变更：`/api/kline?start=20260101` 由静默回落变 400。现有调用方（`ProductCharts`、`page.tsx`、修后的 `adapter`）都传 ISO，不受影响。
- **验证**：web 侧扩 `kline.test.ts`（非法格式 → error；缺失 → 回落）；ds 侧断言 `collect_kline_with_phases` 发出的 `start` 含 `-`（monkeypatch `requests.get` 捕获 params）。反向验证：改回 `"%Y%m%d"` → ds 断言失败。
- **风险**：A2-① 低；A2-② 中（改公共校验语义，须过 test-p2 38 项回归）。

**A3 · ChatUI 180s 中断必须可感知、有出口**（`CR7-5`，P2，R17）

- **做法**：`web/app/chat/ChatUI.tsx:321-349`——① 删/真正使用 `terminated`（现为只读不写的死守卫）；② 在 `done` 事件处置 `gotDoneRef.current = true`；③ while 退出后若 `!gotDone` 则 `setError("回答在 180s 处中断，本条可能不完整——可直接重新发送")`（保留已渲染内容，给出重发出口）；④ 为可测性把判定抽成零依赖纯函数 `web/lib/chat-stream-exit.ts`（`{gotDone, expired}` → `interrupted`），**与 `research-stale.ts` 同一套路**（客户端组件不得 import 牵连 prisma 的模块）。
- **验证**：新增 `chat-stream-exit.test.ts`（done+未到期=正常 / 未 done+到期=中断 / 未 done+未到期=异常退出）。前端组件行为手测一次：把 deadline 临时调到 3s 触发。
- **风险**：低。

### 批次 B：需求闭环（**先决策后动手**）

**B1 · R13 双源交叉验证：接入 or 改判**（`CR7-3`，P2）

现状：`/quote/verified` + `verify_metric` 已实现并有 8 项离线测试，但 **web/MCP/工具三层零调用方**。三选一：

| 方案 | 做法 | 代价 |
|---|---|---|
| **①（推荐）详情页按需核对** | 现状区加「双源核对」按钮 → 新 BFF `GET /api/quote?verify=1` → `/quote/verified`，偏差写入展示的 `note` | 每次多 1 发备源请求，受 R15/C29 额度约束；须"按需"不得默认开 |
| ② 仅 Agent 侧 | `tools.ts` 的 `get_quote` 增可选 `verify?: boolean`（默认 false），LLM 需要核验时才走 | 用户界面看不到"标注"，R13 的"显式标注"仅体现在回答文本 |
| ③ 改判不接入 | 把 PLAN R13 与 G3 的 ✅ 更正为「能力已具备、未接入生产链路」并说明理由 | 零代码；但 R13 交付度下降 |

- **验证**：选 ①/② 则 test-p2 增一条断言（构造偏差 > 阈值 → `note` 含"双源偏差"）；选 ③ 仅文档同步。

**B2 · 港股消费侧接通**（`CR7-4`，P2）

- **B2a 工具枚举**：`web/lib/tools.ts:35,54,73,116` 四处 `enum` 各写各的（`hk` 全缺、`us` 只在两处）→ 抽 `export const PRODUCT_TYPE_ENUM = ["stock","fund","bond","crypto","hk","us"]` 单一来源，四处共用。**须核对 test-p4 19 项**（P4 兼容红线只锁工具**名**不锁 enum，但 LLM 行为可能变化）。
- **B2b 身份画像**：`web/lib/profile.ts:58-81` 补 `hk`（交易所=HK、币种、市值/PE/PB）与 `us` 分支；`profile.test.ts` 加 2 项（港股标的不为"暂无画像数据"）。
- **B2c 币种落地**：`web/lib/data-service.ts` 的 `Quote` 类型补 `currency?: string`（provider 侧 `hk_provider`/`openbb_provider`/`sina_bond_provider` 早已返回该字段，只是 TS 契约漏了）→ 详情页现状区/指标卡、搜索结果、`tools.ts` 的 `toolGetQuote` summary 在 `currency ∉ {CNY, null}` 时追加单位。**待确认文案**：`419.00 港币` / `HK$419.00` / `419.00 HKD`。
- **验证**：单测 + 手测一只 `00700` 详情页；test-p2 增"港股身份区非空且含币种"1 条。
- **风险**：低；B2a 需回归 test-p4/test-p6。

### 批次 C：额度与调度（**先实测 C0**）

**C0 · 前置实测（不改代码）**

记录一次 `POST /api/sync`（全 5 类型）与 `POST /api/market/refresh?type=fund` 的**分类型耗时**与令牌桶占用（`/sync/status` 的 `results[].tookMs` + `snapshot updated=/failedBatches=`），作为 C1/C3/C4 的参数依据。CR6 报告里的"约 15 分钟起"是当时的**推算**值，不得当作实测。

**C1 · 启动补跑冲突**（`CR7-7`，P2，R15/R10）

- **做法**（择一，倾向 a）：**(a)** `sync_scheduler._catch_up_if_needed` 触发前查 `GET /hotspots/status`，若热点 pipeline 正在跑或当日尚未产出 → 延迟到其结束后再跑同步（同进程内也可直接读 `limiter.get_limiter("eastmoney").state()` 判忙）；**(b)** 把同步补跑改为"仅当 web 侧当日 `Product.updatedAt` 早于今天"才跑（需 web 暴露只读状态端点，改动更大）。禁止引入跨进程锁（单进程即可）。
- **验证**：扩 `test_cr6_pipeline.py` 一条"源族被占用时 pipeline 仍在 `HOTSPOT_PIPELINE_TIMEOUT_S` 预算内返回并标注降级"；手测：清 `lastDate` 后同时起双服务，观察热点是否仍降级。
- **风险**：中（涉及调度时序）。

**C2 · 场外基金净值表：空/列缺失必须进失败窗口**（`CR7-8`，P2，C11）🔁

- **做法**：`akshare_provider.py:338-369`——① `_fund_nav_table` 拿到 `None`/`len(df)==0` 时视同失败：写 `_fund_nav_fail_ts` 并抛 `ProviderError`（不得缓存空表 30min）；② `_fund_nav_quotes` 定位不到"单位净值"或"日增长率"列时**上抛**而非 `return {}`（列名变更是上游契约破坏，必须显式降级并带 `note`）。
- **验证**：`test_p2_m8.py` 增 2 项（空 df → 冷却生效且不发第二次全表请求；列缺失 → `ProviderError`）。反向验证：回退 → 断言失败。
- **风险**：低。

**C3 · `/api/sync` 时长与超时口径**（`CR7-9`，P3，依赖 C0）

- **做法**：① 按 C0 实测重设 `web/app/api/sync/route.ts:8` 的 `maxDuration`（或注明"自托管下仅声明性"）与 `data-service/app/sync_scheduler.py:67` 的 `timeout=1800`（建议 ≥ 实测 P95 × 1.5）；② 修 `web/app/api/market/refresh/route.ts:7` 的注释事实错误（"stock 约 2.9 万只" → 实为 `fund 27811 / stock 5913 / bond 1052 / crypto 250`）；③ 读超时不得直接记"失败"——改为 `note: "回调超时，同步可能仍在 web 侧完成，请查 /api/sync 结果或 Product.updatedAt"`（现状会把已成功的同步写成 error，且 `lastDate` 已置位不再重跑，状态失真）。
- **风险**：低（③ 属语义更正）。

**C4 · `/sync/run` 异步化**（`CR7-10`，P3）

- **做法**：照 `hotspot/scheduler.request_run`（`:68-85`）改 `sync_scheduler.run_now`——认领 `running` 后起后台线程、立即返回 `{accepted}`；线程启动失败须回滚 `running`（CR4 已有同类修复）。同步更新 `main.py:259` 的返回体与文档的端点说明。
- **验证**：`/sync/status` 的 `running` 转换可观测；手测 `POST /sync/run` 立即返回。
- **风险**：中（状态语义变化，消费方仅运维/手动）。

**C5 · GET 取数端点 code 校验前移**（`CR7-6`，P2，R15）

- **做法**：抽 `web/lib/validate.ts` 的 `isValidCode()`（正则沿用 `^[\w.-]{1,20}$`，与 `watchlist`/`research/start` 统一），在 `api/kline/route.ts`、`api/quote/route.ts` 于**调用 data-service 之前** 400（当前只判非空 → 任意串都会消耗一发东财令牌）。同时给 `type` 加白名单。
- **验证**：`validate.test.ts` + 两个路由的边界断言（非法 code 不产生 dsGet 调用——用注入/spy 或断言响应码）。
- **风险**：低（需确认无现存调用方传带前缀代码，如 `sh600519`）。

### 批次 D：回归防线 / 观测 / 文档

**D1 · 补回归盲区**（`CR7-11`，P3）

- `web/lib/llm.ts`：SSE 尾帧 flush（C3）、连接超时只约束首字节 / 空闲超时逐块（CR-02）、`tool_calls` name 仅首片赋值（CR4）——三条语义目前**只靠集成测试间接覆盖**。
- `web/lib/tools.ts`：`numOrNull`（**C4 唯一防线**：缺价不得上报 0 元）、9 个工具的成功/降级双分支。
- `web/lib/hotspots.ts`：`(date,title)` 200 字截断去重 + P2002 竞态分支（CR-11）。
- `data-service/scripts/backup_db.py`：**C22 三条加固（integrity_check / `-wal -shm` 还原 / 失败回滚）目前零自动化回归**，而它是全项目唯一破坏性覆盖线上库的脚本——用 tmp 目录构造库 + 损坏备份做离线测试。

**D2 · `_abandoned` 计数竞态**（`CR7-12`，P3）

`timeout.py:66-70`：`t.is_alive()` 判定与置 `box["_abandoned"]` 之间线程跑完 `finally` → 只增不减。改为由 runner 在 `finally` 内用 `threading.Event`/标志位统一裁决（或主线程 +1 后二次确认 `is_alive()`）。仅影响 CR-22 观测可信度，低优先。

**D3 · 分页与慢路径护栏**（`CR7-13`，P3）

`hk_provider.py:287` 加分页上限（对照 `akshare_provider.py:785` 的 `min(pages, 100)`），超限抛 `ProviderError`；`mcp_server.py:91` 的 `list_products` 对 `hk`/超大列表加显式耗时说明或经 `run_with_timeout` 包裹（外部 MCP 客户端视角不应表现为无响应卡死 4 分钟）。

**D4 · 文档失同步**（`CR7-14`，P3）

| # | 项 | 状态 |
|---|---|---|
| 1 | ~~恢复 `PLAN.md` 的 C18–C23 / C26–C34 定义~~ | ✅ **误报，无需恢复**（实测 34 条全在）；原文本已在 `code-review.md:402`、`code-review-fix-plan.md:217`、`:321` 清除 |
| 2 | `Progress.md` 补记 09-19/20 那一整轮 | ✅ **已完成**（见 [PROGRESS.md](PROGRESS.md) 09-18~09-20 条目） |
| 3 | `PLAN.md:257` M7 优化点 3 已被 `lru.py` 推翻 → 改记「已闭环」 | ✅ **已完成**（见 [PLAN.md](PLAN.md) M7 节） |
| 4 | `data-service/app/providers/__init__.py` 注释与实际注册语义对齐（`us` 经 `register_chain(position=0)`，`_QUOTE_REGISTRY` 内无 `us` → `get_provider("us")` 抛 `KeyError` 而 `get_provider_chain("us")` 正常） | ⬜ **待办** |
| 5 | ~~`.workbuddy/memory/MEMORY.md:13` 重试次数 2 → 3~~ | ✅ **已消除**（该目录待删除；用户级记忆已同步更正为 3 次） |

### 执行顺序建议

1. **批次 A**（P1 优先，A1/A2 各配 🔁；半天内可完成）；
2. **批次 B**——待主人定 B1 方案与 B2c 文案；
3. **C0 实测 → C1/C2/C3/C5 → C4**（额度与调度一次改齐，避免反复试）；
4. **D1**（紧随 A/B 补上：P1 两项目前都只有新写的测试在守，回归面要成对）；D4-④ 择机顺带。

### 本轮不做（显式排除，避免反复讨论）

- `CR7-*` 之外的**已核验排除 8 项**（见 [CODE-REVIEW.md](CODE-REVIEW.md) 附录）——已证伪，不改。
- CR6「可优化项」中标 🔵 保留的 5 项（1/3/4/7/8）——维持原决策。
- **G7 写接口完整身份鉴权**：上云 / `WEB_PORT` 对外前再补（当前单机无暴露面）。
- **C31 Dockerfile 进程降权验证** 与任何 Docker 相关改动：按主人指示暂不推进。

---

## CR6 · 执行记录（✅ 已闭环，2026-09-19/20）

> 第一轮·全项目审查（现规范编号 CR6）的 22 项风险 + 7 项需求缺口，分 A/B/C/D 四批执行完毕并验收。
> 完整批次明细（逐项做法、改动文件清单）见 [history/2026-09-18-cr6-批次ABCD执行明细.md](history/2026-09-18-cr6-批次ABCD执行明细.md)。

### 批次完成情况

| 批次 | 项 | 状态 | 本批验证 |
|---|---|---|---|
| **A** | A1–A6（CR-01/02/03/12/13 + CR-15 零风险项） | ✅ 完成 | tsc 0 错 / vitest 101→135 |
| **B** | B1–B8（CR-04/05/07/08/09/11/16/19） | ✅ 完成 | tsc 0 错 / vitest 135 / ds 离线全绿 |
| **C** | C1–C9（CR-06/10/14/17/18/22 + CR-15 其余 + CR-20 评估） | ✅ 完成 | tsc 0 错 / vitest 125 / ds 离线全绿 |
| **D** | G1–G7 需求缺口处置（G2/G3/G4/G5/G6 实现，G1 裁剪，G7 部分） | ✅ 完成 | tsc 0 错 / vitest 135 / ds 离线含 `test_g6_hk`、`test_g3_crosscheck` |
| **验收** | 双服务全量集成 + 冒烟 + 缺陷修复（V1/V2） | ✅ 完成 | tsc 0 错 / vitest **140/140** / 集成 7 套件全绿 / 冒烟 7/8 |
| **G6 补强** | 港股连通性排障 + 多 host 降级 + 分页 + 腾讯备源 | ✅ 完成 | `test_g6_hk` **28/28**（+3 反向验证）/ ds 离线全绿 |

### 决策项落地（用户确认）

| 决策项 | 用户选择 | 落地 |
|---|---|---|
| B1 `busy_timeout` | `connection_limit=1` | `prisma.ts#datasourceUrl` 注入；失败不再永久缓存 |
| B5 快照 null | 保留旧值 | `market-snapshot.ts` 改 `COALESCE(新值, 旧值)` |
| B4/G7 写鉴权 | Origin 校验（轻量） | `request-origin.ts` + 三端点；完整鉴权留上云前 |
| G1 webhook | 显式裁剪 | PLAN M1 划除 + 决策记录 |
| G2/G3/G4/G5/G6 | 全部实现 | 见批次完成情况 |
| C7 每日限额双侧判断（CR-20） | **评估后保留现状** | web 查库（持久兜底）+ ds 内存 `_daily_done`（快速判断）是**有意的双层设计**；主要风险（日期口径错位）已由 C1 消除 |
| CR-15 其余项中评估后不改的 | 保留 | `research-target` 6 位数字误判（仅在意图词命中后调用，收紧会破坏合法识别）；`search` 单字符候选偏斜（`orderBy code asc` 已保证确定性）；`sync` 行 type 取自 payload（provider 契约保证同类型）；进程内单飞多副本（当前单容器部署不触发） |

### 验收中新发现并修复的 2 个缺陷（计划外，集成才暴露）

| 编号 | 结论 | 处理 |
|---|---|---|
| **V1**（高） | `upsertCandles` 原生 INSERT 日期格式与 Prisma 不一致 → `KlineDaily` 日期范围查询漏行 | 修复 + `kline-date-format.test.ts` + 反向验证；test-p2 37/38 → **38/38** |
| **V2**（中） | G2 自动同步用降级备源缩小主数据（转债 1052→329） | 加「降级缩水保护」+ `sync-shrink.test.ts` + 反向验证；test-p1 19/20 → **20/20** |
| **V3**（高） | 港股 provider 三处实现缺陷（akshare 硬编码 CDN 节点 / 列表分页缺失 / 行情误用列表接口）+ BFF 同步超时不足 | `hk_provider.py` 重写 + 腾讯备源；详见 [CODE-REVIEW.md](CODE-REVIEW.md) V3 |

### 最终验证（全绿）

| 套件 | 结果 |
|---|---|
| `npx tsc --noEmit` | ✅ 0 错 |
| `npx vitest run` | ✅ **140/140**（24 文件） |
| 集成 `verify-all`（7 套件） | ✅ 全 exit=0：test-db 16、test-p1 20、test-p2 38、test-p3 27、test-p4 19、test-p5 21、test-p6 21 |
| 冒烟 `smoke.mjs` | ✅ 7/8（第 6 项容器内 health 于本地开发态不适用） |
| data-service 离线 | ✅ 42+6+10+18+9+8+15+7 全绿 |

### ⚠️ 收尾状态

**CR6 的全部改动尚未 git 提交**（工作树 ~75 个未提交路径）。集成套件依赖双服务启动（非 CI 自动）。

---

## CR1–CR5 · 执行记录（✅ 已闭环）

| 轮次 | 处置 | 提交 | 验证证据 |
|---|---|---|---|
| **CR1** | C1–C17 全部修复并固化为约束；O 系列 12 项经用户批准后全部执行完成（B → M → L 三批） | `b22671f`、`f5656d7` | 各批 tsc 0 错 + vitest/集成套件全绿；O 系列执行明细见 [history/2026-09-13-cr1-全项目审查与O系列明细.md](history/2026-09-13-cr1-全项目审查与O系列明细.md) |
| **CR2** | 12 项真实缺陷（含 1 项 P0 死锁）全修；新增 C18–C23 | `3bd73a1` | 当日日志见 [PROGRESS.md](PROGRESS.md) 09-13 |
| **CR3** | 8 项缺陷全修（含 1 项回归 + 1 项不完整修复） | `d6ac165` | ⏳ 无文档记载，待从 `git show d6ac165` 重建，见 [history/2026-09-14-cr3-第三轮重建.md](history/2026-09-14-cr3-第三轮重建.md) |
| **CR4** | P1×5 + P2×12 + P3×25 全部处理并验证；固化为 C26–C33。**唯一未闭环：C31 的 Docker 验证** | `4905095` | 日志见 [PROGRESS.md](PROGRESS.md) 09-15/09-16 |
| **CR5** | P1×2 + P2×1 + 缺口×3 + P3×6；A+B 批 8 项实施并验证（含反向验证 + 全量回归）；固化为 C34。**暂不处理**：CR5-P4 与 CR5-D1/D2/D3 | `4905095` | 日志见 [PROGRESS.md](PROGRESS.md) 09-17 |

### 历史遗留：O 系列优化（2026-09-13 批准并全部执行完成 ✅）

实施顺序 **B → M → L**。每批独立交付并跑回归门槛：`tsc --noEmit` 零错误 + vitest 全绿 + 受影响集成套件（test-p4/p6）全绿。

| 批次 | 状态 | 验证 |
|---|---|---|
| B1 技能/打分重复计算 | ✅ | tsc 0 错 + vitest 65/65 |
| B2 搜索召回稳定化 | ✅ | test-p1 19/20（唯一失败为转债行情富集，属东财限流环境波动，人工 curl 验证富集正常） |
| B3 可观测性 | ✅ | test-p4 19/19 |
| B4 公共逻辑抽取 | ✅ | test-p1/p4 全绿 + data-service 离线 45/45 |
| B5 前端稳定 key / Link | ✅ | tsc 0 错 |
| M1 聊天上下文预算 | ✅ | 新增 `context-budget.ts`（24K 字符可配），test-p4 19/19 |
| M2 快照单飞 | ✅ | test-p1 全绿 |
| M3 缓存 LRU / 任务淘汰 | ✅ | 新增 `lib/lru.ts`；kline/events 换 LRU；research 任务 24h 淘汰 |
| M4 手动抓取异步化 | ✅ | test-p3 28/28（修复初版实现的死锁：`request_run` 置 running 后线程再走 `_single_flight` 直接返回——已改为 `_execute` 直接执行） |
| L1 sync 暂存表换名 | ✅ | 实测 bond 同步 1052 条写入成功（31.9s 含源拉取），FTS 行数一致，检索正常 |
| L2 web 镜像瘦身 | ✅（2026-09-14 补完验证） | 1.62GB → **1.25GB**（`docker images` 口径，-23%），容器内 0.89GB；两容器 healthy、冒烟 **8/8** |
| L3 采集线程治理 | ✅ | adapter 增加信号量（默认 4）+ `collect_stats` 进 `/research/status`；离线 45/45 |

**L2 过程中发现并修复 2 个真缺陷**：① 仅改 `package.json` 未同步 `package-lock.json` → `prisma` CLI 被 `--omit=dev` 误裁 → `migrate deploy` 必失败（固化为 **C24**）；② 在 runner 内先 COPY 再 prune → 体积不降（层语义，固化为 **C25**）。

### 显式不做 / 暂缓（历史决策，维持）

- ChatUI 虚拟化（消息量小，收益低，B5 仅做稳定 key）
- `hotspots ingest` 拉全量 title 去重（量小，已在 C 系列修复口径问题）
- `ProductCharts` 大数组虚拟化（当前 90 点，风险低）
- MCP 服务器进一步功能（HTTP profile 已可用，外部 stdio 第三方 server 保持 disabled 至网络环境允许）
