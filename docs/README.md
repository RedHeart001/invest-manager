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
- **待拍板**：**17:4x 一批已定档并落地＝#57（甲+乙，CR9-85 把日线末点上屏）、#58（甲＋他要的语义标注，CR9-84＝那一格点名是哪个钟＋跨钟补北京时刻）、#59（我原来的甲被他否掉，改成「这一类」的处置＝CR9-83：全站 30 处 key 审计＋AST 自动闸 R1／R2／R3）**；**17:4x 新登记 #60**＝`/product/us/DCM` 那一屏的空态话「试过的数据源都没给这个品种的日线」对这一只是不准的（新浪有它到 2020-07-15 的日线，只是全落在默认 90 天窗口外），推荐乙＋前置＝先把那串 note 原文实测到手（可与今晚 21:30 后那一发同一次做）。**下一枚待拍板＝#61，下一个可用 CR＝CR9-86。**｜（下面 15:5x 那句原样留着，当「当时怎么数的」）**15:5x 追加＝新登记 #59**（详情页两个兄弟节点共用同一个 `key`＝他截图里那个红色「1 Issue」徽章；推荐甲＝两处各加前缀，一行两处）
- **服务**：ds **1164**（10-09 **12:14:20** 起重，`SYNC_CATCHUP=off`＋`HTTPS_PROXY`，装的是含 CR9-81 的码＝`sina_provider.py` 那条 us 日 K 腿）／web **6108**（`npm run dev`），17:2x–17:3x 复核＝**两个 PID 都没变、没重启任何服务**（本轮 ds 侧一个文件都没碰）。装载证据这一轮换了工具＝**活 DOM 直接读出新字面**（`/product/us/CEG` 上「来源：tencent · 美东 2026-10-08 16:00:01（北京 2026-10-09 04:00:01）」与「日线数据（最近 15 条，画到 2026-10-08 / 来源：sina / 币种：USD）」），同时 dev console 里 duplicate-key 那条已经没有了；门禁① 现值＝**363/44**（＋15 枚／＋2 文件＝守卫与 market-clock），② 808/808 沿用，③④ 未跑（要打上游那类＝按 #52 甲 走人工）。

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
