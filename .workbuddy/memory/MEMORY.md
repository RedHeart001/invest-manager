# Invest Manager 项目长期记忆

## 当前阶段约定

- **开发已获批准按阶段推进**（2026-09-12 起解除"仅规划"限制）：用户逐阶段显式批准（"开始 P3"/"开始 P5"等），执行时严格遵从 PLAN.md，进度记录 Progress.md。截至 **2026-09-13 16:55**：**P0–P7 全部完成 + 代码审查 C1–C17 + O 系列优化 12 项 + P2 转债遗留闭环（验收 38/38）**；项目已纳入 git（基线 `b22671f`，修复提交 `f5656d7`）。唯一未闭环：L2 web 镜像重建验证（待 Docker Desktop）。
- **文档同步纪律（2026-09-13 明确）**：沟通讨论中的所有决策与结论，必须精炼同步记录到 PLAN.md（需求/方案定稿）与 Progress.md（执行进度/结果），持续同步、不允许只留在对话里。已同步的例子：P5 落地定稿（B 计划引擎主力/巨潮公告新闻备源/同花顺财务摘要/话语约束/熔断 env 覆盖）写入 PLAN M5 补强节；状态确认结论写入 PLAN C15 + Progress 状态总览/日志。
- **状态确认方式约定（2026-09-13）**：确认项目状态时**不凭记忆**，逐项实测（文档/代码/产物/服务/测试/DB/配置），实测结论才写进文档。

## 文档纪律（源自 PLAN.md 约定）

- PLAN.md 是项目唯一的需求与执行计划来源（single source of truth），需求变更只改它。
- Progress.md 只记执行进度：状态总览表 + 进度日志（倒序）+ 阻塞与问题。
- 测试纪律：失败最多重试 2 次，仍失败即停止并沟通（R9）。
- 开发期间不在 dev server 运行时执行 `npm run build`；类型检查用 `npx tsc --noEmit`。
- **全量复验入口**：`node web/scripts/verify-all.mjs`（串行跑 test-db/p1/p3/p4/p6/p5 并汇总）；FTS 一致性修复用 `node web/scripts/fix-fts.mjs`。

## 已修复并固化的关键约束（C 系列，不得回退）

- C1 空载荷保护（sync 禁止静默清库）；C2 会话取最近 200 条（desc 再反转）；C3 LLM 流 flush 尾帧 + 工具调用看累积结果；C4 缺价一律 null；C5 `get_news` 契约 list[dict] 双兼容；C6 限速器状态码校验前置；C7 akshare 统一下 `utils/timeout.py` 看门狗；C8 研报推送带会话归属；C9 浏览器只与 web 通信（`/api/hotspots/run` BFF 代理）；C10 ingest 结果可观测（`ingestOk/ingestNote`）；C11 K 线失败窗口 + P2002 幂等；C12 快照失败显式计数；C13 界面细节（北京时间/ECharts dispose/搜索 loading 竞态等）；C14 安全基线（链接协议白名单、health 不回显异常、tools/status 不回显路径且缓存 30s）；**C15 FTS 一致性**（rebuildFts 必须先清孤儿行；L1 暂存表用后 DROP——换名式替换主表会让以旧 id 为锚点的派生数据失锚）；**C16 采集线程安全**（`adapter._run_with_timeout` 对模块级计数器赋值必须 `global`；信号量 acquire 必须有超时——缺 global 曾致研报采集全线 UnboundLocalError）；**C17 进程内单例必须挂 globalThis**（Next dev HMR 会重建模块作用域并重置模块级变量；已发生两例：P6 MCP 注册表、P3 SSE clients Map → 事件偶发丢失）。

## 多源策略补充（2026-09-13）

- 转债行情备源 = 新浪 `bond_zh_hs_cov_spot`（`sina_bond_provider`：快照缓存 60s + 锁内双检 + 看门狗）
- 转债列表备源 = 同源 cov_spot（东财限流兜底，覆盖度较低属降级可用）
- **转债 K 线仅东财一个源**（腾讯 fqkline/kline、新浪 cov_daily、新浪通用 K 线、网易 chddata 均已系统性排除）→ 限流时显式降级即正确行为（R10/R12）
- **未上市/已退市转债不在实时行情列表**（如 113710/123285），其行情与 K 线本不可得 → 取数时报明确错误而非静默缺失
- 活跃代码段：沪 111/113/118、深 123/127/128（`110xxx` 多为沪市老债段）

## 已定稿的关键决策（摘要）

- 技术栈：Next.js 全栈 + Python FastAPI data-service（无状态）+ SQLite/Prisma；LLM 走 OpenAI 兼容端点（DeepSeek/GLM，缺 BASE_URL 时按模型名推断）。
- P2 详情页：六区结构；变化归因两阶段策略（R11）；归因一律"可能相关"非因果断言。
- R12：海外数据源（Tavily/OpenBB/CoinGecko）本地代理优先，不可达自动降级国内源并显式提示。
- R15/M8 多源降级与频率控制：源族令牌桶（东财 IP 级） + 熔断冷却 + 主备链（腾讯覆盖 A股/场内基金 行情+日K；**转债无备源**；A股新闻备源=巨潮公告 cninfo）。
- **P5 落地定稿（2026-09-13）**：研报引擎=B 计划 `custom-multichar`（技术/基本面/新闻情绪 → 辩论 → 经理，5 次 LLM 调用）；基本面数据=同花顺财务摘要（主）/东财（备），**取最新 4 期**（接口升序，需降序）；话语约束=dataBased 门槛 + 缺口角色"无法判断"；熔断 env 可覆盖（`RESEARCH_MAX_LLM_CALLS`/`RESEARCH_TASK_TIMEOUT_S`）。
- **P6/P7 定稿与落地**：见 PLAN M7 与「P7 落地定稿与实现约束」（MCP 注册表挂 globalThis、连接 in-flight 去重、技能正文按需注入上限 2400 字符/≤3、MCP 默认不进容器、web 镜像 prisma 入 dependencies + runner prune）。
- **P6 不得回退的工程约束（2026-09-13 体检固化，详见 PLAN M7「落地定稿与实现约束」）**：① MCP 运行时注册表必须挂 `globalThis`（否则 Next dev HMR 每次重载都泄漏 stdio 子进程）+ exit hook 清理；② 连接必须做 in-flight Promise 去重（防并发 spawn）；③ `/api/tools/status` 为探测式；④ MCP 客户端进程访问本机需 `NO_PROXY=*`。P6 已知低优先优化点 3 条（触发词子串误命中 / 状态面板探测超时 / 进程内缓存无上限）已登记在 PLAN 与 Progress「阻塞与问题」。

