# 修复账本（FIX-LEDGER）

> **职责**：记录**每一项发现修了没有、怎么验的**。未闭环项置顶，一眼可见。
> 另设「优化候选登记」（非缺陷的改进想法，编号 `OPT-n`）与「待拍板决策」两节。
> 审查发现原文见 [CODE-REVIEW.md](CODE-REVIEW.md)；被压缩掉的过程材料见 [history/](history/)。
>
> **维护规则**：
> ① 看板用**稳定编号 + 一行状态**，不藏进 prose；状态只在本看板维护——关闭时若 [PLAN.md](PLAN.md) 有对应条目，同步更新该条目的结论一行。
> ② 已闭环轮次的正文**只压缩、不重写**——防止在"重述"中引入新错误。
> ③ 修"失败负缓存 / 限流计数 / 熔断计数 / 复查窗口"类问题时必须附**反向验证**（C34）。

> **速览**：想知道"现在该做什么"看这里。**当前未闭环 21 项** = CR7 的 13 项（**11 未修 + CR7-2/CR7-14 部分闭环**；CR7-1 已于 2026-09-24 修复）+ **CR8 的 6 项**（2026-09-24 界面语义审查，方案已全部拍板、代码未动）+ G7 鉴权 + C31 Docker 验证（看板列 25 行 = 21 未闭环 + 1 已修 + 3 别名行；`G3`/`G6 消费侧`/`C31 关联` 为别名，状态指回主行、不在本行复述）；其中 **CR7 侧 3 项等主人拍板**（CR7-3/B1 与 CR7-4/B2c 已于 09-24 拍板，批次 B 可开工）、**CR8 侧 2 项待定**（批次范围 + OPT-2 是否立项，见下「待你拍板」）。优化候选 OPT-1 已落地（2026-09-22 技能路由改 `load_skill`）；OPT-2（新闻层多源合并）2026-09-24 登记，**未查证完不升级为 PLAN 设计**。发现原文在 [CODE-REVIEW.md](CODE-REVIEW.md)，本文件不管"发现了什么"，只管"修没修、怎么验、下一步做什么"。

---

## 🔴 未闭环看板

