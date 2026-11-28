# Invest Manager 文档导航

> 统一入口：30 秒知道项目是什么、去哪里找什么。逐项状态只在 [FIX-LEDGER.md](FIX-LEDGER.md) 维护。

## 项目是什么

个人投资理财辅助 Agent：热点推送 / 智能搜索 / 产品详情页 / 金融分析 Agent。

- **web/**：Next.js 15（App Router）+ React 19 + Prisma/SQLite；界面 + BFF，唯一对外端口和唯一写库方。
- **data-service/**：FastAPI 无业务状态取数服务，不写业务库；运行时状态与库快照在 `.gitignore` 内。Compose 网络内 `expose 8000`，不发布到宿主机；采集结果经 HTTP 回调 web 落库。
- **LLM**：OpenAI 兼容端点（DeepSeek/GLM）。
- **数据源**：akshare（东财/腾讯/新浪）、Tavily、yfinance 等，走多源降级。

## 当前短摘要

P0–P7 主功能已完成；round4 完整七套、真实 LLM 对话/工具链及 A 股、美股完整研报已通过。CR10-40 DS/Web、CR10-41 Web、CR10-42 DS、CR10-43 DS/Web 与 CR10-44 DS/Web 已正式装载，复用原正式卷，未人工触发同步。CR10-42 修复 us 真实空名导致的整批映射失败，并接入 HKEX 官方完整备源；CR10-43 拒绝 us 名称 `true` 并补齐刷新进度 owner 归属；CR10-44 把无备源的 fund 名单移出东财熔断连坐并前置同步顺序。

**11-25 自然窗口四项全过：02:00 同步 `daily/completed`（六类全到货，stock/hk/us 走设计内备源）、03:30 备份 `completed`（55,463,936 B）、独立恢复 `invest-e-restore-1125` `passed=true`（Product 43,246、迁移 12）、08:30 盘前热点 `completed`（keyword 降级、2 源）。E-调度已闭；E-数据按 CR10-46 转来源健康账；E3 与解绑项推进中。** 11-22/11-23 原始失败与 11-24 无自然轮保留不改写；网络加固 11-24 16:40 落地。CR10-44 回归测试已补交 `5dc5dde`；CR10-45 副本机取证另账，原始回执本机未独立复核，不进入正式 E。状态见 [FIX-LEDGER.md](FIX-LEDGER.md)，方案见 [CR10-46 双轨验收](history/2026-11-24-CR10-46-双轨验收与带缺口推进方案.md)，11-25 读数见 [11-25 自然窗口](history/2026-11-25-自然窗口全过与E-调度闭环.md)，11-23 归因见 [CR10-44 方案](history/2026-11-23-CR10-44-同族熔断连坐与无备源腿.md)，副本取证见 [CR10-45 报告](history/2026-11-24-本机dev副本实例与首日取证.md)。

**11-27：** 自然 02:00 同步 `partial_failed`（crypto/hk 失败、stock 走新浪降级 5,580 行、us `collecting`），03:30 备份通过，16:30 热点 `post-market` 以 `engine=llm`／`degraded=false`／三源齐到／5-5 **恢复**（W5 配置由此取得自然轮证据）。分类出的 W1～W4（按源族出网、A 股 fail-closed、有界补试、四态展示）代码提交 `d5effa0`、门禁 `gate1-93-1127-1831.out` 全绿后，**已于 11-27 23:38 成套装载到新标签 `w1w4-1127-accept`**（DS `740c16a5981a`／Web `8a8e397ef8a0`，复用正式卷，回退镜像 `cr1049-accept` 保留）：隔离 Compose 验收 30/30、正式冒烟 8/8、装载后硬判据 8/8，未人工触发同步或热点。**装载只证明新码可运行，不等于已验证**——W2 的 A 股 fail-closed、W3 的有界补试、W4 的失败态展示都需 11-28 自然轮真的出现对应失败才算取证；W1 的海外显式代理路径本轮未改配置（代理仍为空），同样未获实测。执行记录见 [装载任务书](history/2026-11-27-W1-W4装载任务书.md)，代码落地读法见 [W1～W4 实施记录](history/2026-11-27-W1-W4实施记录-按源族出网与失败透明.md)。另：19:0x 只读复核确认**凌晨只有 02:00 同步与 03:30 备份两条腿、且都每天跑**，`compose` 未透传四个调度变量；并发现**周末启动补跑不看星期**（11-21／11-22 各真跑过一轮），「周末不排热点」只对 cron 成立——两项均未改，见 [调度时刻可调性评估](history/2026-11-27-当前状态复核与调度时刻可调性评估.md)。

**11-28 最新：** 02:00 自然同步六类名单均到货（fund 28,452／stock 5,931／bond 1,068／crypto 249／hk 4,754／us 3,343），美股任务 923/923、02:26:39 完成；03:30 备份与独立恢复通过。**原同步总状态停在 `collecting`，watcher 于 11:38:57 按原逻辑到 deadline；五类行情 `partial_failed`（fund 2、hk 10 空批次）⇒ 本轮未全过。** CR10-51 已提交 `c9a516d`、`f88ebb3`，定向 26/26、门禁 42 套 1578/1578、隔离 30/30、冒烟 8/8；正式 DS 已装载 `cr1051-1128-accept`（`41651e9cd259`），Web 未重建。11:47 启动恢复对既有结果完成**派生收尾**，不是新自然轮证据；总状态现显示 `completed`，但 `lastRefresh` 仍从 Web 持久化结果恢复为 `partial_failed`，fund/hk 缺口不被掩盖。**下一次真实自然窗口仍待验证**；**11-29 因夜间机器不运行记为“未发生自然窗口”，不判失败、不人工补跑**；W2/W3/W4 与 W1 显式代理未获自然证据。详见 [11-28 复核](history/2026-11-28-同步collecting终态收尾修复与自然轮复核.md)。

**11-28 P2（离线验收，已提交未装载）：** 机器不可用期间按计划推进两项，均只产出离线／隔离证据，不计入自然轮。① watcher 离线测试 `test_cr10_38_natural_watch.py` 17→38 项，补上 `collecting` 不终态、`completed` 才封存、名单终态先到只补 `lastRefresh`、上一轮刷新不冒充本轮、watcher 从未运行仍可凭持久化读数判读——§10.4「事后取证」不再是只写在文档里的话。② **CR10-52**：刷新腿结果自己落盘（`runtime/sync-refresh-state.json`，按 `runId` 分槽保留 4 轮，自然轮与 W3 补试轮互不覆盖），`_recover_last_refresh()` 先读摘要、读不到才回落 Web 进度，新增 `lastRefreshSource=disk/web-progress/null` —— 消除了 `/sync/status` 对 Web `/api/health` 的隐性依赖。新增套件 22/22；总闸 `gate1-105-1128-1339.out` 全绿（tsc 0、Vitest 747/747、DS 43 套 1616/1616、docs 全过）、隔离 30/30、候选容器内 `status()` 零网络。提交 `a5953bb`。**候选镜像 `cr1052-1128-cand` 未装载，正式实例仍 `cr1051-1128-accept`；真实重启读数仍未取得。** 读数见同文件 §12。

**11-28 装载安排变更（未执行，目标日待定）：** CR10-52 的“P0 前不正式装载”改为**目标自然日 `D` 前一安全窗口装载**，让下一次自然轮直接验最终代码；`D` 当天与 02:00～03:30 禁止切换（DS 启动会同时恢复同步、美股、W3、热点、备份五条腿，当天切换会把部署混进被测窗口）。**`D` 由用户自行评估后主动提出，助手不推定、不催办**；未指定前不做前置检查、不动容器。前置十条不齐即顺延，`D-1` 的 22:00 未过则顺延到下一窗口，授权晚于完整前置窗口即本轮不装、不追赶。装载后 CR10-51 自然收尾与 CR10-52 重启恢复**分开记**；装载只证明可运行，`collecting → completed` 仍只能由自然轮回答。步骤与受理规则见 [CR10-52 装载与前窗口切换任务书](history/2026-11-28-CR10-52装载与前窗口切换任务书.md)。

## 文档地图

| 你要做什么 | 读哪个文件 | 说明 |
|---|---|---|
| 改需求/设计 | [PLAN.md](PLAN.md) | 需求与设计唯一来源 |
| 改代码 | [CONSTRAINTS.md](CONSTRAINTS.md) | 不得回退的约束、跨服务契约、数据源事实和部署约束 |
| 查功能状态与验收欠账 | [FIX-LEDGER.md](FIX-LEDGER.md) | 逐项状态、有效判据、验证门槛的唯一来源 |
| 查里程碑与真实阻塞 | [PROGRESS.md](PROGRESS.md) | P0–P7 与当前里程碑，不复制逐项状态 |
| 查审查发现 | [CODE-REVIEW.md](CODE-REVIEW.md) | 各轮发现原文与误报排除表；近期发现另见 history，现值状态只认 FIX-LEDGER |
| 回顾重要事件 | [history/](history/) | 根因、决策、验收、自然窗口与事故报告；[索引](history/README.md) |
| 评估候选优化 | [BACKLOG-PLAN.md](BACKLOG-PLAN.md) | 候选项的可行性、落地方案与代价，不是当前状态账本 |
| 查旧收尾计划 | [END_PLAN.md](END_PLAN.md) | 2026-10-23 历史快照，不是现值；其中行号和计数不采信 |

## 常用命令

- **起 DS**：`cd data-service && PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。解释器须为 `.venv/Scripts/python.exe`；dev 不加 `--reload`。启动前按任务书检查补跑开关、热点日键、同步状态和备份新鲜度，避免未授权外部任务。
- **起 Web**：`cd web && npm run dev`。
- **离线门禁**：`node scripts/gate.mjs --offline`。
- **Web 测试**：`cd web && npx tsc --noEmit && npx vitest run`。
- **完整集成**：`node web/scripts/verify-all.mjs`。会写库并可能触发真实行情、热点、研报或 LLM，只能按授权在隔离实例运行，不得直接对开发实例执行。
- **健康检查**：`curl :8000/health`、`curl :3000/api/health`。
- **docs 检查**：`python scripts/docs-scan.py`、`python scripts/docs-scan.py --selftest`。

各套件边界与验收条件见 [FIX-LEDGER.md](FIX-LEDGER.md)「验证门槛（权威现值）」。

## 文档维护约定

- 状态只在 [FIX-LEDGER.md](FIX-LEDGER.md) 更新；本文件只留导航与短摘要。
- 普通旧状态由 Git 保存，不再为每次现值重写生成机械归档和指针。
- [history/](history/) 只保留有长期价值的根因、决策、验收、自然窗口、事故报告与前向任务书；重要报告不做摘要重写。
