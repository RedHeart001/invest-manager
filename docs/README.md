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
- **待拍板**：**10-09 15:0x 一批＝#56 收口**（**顶栏高亮定为「不」断开**「沿会话残留」＝10-01 的 (i) 在高亮这一侧原样保留、本轮零生产码改动；`db79bc5c` 已按他一句「现在 remove」删掉；**F 那一格诊断完成＝不是取数坏了**——「2026-10-08T16:00:01」是**美东时间的上一交易日收盘**，此刻美股休市所以那就是最新一笔，同一分钟同一条链路的 A 股对照组给的是 `2026-10-09T15:13:47`）**＋**新登记 #58**（那一屏缺「谁的钟／哪一交易日」的语义，推荐甲＝不改）｜**#52 ✅ 甲 已定档（10-09 13:1x）**＝零出网类继续排 `at`、**要主动打上游类（③ 主源档／④ 七枚／真刷新／真 pipeline）从此改人工**；17:15 那枚已按他的「算人工」改写成"到场不跑"（我没自行删，`remove` 归他一句字）；⚠️ **#56：甲（CR9-79）只关掉一半，主人第二轮手测又报回两形 ⇒ 已修＝CR9-82**（裸 URL 的返回目标不再继承会话残留＋`back()` 改由"本文档路由轨迹"发放），**新复测清单 A–H 等他点击结果**；**#55 甲＋乙 都已落地（CR9-78／CR9-81），丙 定为不做，那条 note 的屏上文案他已给字＝不改**；**#53 丙 已落笔**＝判读单位改「批」，现值＝**已到手 4 批／45 对里 4 对 ⇒ 门槛（≥3 批）已过**，16:45 那枚是第 5 批、当场可下结论；**#54 乙／#51 甲 均已落地**。178 只 us 码的新浪覆盖率＝**本轮他给字补测、已跑完：178/178 全供出、符号闸零拒绝**，其中 `DCM`（NYSE ADR「NTT DoCoMo」）的日线止于 2020-07-15＝上游给的真历史（那家已下市）⇒ 由此**新登记待拍板 #57**（要不要处理名单里的下市股，推荐＝本轮不处理）。逐条状态与案由只读 [FIX-LEDGER.md](FIX-LEDGER.md) 的状态卡与「待拍板」节，本文件不并列第二套
- **服务**：ds **1164**（10-09 **12:14:20** 起重，`SYNC_CATCHUP=off`＋`HTTPS_PROXY`，装的是含 CR9-81 的码＝`sina_provider.py` mtime 12:11:44 < StartTime，且 `/kline?type=us` 当场回 `source=sina`）／web **6108**（`npm run dev`）——**两侧都是 10-09 中午按主人的字新起的**（机器 11:34:14 重启后两端 0 监听）。**10-09 13:2x 的 CR9-82 全在 web 侧 ⇒ ds 不必重启**，装载证据换成"产物里有没有新符号"那一档（`canBackToOrigin` 已出现在 dev bundle 的 product 页与 layout 里）。**这两个 PID 是当日实况，下轮请现查**（`Get-NetTCPConnection -State Listen -LocalPort 8000,3000`）；若 0 监听，起 ds 带 `SYNC_CATCHUP=off` + `HTTPS_PROXY`（只这两个前缀，**不要手设 `NO_PROXY`**），并记住**起 ds 会自带一轮热点 pipeline**（10-09 12:14 那次实测 70.0s／5 topics／东财桶打到 cooldown 165.9s＝一次重启不免费）；**15:2x 复核＝两端 PID 未变（ds 1164／web 6108），本轮零生产码改动 ⇒ 装载状态与 13:2x 是同一棵树，① 重跑仍 348/42、② 沿用 808/808**

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