| 编号 | 事项 | 严重度 | 状态 | 前置 / 卡点 |
|---|---|---|---|---|
| **CR7-1** | 技术分析师 `dataBased` 恒真 → 无 K 线仍进辩论并参与评级 | P1 | ✅ 已修（2026-09-24，A1） | 未提交；测试 `tests/test_cr7_research.py` |
| **CR7-2** | 研报回读 `/api/kline` 日期格式不匹配 → `days` 参数静默失效 | P1 | 🟡 A2-① 已修／A2-② 已拍板待实施（09-24：改 400） | 见批次 A |
| **CR7-3** | R13/G3 交付成「零调用方端点」 | P2 | ⬜ 未修（方案已拍板 09-24：B1 方案 ①） | 详情页「双源核对」按钮 + BFF `GET /api/quote?verify=1`；见批次 B |
| **CR7-4** | 港股消费侧三处断链（工具枚举 / 身份画像 / 币种） | P2 | ⬜ 未修（B2c 文案已拍板 09-24） | 文案定 `419.00 港币`；见批次 B |
| **CR7-5** | ChatUI 180s 静默截断，`terminated` 是死守卫 | P2 | ⬜ 未修 | 无 |
| **CR7-6** | GET 取数端点无 code 校验，可被耗尽东财额度 | P2 | ⬜ 未修 | 无 |
| **CR7-7** | 启动补跑冲突：同步与热点争抢同一源族令牌桶 | P2 | ⬜ 未修 | 需先做 C0 实测 |
| **CR7-8** | 场外基金净值表缓存"成功但空"，全体静默无值 | P2 | ⬜ 未修 | 无（🔁 反向验证） |
| **CR7-9** | `/api/sync` 耗时基线写错 + ds 侧超时把成功记成失败 | P3 | ⬜ 未修 | 依赖 C0 实测 |
| **CR7-10** | `POST /sync/run` 在请求线程内同步跑 15min+ | P3 | ⬜ 未修（异步化已拍板 09-24） | 照 `request_run` 模板改；见批次 C（留下一轮） |
| **CR7-11** | 回归盲区：`llm.ts`/`tools.ts`/`hotspots.ts`/`backup_db.py` 无单测 | P3 | ⬜ 未修 | 建议紧随 CR7-1~5 |
| **CR7-12** | `timeout.py` 的 `_abandoned` 计数窄竞态 | P3 | ⬜ 未修 | 无 |
| **CR7-13** | `hk_provider` 分页无上限 / MCP `list_products("hk")` 无超时 | P3 | ⬜ 未修 | 无 |
| **CR7-14** | 文档/注释漂移 | P3 | 🟡 部分闭环 | ①③ 已处置；② 待办 |
| **CR8-1** | 「降级产出」横幅：一个布尔承载三语义 + 批次级 note 被逐行复制到每张卡 | P2 | ⬜ 未修（方案已拍板 09-24） | **批次二**；需拆 `reasons[]` + 改新闻源序；PLAN R12 与验收项已同步修订；触及 `test_cr6_pipeline.py` |
| **CR8-2** | 「深度解读」名不副实（只是链接，不触发分析、不带热点上下文） | P3 | ⬜ 未修（方案已拍板 09-24） | **批次一**；只改文案为「去分析 <股票名>」 |
| **CR8-3** | 来源链接的标题在后端最后一步被丢弃 → 前端只能渲染 3 个无差别"原文" | P2 | ⬜ 未修（方案已拍板 09-24） | **批次二**；跨服务 payload + 存量 `string[]` 读兼容；**前置实测：东财快讯「链接」列是否有值**（今日零证据） |
| **CR8-4** | 顶部导航随页面滚动，长卡片流下失去一级入口 | P3 | ⬜ 未修（方案已拍板 09-24） | **批次一**；必须与 CR8-2 的 `#research` `scroll-mt` 补偿同批 |
| **CR8-5** | 面包屑硬编码"搜索"，与真实来路不符（反转 `PLAN.md` 面包屑约定） | P3 | ⬜ 未修（方案已拍板 09-24） | **批次一**；4 处调用点 `page`/`loading` 成对改；`Breadcrumbs.tsx` 零消费者即删文件 |
| **CR8-6** | 详情页无页内返回入口（CR8-5 删面包屑后成为唯一回指缺口） | P3 | ⬜ 未修（方案已拍板 09-24） | **批次一**；`router.back()` + 无历史退化「首页」；与 CR8-5 同批 |
| **G3（CR6 遗留）** | R13 端点零调用方 | — | → 见 CR7-3 | 同一件事，状态不在本行复述 |
| **G6 消费侧（CR6 遗留）** | 港股取数侧已闭环，消费侧仍断链 | — | → 见 CR7-4 | 同一件事，状态不在本行复述 |
| **G7（CR6 遗留）** | 写接口完整身份鉴权 | — | ⬜ 未闭环 | **上云 / `WEB_PORT` 对外前必补**；当前单机无暴露面 |
| **C31 验证** | Dockerfile 进程降权（`setpriv`）的镜像构建/运行验证 | — | ⏳ 未验证 | 主人指示暂不推进 Docker；启用前必须先验证容器内 uid、两容器 healthy、`compose exec` 备份正常 |
| **C31 关联** | 任何 Docker 相关改动 | — | → 见 C31 验证 | 同一闸口（主人指示暂缓），状态不在本行复述 |

### ⚠️ 待你拍板（CR8 剩余 2 项；CR7 侧已全部拍板）

> 2026-09-24 已拍板 6 项：**CR7-3/B1 → 方案 ①**（详情页按需核对）；**CR7-4/B2c → `419.00 港币`**；**CR7-2/A2-② → 改 400**；**CR7-10/C4 → 做异步化**；**批次范围 → A 收尾 + B 全量 + D4-①② 同批，C 留下一轮**；**研报回读默认窗口 → 182 天**（补落码，见批次 A 追加项）。结论均已并入对应批次实施计划；CR7-3/B1、CR7-4/B2c 另见 [PLAN.md](PLAN.md) R13/G3 条目。

1. ~~**CR7-3 / B1**~~ ✅ 已拍板（09-24）：走 **① 详情页按需核对**。
2. ~~**CR7-4 / B2c**~~ ✅ 已拍板（09-24）：币种文案定 **`419.00 港币`**（后缀中文单位；CNY 保持现状；映射仅 `HKD→港币`、`USD→美元`，未知值透传原文）。
3. ~~**CR7-2 / A2-②**~~ ✅ 已拍板（09-24）：**改 400**——`normalizeRange` 区分「缺参回落默认」与「格式非法返回 `{error}`」；现有调用方全传 ISO 不受影响，实施须过 test-p2 38 项回归。
4. ~~**CR7-10 / C4**~~ ✅ 已拍板（09-24）：**做异步化**——照 `hotspot/scheduler.request_run`（`:68-85`）模板改 `sync_scheduler.run_now`，认领后立即返回 `{accepted}`，线程启动失败回滚 `running`（CR4 同类修复）；同步更新 `main.py:259` 返回体与端点说明。
5. ~~**批次范围**~~ ✅ 已拍板（09-24）：**A 收尾 + B 全量 + D4-①② 同批推进，C 留下一轮**（C 批次被 C0 实测卡着，实测另择空闲时段单独跑）。
6. **CR8 批次范围**：是否按「批次一 = CR8-2/4/5/6（纯 UI，可先出 `/ui-demo`）→ 批次二 = CR8-1/3（跨服务 payload）」两批推进？（详见下「CR8 · 实施计划」）
7. **OPT-2**：新闻层多源合并是否立项？（**未实测完不升级为 PLAN 设计**；且它是减少 CR8-1 ③ 噪声的唯一源头手段）

