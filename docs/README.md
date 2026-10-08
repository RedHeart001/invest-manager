# Invest Manager 文档导航

> **这份文件是给主人和 AI 工具的统一入口**——30 秒知道项目是什么、当前状态、去哪里找什么。
> 其他文件都是"按需查阅"，不需要通读。

## 项目是什么

个人投资理财辅助 Agent。四条原始需求：热点推送 / 智能搜索 / 产品详情页 / 金融分析 Agent。
- **web/**：Next.js 15（App Router）+ React 19 + Prisma/SQLite —— 界面 + BFF，**唯一对外端口**，也是**唯一写库方**
- **data-service/**：FastAPI **无业务状态的取数服务**（**不写业务库**——写库方只有 web；它会写自己的运行时状态文件与库快照，都在 `.gitignore` 内，口径见 [PLAN.md](PLAN.md)「为什么 data-service 不需要数据库配置」；compose 网络内 `expose 8000` 不发布到宿主机，采集结果经 HTTP 回调 web 落库）
- **LLM**：OpenAI 兼容端点（DeepSeek/GLM）
- **数据源**：akshare（东财/腾讯/新浪）、Tavily、yfinance 等免费源，全部走多源降级

## 当前状态（随 FIX-LEDGER 同步）

- **当前轮次**：CR9（开放）；CR8 已收尾
- **未闭环项**：CR9-3（BK 成分等价性，只欠实网验收）、CR9-26（hk 列表，上游态）、G7（token 已配置且双侧生效，欠的是"上云前补完整身份鉴权"）、C31（Docker 验证，暂缓）
- **待拍板**：**#51 定档＝甲（打住，零代码零新立项）**；**#55 甲 已落地＝CR9-78**（K 线空态上屏一行诚实成因），其 乙／丙 仍待字；**#56 评估完成＝「先乙后甲」成立、两刀塌缩成同一处改动**，等「写」字；**#52 乙 的规则升格、#54 乙 的「写」字、④ 其余三档跑不跑、刀 5 主源档跑不跑**仍各等他一句字。逐条状态与案由只读 [FIX-LEDGER.md](FIX-LEDGER.md) 的状态卡与「待拍板」节，本文件不并列第二套
- **服务**：ds **26396**（10-08 21:15:08 起重，带 `HTTPS_PROXY`）／web **18492**——23:0x 现查两枚都在监听；**CR9-78 是 web 侧改动，dev HMR 已装载并浏览器实测 ⇒ 没重启过任何一侧**。**这两个 PID 是当日实况，下轮请现查**（`Get-NetTCPConnection -State Listen -LocalPort 8000,3000 | Select -ExpandProperty OwningProcess`）；若 0 监听，起 ds 带 `SYNC_CATCHUP=off` + `HTTPS_PROXY`（只这两个前缀，**不要手设 `NO_PROXY`**）

## 文档地图

| 你要做什么 | 读哪个文件 | 说明 |
|---|---|---|
| 改需求/设计 | [PLAN.md](PLAN.md) | 需求与设计**唯一来源**——要改行为先看这里是否已定稿 |
| 改代码 | [CONSTRAINTS.md](CONSTRAINTS.md) | **改代码前必自查**：C1–C34 不得回退的约束、跨服务契约坑、数据源事实 |
| 查某功能修了没 | [FIX-LEDGER.md](FIX-LEDGER.md) | 每项修了没、怎么验的；**未闭环看板置顶** |
| 查某轮发现了什么 | [CODE-REVIEW.md](CODE-REVIEW.md) | 当前轮 CR9 的完整发现；历史轮次在 [history/](history/) |
| 回顾执行过程 | [history/](history/) | 按主题归档被压缩的过程材料，[history/README.md](history/README.md) 有索引 |

## 常用命令

- **起服务**：ds 带 `SYNC_CATCHUP=off` + `HTTPS_PROXY`；web `npm run dev`
- **跑测试**：web `npx tsc --noEmit && npx vitest run`；ds 离线套件逐套 `exit=0`；集成 `node web/scripts/verify-all.mjs`。**点名的套件清单与各项现值只读 [FIX-LEDGER.md](FIX-LEDGER.md)「验证门槛」**——本文件不复述计数（计数会随重组漂移）
- **查状态**：`curl :8000/health`（ds）、`curl :3000/api/health`（web）

## 文档维护约定

- **"当前状态"节**：随 [FIX-LEDGER.md](FIX-LEDGER.md) 的未闭环看板与待拍板区同步更新（每次轮次推进、未闭环项增减、待拍板变化时）
- **其他节**：基本不变（项目结构、文档地图、常用命令稳定）
- **历史归档**：被压缩的过程材料一律进 [history/](history/)，并在 [history/README.md](history/README.md) 加索引行

## 历史在哪

[history/](history/) 按主题归档被压缩的过程材料：
- 执行明细（如 `2026-09-18-cr6-批次ABCD执行明细.md`）
- 已闭环轮次发现（如 `2026-10-08-code-review-已闭环轮次归档.md`）
- 早期日志（如 `2026-10-08-progress-进度日志归档.md`）
- 一次性操作记录（如 `2026-09-19-ops-港股排障记录.md`）

检索方式：按文件名（日期 + 主题）或 [history/README.md](history/README.md) 的索引表。
