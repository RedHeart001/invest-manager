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

**11-28 最新：** 02:00 自然同步六类名单均到货（fund 28,452／stock 5,931／bond 1,068／crypto 249／hk 4,754／us 3,343），美股任务 923/923、02:26:39 完成；03:30 备份 `daily/completed`（62,406,656 B），独立恢复 `invest-e-restore-1128` `passed=true`、迁移 12。**但同步总状态停在 `collecting`、watcher 未封口，五类行情 `partial_failed`（fund 2、hk 10 个空批次）⇒ 本轮未全过。** 根因是美股完成未回写同步总状态、读取侧也不收尾；CR10-51 修复代码已提交 `c9a516d`（幂等 `_finalize_collecting_from_us()`、三个收尾入口、保留五类结果与 `lastRefresh`、不生成补试），定向 23/23、全量门禁 42 套 1575/1575、隔离 30/30 通过，候选镜像 `cr1051-1128-accept` 已构建；**正式装载待 11-28 原 watcher 自然结束，尚未部署、未获自然轮证据**。W2/W3/W4 与 W1 显式代理仍未获自然证据。详见 [11-28 复核](history/2026-11-28-同步collecting终态收尾修复与自然轮复核.md)。

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