### 🧪 优化候选登记（OPT-n）

> 与上面的**缺陷**看板分开：这里放"**可以更好**"的想法，不是"**坏了**"的问题。
> 每条必须写明**来源**与**采用前要查证什么**；**未查证完不升级为 PLAN 的设计**。

| 编号 | 候选 | 针对 | 状态 | 备注 |
|---|---|---|---|---|
| **OPT-1** | 用**类型化判断原语**替代技能触发词子串匹配——不写死子串，而把"这句话属于哪个技能"作为一次**结构化判断**交给模型，代码只消费结果 | M7 优化点 1（[PLAN.md](PLAN.md)），`web/lib/skills.ts:175` | ✅ **已落地**（2026-09-22，`SKILL_ROUTER=llm` 默认档上线，commit `10745ff`） | 结论摘要见下；评估证据与逐文件明细见 [history](history/2026-09-22-opt1-路线C-技能路由改造.md) |
| **OPT-2** | **新闻层多源合并（fusion）**：把 `fetch_news` 从"任一源成功即返回"改为"多源并集 + 标题相似度去重 + 择优喂结构化" | CR8-1 与 CR8-3 的共同上游（`PLAN.md` M8/R15 现为 failover 语义；fusion 先例是行情层 R13） | ⏳ **待拍板，未查证** | **采用前必须先实测两件事**：① 东财快讯的「链接」列 akshare 是否真填值（今日 9 行 digest 全是 tavily/cls 批次，东财从未被调用，零证据）；② 东财新闻改为"每次必调"后 `map_board_products` 的令牌获取率——`eastmoney` 桶单次 pipeline 内已有三处争抢（`_em_global_news:159`/`_board_names:255`/`map_board_products:498`，后者每 topic×board 各一次）。**在实测完成前不得升级为 PLAN 设计** |

**OPT-1 结论摘要（2026-09-22）**：三条路线评估——TypeSafe Jev（境外 SaaS：聊天内容出境 + 新凭据/SDK 依赖 + 官方明示 CJK 不保证 + TTFT 同步路径硬伤）作废；Laya（自托管、支持 zh）因 Python/torch 与 web（Node）侧同步调用点架构错配、镜像重量、成熟度未验证，未采纳留作备选；**拍板走路线 C**——技能 meta 常驻 system prompt，注册内置工具 `load_skill` 由主 LLM 自主拉取正文（现有 LLM、零新依赖），`SKILL_ROUTER` 三档开关（keyword 保留作 env 回滚）。当日实施并验收：`vitest` **148/148**、`test-p6` llm 档 **24/24**、真实 LLM 行为评估**加载率 100%（≥90%）/ 误加载率 0%（≤10%）→ 达标，无需退 hybrid**。

---

## CR8 · 实施计划（⬜ 未开始，待批准）

> **依据**：[CODE-REVIEW.md](CODE-REVIEW.md) 的 `CR8-1…CR8-7`（发现原文与行号锚点只在那里，本节不复述）。
> **状态**：CR8-1…6 **方案已于 2026-09-24 全部拍板，代码一行未动**；主人要求**先出可看的 demo 再落真改动**。CR8-7 转 `OPT-2` 待拍板。
> **分批原则**：按**爆炸半径**而非改动量分批——纯 UI 项（眼睛可验收）与跨服务契约项（需重跑集成测试）不混批，否则前者被后者拖住。
> **验证门槛**：批次一 `npx tsc --noEmit` 0 错 + **人工点击验收**（实测：24 个 vitest 文件全部是 lib/API 逻辑测试，**零 UI 组件测试覆盖**，`npx vitest run` 对本批无判别力）；批次二加跑 `test_cr6_pipeline.py` 与 `node web/scripts/verify-all.mjs` 受影响套件。**开发期不跑 `npm run build`。**
> **约束继承清单（改前逐条自查）**：C9 浏览器只与 web 通信 · C17/C27 进程内单例挂 `globalThis` · C29 限速按逻辑请求计次 · **C34 负缓存对称 + 反向验证**（批次二的源序改动触及限流/降级路径，标 🔁）。
> **重试纪律**：测试失败最多重试 **3** 次（PLAN.md R9）。

### 批次划分

