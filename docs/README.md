# Invest Manager 文档导航

> 统一入口：30 秒知道项目是什么、去哪里找什么。逐项状态只在 [FIX-LEDGER.md](FIX-LEDGER.md) 维护。

## 项目是什么

个人投资理财辅助 Agent：热点推送 / 智能搜索 / 产品详情页 / 金融分析 Agent。

- **web/**：Next.js 15（App Router）+ React 19 + Prisma/SQLite；界面 + BFF，唯一对外端口和唯一写库方。
- **data-service/**：FastAPI 取数服务，**不写业务库**（业务库只有 web 写）；同步状态、美股任务、热点状态与刷新摘要等运行态落在 `.gitignore` 内的 `runtime/`。Compose 网络内 `expose 8000`，不发布到宿主机；采集结果经 HTTP 回调 web 落库。
- **LLM**：OpenAI 兼容端点（DeepSeek/GLM）。
- **数据源**：akshare（东财/腾讯/新浪）、Tavily、yfinance 等，走多源降级。

## 当前短摘要

**一句话**：P0–P7 主功能已完成，round4 完整七套与真实 LLM／研报已通过；11-25 起 E-调度闭环、E-数据转来源健康账。**当前唯一前向动作＝等用户指定目标自然日 `D`**，在 `D-1` 安全窗口装载 CR10-52（候选镜像 `cr1052-1128-cand` 未装载，正式 DS 仍 `cr1051-1128-accept`）。逐项状态见 [FIX-LEDGER.md](FIX-LEDGER.md)，不要在本文找。

**已闭的里程碑（只留指针）**：CR10-40／41／42／43／44／47／48／49／50／51 均已完成装载或验收；E3 唯一实例、收益率曲线行面、实时有数据窗口、fund 自然账本、CR10-41 跨日混行已于 11-25／11-27 逐项闭环。证据分散在 [11-25 自然窗口](history/2026-11-25-自然窗口全过与E-调度闭环.md)、[E3 与解绑验收](history/2026-11-25-E3唯一实例与解绑验收.md)、[CR10-49 装载任务书](history/2026-11-26-CR10-49装载与IPv6默认值收敛任务书.md)；11-22/11-23 原始失败与 11-24 无自然轮保留不改写。

**11-27／11-28 两个自然轮（均未全过）：** 11-27 同步 `partial_failed`（crypto/hk 失败、stock 走新浪降级、us `collecting`），16:30 热点以 `engine=llm`／`degraded=false`／5-5 恢复，W5 由该轮取得自然证据；W1～W4 代码 `d5effa0` 于 23:38 成套装载到 `w1w4-1127-accept`（隔离 30/30、冒烟 8/8、硬判据 8/8），**装载只证明可运行**。11-28 六类名单全到货、美股 923/923、备份与独立恢复通过，但总状态停在 `collecting`、五类行情 `partial_failed`（fund 2／hk 10 空批次）；CR10-51 装载 `cr1051-1128-accept` 后 11:47 启动恢复只完成**派生收尾**，`lastRefresh` 仍为 `partial_failed`、缺口不被掩盖。**⇒ W2／W3／W4 的失败分支、W1 显式代理、CR10-51 自然收尾与 CR10-52 重启恢复全部仍欠自然轮证据**；11-29 记“未发生自然窗口”，不判失败、不补跑。详见 [11-28 复核](history/2026-11-28-同步collecting终态收尾修复与自然轮复核.md)。

**11-28 离线／隔离推进（不计入自然轮）：** watcher 测试 17→38（`a5953bb`）、CR10-52 刷新摘要按 `runId` 分槽落盘 22/22、只读护栏 `test-script/deploy_guard.py` 76/76（`9c4017f`）。docs 扫描器补上一处覆盖盲区（`docs/history/README.md` 自身的链接此前不在任何尺里，`--selftest` 41→46 判据）。最终门禁 `gate1-108-1128-1507.out` 六步全绿，**但抬头是 `bb47552 + dirtyPaths=696`，只能读作“最终代码内容的门禁读数”，不是对干净 `9c4017f` 树的回执**。

**装载安排（未执行，目标日待定）：** CR10-52 改为**目标自然日 `D` 前一安全窗口装载**，让下一次自然轮直接验最终代码；`D` 当天与 02:00～03:30 禁止切换。**`D` 由用户主动提出，助手不推定、不催办**；未指定前不做前置检查、不动容器。见 [装载与前窗口切换任务书](history/2026-11-28-CR10-52装载与前窗口切换任务书.md)。

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

- **起 DS**：`cd data-service && SYNC_CATCHUP=off PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。解释器须为 `.venv/Scripts/python.exe`；dev 不加 `--reload`；**不要手设** `NO_PROXY`（海外源出网由 `app/utils/http.py` 按源族决定，当前代理值为空）。`SYNC_CATCHUP=off` 只关启动补跑，不影响每天 02:00 的 cron；起 DS 前仍须按任务书检查热点日键、同步状态和备份新鲜度，避免未授权外部任务。**启动顺序是先 web 后 ds**：ds 起来约 5s 后会 `GET` web 的 `/api/hotspots/ingest`，web 不在时当天热点补跑直接跳过且不重试。
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