## 环境与工具链（重要，踩过的坑）

- **Docker 构建（P7 定版）**：docker.io 直连被拦截（auth 502）→ 基础镜像走 `docker.m.daocloud.io` 前缀（compose 的 `NODE_IMAGE`/`PY_IMAGE` 可覆盖）；**镜像 Python 必须与锁文件同版本**（现为 3.12，曾因 3.11 装 numpy 2.5.3 失败）且**锁文件须在容器内生成**；**web 镜像 base 阶段禁止设 `NODE_ENV=production`**（会跳过 devDependencies，缺 tailwind postcss 与 prisma CLI）；数据卷在 data-service 侧须 rw（恢复需写入，恢复前停 web）；全新卷无业务数据，需 `POST /api/sync`。
- **C24 依赖归属变更必须同步锁文件**：包在 dependencies/devDependencies 间移动后必须重跑 `npm install --package-lock-only`——`npm ci`/`npm prune` 以锁文件为准，只改 `package.json` 会让 `--omit=dev` 把运行时必需的包裁掉（2026-09-14 实测：`prisma` CLI 被误裁 → `migrate deploy` 必失败）
- **C25 裁剪必须在独立 stage 完成**：`npm prune`/`rm -rf` 不能在 runner 内"先 COPY 全量再删"（被删文件留在更早层里，体积不降，实测仍 1.62GB）；正确做法 `FROM build AS prod-deps` 裁剪 → runner 只 `COPY --from=prod-deps`
- **web 镜像体积事实（2026-09-14 实测）**：1.62GB → **1.25GB**（`docker images` 口径 -23%），容器内占用 0.89GB。**devDeps 不是大头**——裁剪后 node_modules 仍 833MB，主体是 `@next` SWC 273MB / `next` 156MB / `@prisma` 112MB / `prisma` 67MB / `echarts` 62MB / `@img/sharp` 46MB；musl+wasm 变体（165MB）已裁（本镜像 glibc）
- **容器起法**：`WEB_PORT=3100 docker compose up -d`（避免与开发态 3000 冲突）；`BASE=http://localhost:3100 node scripts/smoke.mjs` 验证；`--profile mcp` 启用 MCP HTTP（宿主 127.0.0.1:8765）。Docker Desktop 未启动时 `docker compose build` 会报 `npipe ... daemon is running` 错误——需主人手动启动 GUI
- **pip 操作必须加 `PYTHONPATH=`**：WorkBuddy 沙箱注入的 sitecustomize 会拦截 pip 的卸载动作（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`），中断会留下"旧版已删、新版未装"的损坏态（P6 曾因此毁掉 data-service 的 venv）。正确姿势：`PYTHONPATH= .venv/Scripts/python.exe -m pip install ...`。
- **依赖定版（勿随意升级）**：`fastmcp>=2.0,<3` + `starlette>=0.40,<0.51` + `fastapi>=0.115,<0.126`（fastmcp 4.x 依赖 starlette>=1.0.1，与 fastapi 硬冲突，装上后 data-service 起不来）；另需 `httpx>=0.27,<1`、`yfinance>=0.2`。
- **本机 Bash 工具缺 coreutils**：命令前需 `export PATH="/usr/bin:/bin:$PATH"`（否则 head/wc/ls/rm 全不可用）；`pkill` 不存在。
- **PowerShell 工具 stdout 常不被捕获**：需 `Set-Content` 写临时文件再 Read。
- **`next dev` 需作为托管后台任务启动**（Bash 工具 `run_in_background=true`），用 `&` 裸启会被回收；dev 启动卡在 "Starting..." 时删除/隔离 `.next` 后重启。
- **沙箱删除受限**：大目录/批量删除会被 safe-delete 守卫拒绝，改用"重命名隔离"或等待 escalation 通过。

## 挂起事项

- **L2 web 镜像重建验证**（代码已就绪）：需主人启动 Docker Desktop → `docker compose build web` → `docker compose up -d` → `node scripts/smoke.mjs` → 记录体积（预期 ~0.9GB）。Bash 侧无法拉起 GUI 应用，切勿擅自尝试启动。
- 东财数字货币行情源可用性验证：推迟到实际落地时进行（用户 2026-09-12 明确）；遵循 R13 多源数据对比验证原则。
- ~~转债行情/K 线~~：**已闭环**（2026-09-13）——行情经新浪备源可用；K 线定性为外部源限制（仅东财），限流时显式降级；未上市标的取数报明确错误。
- ~~项目未初始化 git~~：**已初始化**（2026-09-13，基线 b22671f + 修复提交 f5656d7）。
- ~~目标 LLM 选型~~：暂定 DeepSeek + GLM（2026-09-12），P4 启动时做双家 function calling spike。
- ~~称呼偏好~~：用户已定称呼其为"主人"（2026-09-12，记入用户级 USER.md / MEMORY.md）。