| 批次 | 项 | 性质 | 风险 | 前置 |
|---|---|---|---|---|
| **一（UI）** | CR8-2 改名、CR8-4 固定导航、CR8-5 删面包屑、CR8-6 返回入口 | 不碰数据链路 | 低 | 先出 `/ui-demo`（临时路由 + mock 数据，不动生产组件），看完再落真改动 |
| **二（契约）** | CR8-1 `reasons[]` 拆分 + 新闻源序、CR8-3 `{url,title}` 透传 | 跨服务 payload + 存量数据读兼容 | 中 | CR8-3 需先实测东财「链接」列是否有值；CR8-1 的 PLAN 同步（R12 + 验收项 + 界面约定表）**已于 2026-09-24 改毕** |
| **三（数据层）** | `OPT-2` 新闻层多源合并 | 取数模型变更 | 高 | 两项实测 + 待拍板，不进本批 |

### 不可拆的耦合（同批硬约束）

| 耦合 | 若拆开的后果 |
|---|---|
| CR8-4 固定导航 ↔ CR8-2 的 `#research` 锚点 | 跳转后目标标题被固定头部压住 |
| CR8-5 删面包屑 ↔ CR8-6 加返回 | 详情页没有任何页内回指入口 |
| CR8-5 的 `page.tsx` ↔ `loading.tsx` | 面包屑在导航期间闪一下（4 处调用点必须成对） |
| CR8-1 源序 ↔ CR8-3 链接可得性 | 主源若选成财联社电报（`url` 恒空）→「相关文章」永久空白 |
| CR8-1 `reasons[]` ↔ OPT-2 | 合并后"某源缺失"成常态，布尔表达不了，不预留就要返工 |

---

## CR7 · 修复计划（🟡 进行中：A1/A2-① 已修已提交 `13be2cf`；范围已拍板——A 收尾 + B 全量 + D4-①② 同批，C 留下一轮）

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
| **A** | 产出正确性（P1 + R17 缺口） | A1=`CR7-1`、A2=`CR7-2`、A3=`CR7-5`；**收尾追加**：A2-② 改 400（已拍板）+ A2-③ 回读窗口 182 天（已拍板）+ CR7-14-④ 注释对齐 + A1 反向验证实证补跑 | 低 | 无 |
| **B** | 需求闭环 | B1=`CR7-3`（方案 ① 已拍板）、B2=`CR7-4`（B2c 文案已拍板） | 低–中 | ~~主人选定 B1 方案、B2c 文案~~ 已拍板（09-24），可开工 |
| **C** | 额度与调度（**须先实测**；**留下一轮**） | C1=`CR7-7`、C2=`CR7-8`、C3=`CR7-9`、C4=`CR7-10`（异步化已拍板）、C5=`CR7-6` | 中 | C0 实测同步总耗时 |
| **D** | 回归防线 / 观测 / 文档 | D1=`CR7-11`、D2=`CR7-12`、D3=`CR7-13`、D4=`CR7-14`（**D4-①② 已并入本批 A 收尾**；D4-④ 择机） | 低 | 无 |

### 批次 A：产出正确性

**A1 · 技术分析师 `dataBased` 加真实数据门控**（`CR7-1`，P1）🔁

- **做法**（`data-service/app/research/engine.py:120-133`）：
  1. 新增 `kline_available = payload["kline"].get("ok")`（与 `:137` `fund_available`、`:161` `news_available` 同构）；
  2. append 改为 **spread 在前、门控字段在后**：`analysts.append({**r1, "role": "技术分析师", "view": r1["view"], "dataBased": bool(r1.get("dataBased", True)) and kline_available})`——顺带修掉"`**r1` 在后会覆盖硬编码值"的顺序问题；
  3. `:249` 归一化默认值 `a.get("dataBased", True)` → `bool(a.get("dataBased"))`（**fail-closed**：现有三处角色都显式赋值，行为不变；只防未来新增角色漏赋值时默认"有数据"）。
- **验证**：新增离线测试 ~~`data-service/tests/test_cr7_engine_databased.py`~~（实际落名 `test_cr7_research.py`，见下实施记录）3 项——① kline 不可用 → 技术分析师不进 `debate_input.analysts` 且出现在「缺口说明」；② kline 可用 → 正常进；③ 模型自返 `dataBased:false` 时不被翻真。反向验证：临时改回 `True` → ①精确失败。
- **风险**：低（纯判定，不改 LLM 调用次数与预算）。
- **实施（2026-09-24，未提交）**：与计划有一处形态差异——append 采用**与角色 2/3 同构**的 spread-排除式（`"dataBased": bool(r1.get("dataBased", True)) and bool(kline_available)` + `**{k: v for k, v in r1.items() if k != "dataBased"}`），同样消除"`**r1` 在后覆盖门控"的顺序问题；`:258` 归一化改 fail-closed（缺 `dataBased` 一律视为无据）。测试落在与 A2 合并的 `data-service/tests/test_cr7_research.py`（CR7-1 侧 12 项断言）。**反向验证**以成对断言实现：有 K 线必判 `True`（证明门控不是恒假桩）、模型自报 `false` 不被翻真、模型自报 `true` 不越过缺口；"临时改回 `True` 再跑"的实证被执行权限拦截，未执行 ⏳。
- **验证证据**：`test_cr7_research` 22/22；回归无破坏——`test_cr6_lru` 18 / `test_cr6_pipeline` 10 / `test_cr6_timeutil` 6 / `test_g3_crosscheck` 8 全绿，`vitest` 148/148（web 侧未改动），`compileall app` 0 错。
- **跨语言契约实测（09-24）**：从 `web/lib/kline.ts:91` 原样抽出正则 `^\d{4}-\d{2}-\d{2}$`，对 `collect_kline_with_phases("stock","600519")` 实发的参数做对账 → `start=2026-05-27`、`end=2026-09-24`、跨度 **120 天**、web 侧接受、`ok=True`。另核 `MAX_RANGE_DAYS = 366×5 = 1830`（`kline.ts:44`）→ 120 天远低于上限，**修复不会把"静默回落"变成"range too large 报错"**。

