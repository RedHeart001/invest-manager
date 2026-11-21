# Invest Manager 文档导航

> 统一入口：30 秒知道项目是什么、去哪里找什么。逐项状态只在 [FIX-LEDGER.md](FIX-LEDGER.md) 维护。

## 项目是什么

个人投资理财辅助 Agent：热点推送 / 智能搜索 / 产品详情页 / 金融分析 Agent。

- **web/**：Next.js 15（App Router）+ React 19 + Prisma/SQLite；界面 + BFF，唯一对外端口和唯一写库方。
- **data-service/**：FastAPI 无业务状态取数服务，不写业务库；运行时状态与库快照在 `.gitignore` 内。Compose 网络内 `expose 8000`，不发布到宿主机；采集结果经 HTTP 回调 web 落库。
- **LLM**：OpenAI 兼容端点（DeepSeek/GLM）。
- **数据源**：akshare（东财/腾讯/新浪）、Tavily、yfinance 等，走多源降级。

## 当前短摘要

P0–P7 主功能已完成；round4 完整七套、真实 LLM 对话/工具链及 A 股、美股完整研报已通过。CR10-40 完整快照事务和 Web 不完整候选零写入防线已提交推送（`a80f1ea`），完整代码验收与独立副本契约 10/10 通过，但正式 DS 仍为 CR10-39、正式 Web 未装载 CR10-40。11-21 自然同步因 hk/us 失败为 `daily/partial_failed`，自然 E 未通过；11-21 自然备份/恢复也没有通过记录，启动补备不能替代。

下一步经明确授权后同时装载正式 CR10-40 DS/Web，不人工触发同步、不替换正式卷，再观察 11-22 自然同步、备份和独立恢复；当日为周日，无自然热点义务。等价备源验证、E 后真实 UI/行面补验及热点 SSE 日期混合静态风险分别留账，不混入装载结论。全部欠账见 [FIX-LEDGER.md](FIX-LEDGER.md)，执行分类见 [PROGRESS.md](PROGRESS.md)，隔离和授权边界见 [全新空卷初始化与分级验收方案](history/2026-11-15-全新空卷初始化与分级验收方案.md)。

## 文档地图

| 你要做什么 | 读哪个文件 | 说明 |
|---|---|---|
| 改需求/设计 | [PLAN.md](PLAN.md) | 需求与设计唯一来源 |
| 改代码 | [CONSTRAINTS.md](CONSTRAINTS.md) | 不得回退的约束、跨服务契约、数据源事实和部署约束 |
| 查功能状态与验收欠账 | [FIX-LEDGER.md](FIX-LEDGER.md) | 逐项状态、有效判据、验证门槛的唯一来源 |
| 查里程碑与真实阻塞 | [PROGRESS.md](PROGRESS.md) | P0–P7 与当前里程碑，不复制逐项状态 |
| 查当前轮发现 | [CODE-REVIEW.md](CODE-REVIEW.md) | 当前开放轮次完整发现与误报排除表 |
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