**A2 · 研报回读 `/api/kline` 的日期契约**（`CR7-2`，P1）🔁

- **A2-①（必做，低风险）**：`data-service/app/research/adapter.py:30-36` 的 `_iso_days_ago` / `_today_iso` 由 `strftime("%Y%m%d")` 改为 `"%Y-%m-%d"`（web `normalizeRange` 的契约）。**注意勿误改** `ak_stock_disclosures`（`:304-305`）——akshare 入参确实要紧凑 8 位；在两个函数上各加一行注释标明"web 契约=带连字符 / akshare 契约=8 位"。
- **A2-②（已拍板 09-24：改 400）**：`web/lib/kline.ts:86-99` `normalizeRange` 区分「参数缺失」（回落默认）与「格式非法」（返回 `{error}`）。行为变更：`/api/kline?start=20260101` 由静默回落变 400。现有调用方（`ProductCharts`、`page.tsx`、修后的 `adapter`）都传 ISO，不受影响。
- **验证**：web 侧扩 `kline.test.ts`（非法格式 → error；缺失 → 回落）；ds 侧断言 `collect_kline_with_phases` 发出的 `start` 含 `-`（monkeypatch `requests.get` 捕获 params）。反向验证：改回 `"%Y%m%d"` → ds 断言失败。
- **风险**：A2-① 低；A2-② 中（改公共校验语义，须过 test-p2 38 项回归）。
- **实施（2026-09-24，未提交）**：**A2-① 已落**——`adapter.py:30-38` 两个函数改 `"%Y-%m-%d"`，定义上方补 3 行契约注释（web 侧要连字符 / akshare 侧要 8 位）；`ak_stock_disclosures` 的 `:304-305` 保持紧凑格式未动。断言在 `test_cr7_research.py`（CR7-2 侧 10 项）：`start`/`end` 匹配 web 的 `^\d{4}-\d{2}-\d{2}$`、**显式断言不再是紧凑 8 位**（回退即失败）、`days=120/30` 跨度真实生效（旧缺陷下两者都被回落成 90 天、无从区分）、`end` 为北京时区当日、cninfo 侧仍为 8 位（防后续"统一日期格式"误改）。**A2-② 未做**（已拍板改 400，随 A 收尾实施）。
- **A2-③ 追加项（拍板 09-24：回读默认窗口定 182 天）**：`13be2cf` commit message 写了"回读窗口定为 182 天（对齐详情页 6M 预设）"但**代码未落**——`adapter.py:121` 仍为 `days=120`，唯一调用点 `collect_all`（`adapter.py:333`）未传参。收尾时补：默认值改 182 + `test_kline_days_window_actually_applied` 的 120 断言同步更新（2026-09-24 对账发现，同日拍板补落码）。

**A3 · ChatUI 180s 中断必须可感知、有出口**（`CR7-5`，P2，R17）

- **做法**：`web/app/chat/ChatUI.tsx:321-349`——① 删/真正使用 `terminated`（现为只读不写的死守卫）；② 在 `done` 事件处置 `gotDoneRef.current = true`；③ while 退出后若 `!gotDone` 则 `setError("回答在 180s 处中断，本条可能不完整——可直接重新发送")`（保留已渲染内容，给出重发出口）；④ 为可测性把判定抽成零依赖纯函数 `web/lib/chat-stream-exit.ts`（`{gotDone, expired}` → `interrupted`），**与 `research-stale.ts` 同一套路**（客户端组件不得 import 牵连 prisma 的模块）。
- **验证**：新增 `chat-stream-exit.test.ts`（done+未到期=正常 / 未 done+到期=中断 / 未 done+未到期=异常退出）。前端组件行为手测一次：把 deadline 临时调到 3s 触发。
- **风险**：低。

### 批次 B：需求闭环（**先决策后动手**）

**B1 · R13 双源交叉验证：接入详情页**（`CR7-3`，P2）——**方案 ① 已拍板（2026-09-24）**

现状：`/quote/verified` + `verify_metric` 已实现并有 8 项离线测试，但 web/MCP/工具三层零调用方。~~三选一~~ → **主人拍板走 ① 详情页按需核对**（理由：R13 的"显式标注"必须落在用户可见路径；② 的标注只进 LLM 回答文本、是否传参不可控，模糊态只是下沉一层；③ 舍弃已建成资产）。未选：~~② 仅 Agent 侧~~、~~③ 改判不接入~~。

- **做法**：现状区加「双源核对」按钮 → 新 BFF `GET /api/quote?verify=1` → `/quote/verified`，偏差写入展示的 `note`。两个实施约束：① 新 GET 路由**带 `CODE_SET` 校验**（与 C5/CR7-6 同口径，不新开无校验口子）；② 备源不可用/验证失败按 **R16** 如实展示 note（如"备源不可用，未能交叉验证"），不静默只显主源价。每次多 1 发备源请求，落腾讯/新浪桶（非东财受限源族），按需触发可承受。
- **验证**：test-p2 增一条断言（构造偏差 > 阈值 → `note` 含"双源偏差"）；手测详情页按钮一次。

**B2 · 港股消费侧接通**（`CR7-4`，P2）

- **B2a 工具枚举**：`web/lib/tools.ts:35,54,73,116` 四处 `enum` 各写各的（`hk` 全缺、`us` 只在两处）→ 抽 `export const PRODUCT_TYPE_ENUM = ["stock","fund","bond","crypto","hk","us"]` 单一来源，四处共用。**须核对 test-p4 19 项**（P4 兼容红线只锁工具**名**不锁 enum，但 LLM 行为可能变化）。
- **B2b 身份画像**：`web/lib/profile.ts:58-81` 补 `hk`（交易所=HK、币种、市值/PE/PB）与 `us` 分支；`profile.test.ts` 加 2 项（港股标的不为"暂无画像数据"）。
- **B2c 币种落地**：`web/lib/data-service.ts` 的 `Quote` 类型补 `currency?: string`（provider 侧 `hk_provider`/`openbb_provider`/`sina_bond_provider` 早已返回该字段，只是 TS 契约漏了）→ 详情页现状区/指标卡、搜索结果、`tools.ts` 的 `toolGetQuote` summary 在 `currency ∉ {CNY, null}` 时追加单位。**文案已拍板（2026-09-24）：`419.00 港币`**（后缀中文单位——中文 UI 零歧义、港股/美股同屏时避免 `HK$`/`$` 误读、LLM 中文回答可直接复用；映射仅 `HKD→港币`、`USD→美元`，未知值透传原文；CNY 保持现状）。
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

**C4 · `/sync/run` 异步化**（`CR7-10`，P3）——**已拍板（2026-09-24）：做**（C 批次整体留下一轮，实施时照此执行）

- **做法**：照 `hotspot/scheduler.request_run`（`:68-85`）改 `sync_scheduler.run_now`——认领 `running` 后起后台线程、立即返回 `{accepted}`；线程启动失败须回滚 `running`（CR4 已有同类修复）。同步更新 `main.py:259` 的返回体与文档的端点说明。
- **验证**：`/sync/status` 的 `running` 转换可观测；手测 `POST /sync/run` 立即返回。
- **风险**：中（状态语义变化，消费方仅运维/手动）。

**C5 · GET 取数端点 code 校验前移**（`CR7-6`，P2，R15）

- **做法**：**新建**共享 code 校验（2026-09-24 核对：当前**不存在** `web/lib/validate.ts`，也**没有** `isValidCode()`；正则 `CODE_SET = /^[\w.-]{1,20}$/` 现分别硬写在 `api/research/start/route.ts:7` 与 `api/watchlist/route.ts:13` 两处）——提为单一来源后，在 `api/kline/route.ts`、`api/quote/route.ts` 于**调用 data-service 之前** 400（当前只判非空 → 任意串都会消耗一发东财令牌）。同时给 `type` 加白名单。
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

### 处置结果总览（CR-01..22 + G1–G6）

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
| CR-15 | P3 | ✅/🔵 | 见 `history/` 归档「CR-15 逐项」 | 混合 |
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
| G6 | — | ✅ | `data-service/app/providers/hk_provider.py`（重写）+ `tencent_provider.py`（腾讯备源） | `test_g6_hk.py` 28 项 + 3 反向验证 |

> ⚠️ **本表 G3/G6 的 ✅ 已被 CR7 修正**：CR7-3 指出 G3 端点**零调用方**（已复核确认）、CR7-4 指出 G6 消费侧三处断链。最终状态见上方未闭环看板。

### 决策项落地（用户确认）

> 决策原文见 [PLAN.md](PLAN.md)「决策记录」（G1–G7 决策的唯一来源）；此处只记落地证据。

| 决策项 | 用户选择 | 落地 |
|---|---|---|
| B1 `busy_timeout` | `connection_limit=1` | `prisma.ts#datasourceUrl` 注入；失败不再永久缓存 |
| B5 快照 null | 保留旧值 | `market-snapshot.ts` 改 `COALESCE(新值, 旧值)` |
| B4/G7 写鉴权 | Origin 校验（轻量） | `request-origin.ts` + 三端点；完整鉴权留上云前 |
| G1 webhook | 显式裁剪 | PLAN M1 划除 + 决策记录 |
| G2/G3/G4/G5/G6 | 全部实现 | 见批次完成情况 |
| C7 每日限额双侧判断（CR-20） | **评估后保留现状** | web 查库（持久兜底）+ ds 内存 `_daily_done`（快速判断）是**有意的双层设计**；主要风险（日期口径错位）已由 C1 消除 |
| CR-15 其余项中评估后不改的 | 保留 | `research-target` 6 位数字误判（仅在意图词命中后调用，收紧会破坏合法识别）；`search` 单字符候选偏斜（`orderBy code asc` 已保证确定性）；`sync` 行 type 取自 payload（provider 契约保证同类型）；进程内单飞多副本（当前单容器部署不触发） |

### 可优化项（9 项结论）

| # | 项 | 处置 |
|---|---|---|
| 1 | `gatherCandidates` FTS→IN 补全可合并为单查询 | 🔵 保留（当前正确，收益有限） |
| 2 | `callMcpTool` 可缓存 tool-name → binding 映射 | ✅ 已按 `mcp_<server>_` 前缀定位目标 server（见 CR-13） |
| 3 | `mcp.ts` 配置可缓存（按 mtime 失效） | 🔵 保留（配置小） |
| 4 | `rebuildFts` 可评估按 type 增量维护 | 🔵 保留（34k 行可接受） |
| 5 | `kline.ts` 批量 upsert 替代逐行 create | ✅ 已实现（分块 `INSERT OR IGNORE`） |
| 6 | 研报采集泄漏线程阈值告警 | ✅ 已实现（`abandoned_count()` + `/health` 暴露，见 CR-22） |
| 7 | `sync.ts`/`market-snapshot.ts` 的 EM 限速常量抽公共配置 | 🔵 保留（重复度低） |
| 8 | ChatUI 研报推送可评估独立成 `/api/events/stream` | 🔵 保留（现状可用） |
| 9 | `DELETE` 等路径的异常吞并应改为区分错误码 | ✅ 已实现（见 CR-15） |

### 验收中新发现并修复的缺陷（计划外，单测覆盖不到）

#### V1（高）· KlineDaily 原生写入的日期格式与 Prisma 不一致 → 日期范围查询静默漏行

- **发现于**：test-p2 的 R13 交叉验证断言失败（`kline=1266.98` vs `quote.price=1257.12`，偏差 0.784%）。
- **根因**：为优化逐行写（CR-15 项），`upsertCandles` 改为原生 `INSERT OR IGNORE` 时**日期参数传了 ISO 字符串**；而 Prisma 对 SQLite DateTime 存的是 **Unix 毫秒整数**（实测 `typeof(date)='integer'`）。文本行与 Prisma 生成的 `date >= ? / <= ?`（数字比较）不匹配 → 这些行在**带日期范围的查询中被静默漏掉**（实测污染 3 行）。
- **影响**：K 线数据"写了但读不到"，详情页少一根 K 线、缓存天数虚高、R13 交叉验证失败。**属静默数据不一致**（最危险的一类）。
- **修复**：`web/lib/kline.ts` 改传 `dayStart(c.date).getTime()`；当时另有一次性数据修复脚本 `web/scripts/fix-kline-date.mjs`——**2026-09-24 核对：该脚本当时未入库、现已不在仓库**（`web/scripts/` 下同类脚本仅存 `fix-fts.mjs`），故其数据修复动作不可复现；回归由 `web/lib/kline-date-format.test.ts` + `kline-headtail.test.ts` 守护。一次性脚本用完即删属预期，此处只登记"复现路径已断"，`docs/history/2026-09-18-cr6-批次ABCD执行明细.md` 末段所述"未提交故丢失"的归因已由 FIX-LEDGER ① 更正（CR6 代码已入库，是该脚本本身未入库）。
- **回归防线**：`web/lib/kline-date-format.test.ts`；**反向验证**：临时回退为 `toISOString()` → 断言精确失败 → 恢复后通过。
- **效果**：test-p2 37/38 → **38/38**。

#### V2（中）· G2 自动同步会用降级备源"缩小"主数据

- **发现于**：test-p1 失败（`bond=329 < 500`），而此前全量为 1052。
- **根因**：G2 新增的每日同步在凌晨自动执行过一次（`/sync/status` runs=1），当时东财限流 → 转债列表降级到**新浪 cov_spot（约 320 只）**；而全量替换语义（先删后插）会用这 329 条**覆盖**原有 1052 条 → **主数据静默劣化**。这是 G2 落地后与 R15 降级的**交互副作用**。
- **修复**：`web/lib/sync.ts` 在空载荷保护（C1）之外增加**降级缩水保护**——新载荷 < 现有条数 70% 时保留旧数据并显式报错，等主源恢复后再全量更新。
- **回归防线**：`web/lib/sync-shrink.test.ts`（4 项）+ 反向验证。
- **效果**：test-p1 19/20 → **20/20**。

#### V3（高）· 港股 provider 三处实现缺陷（2026-09-20 用户本地验证驱动发现）

> 由用户本地 `POST /api/sync?type=hk` 失败驱动排查，属**集成/真实环境**才暴露的问题。详细约束见 [CONSTRAINTS.md §C-3](CONSTRAINTS.md)。

- **V3-a 依赖 akshare 硬编码 CDN 节点**：`hk_provider` 初版复用 akshare `stock_hk_spot_em`，而其**硬编码 `72.push2.eastmoney.com`**——该节点在用户网络不可达（`RemoteDisconnected`），同族 `push2delay`/`7.push2` 却返回 200 真实数据。**等于绕过了本项目已有的多 host 降级能力**。→ 改为直连东财 + 多 host 按序降级。
- **V3-b 列表分页缺失**：东财港股 `clist/get` **忽略大分页参数**（`pz=100/1000/10000` 均只返回 100 条），港股 `total≈4707` → 初版单请求**只拿到 100 条**，`00700` 腾讯控股根本不在其中。→ 按 `total` 分页遍历（实测取满 4707 只）。
- **V3-c 行情路径误用列表接口（性能红线）**：初版 `get_quote` 复用列表快照 → **查单个港股需拉全量 4700 条、耗时约 4 分钟**。→ 快/慢路径分离：单股 `stock/get`、批量 `ulist.np`（各 1 次请求）、全量列表 `clist/get` **仅每日同步调用**；并由单测 `test_quote_does_not_trigger_list_paging` **锁为红线**。
- **修复**：`hk_provider.py` 重写；**新增腾讯港股备源**（`tencent_provider` 的 `_hk_symbol`/`_symbol_for` + `register_chain(["hk"], …, position=1)`）。
- **回归防线**：`test_g6_hk.py` 9 → **28 项**；**3 处反向验证**（削弱多 host、移除类型分派、行情改用列表接口）均精确失败。
- **V3-d（核对中新发现）**：`web/lib/sync.ts` 拉取 `/products` 的超时为 180s，而港股列表分页实测约 236s → **港股同步必然超时**。→ 超时放宽至 600s。

### 最终验证（全绿）

| 套件 | 结果 |
|---|---|
| `npx tsc --noEmit` | ✅ 0 错 |
| `npx vitest run` | ✅ **140/140**（24 文件） |
| 集成 `verify-all`（7 套件） | ✅ 全 exit=0：test-db 16、test-p1 20、test-p2 38、test-p3 27、test-p4 19、test-p5 21、test-p6 21 |
| 冒烟 `smoke.mjs` | ✅ 7/8（第 6 项容器内 health 于本地开发态不适用） |
| data-service 离线 | ✅ 42+6+10+18+9+8+15+7 全绿 |

### ⚠️ 收尾状态

CR6 全部改动已随项目结构调整提交 `2efda87`（2026-09-20）入库——**代码与测试均在库内**，当时未单独提交是因与文档迁移同批。集成套件依赖双服务启动（非 CI 自动）。

---

## CR1–CR5 · 执行记录（✅ 已闭环）

| 轮次 | 处置 | 提交 | 验证证据 |
|---|---|---|---|
| **CR1** | C1–C17 全部修复并固化为约束；O 系列 12 项经用户批准后全部执行完成（B → M → L 三批） | `b22671f`、`f5656d7` | 各批 tsc 0 错 + vitest/集成套件全绿；O 系列执行明细见 [history/2026-09-13-cr1-全项目审查与O系列明细.md](history/2026-09-13-cr1-全项目审查与O系列明细.md) |
| **CR2** | 12 项真实缺陷（含 1 项 P0 死锁）全修；新增 C18–C23 | `3bd73a1` | 当日日志见 [PROGRESS.md](PROGRESS.md) 09-13 |
| **CR3** | 8 项缺陷全修（含 1 项回归 + 1 项不完整修复） | `d6ac165` | 已于 2026-09-20 从 `git show d6ac165` 重建，见 [history/2026-09-14-cr3-第三轮重建.md](history/2026-09-14-cr3-第三轮重建.md) |
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
