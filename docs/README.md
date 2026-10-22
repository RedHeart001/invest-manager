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
- **⚠️ 现值更正（10-22 14:5x，只增这一行，上面那句原样不回改）**＝**CR9 已收尾（10-19 12:3x）**，当前开放的是 **CR10**：当天已取 CR10-1…CR10-5，下一枚 **CR10-6**；逐项计数与状态只认 [FIX-LEDGER.md](FIX-LEDGER.md) 状态卡。
- **未闭环项**：CR9-26（hk 列表，上游态）、G7（token 已配置且双侧生效，欠的是"上云前补完整身份鉴权"）、C31（Docker 验证，暂缓）。**CR9-3 已于 10-16 16:0x 实网验收结案翻 ✅**｜**10-19 13:4x 现值**＝按状态列读**真未闭只有两行**＝CR9-26②／C31（CR9-3 那句已翻 ✅；**G7 按主人的字保留不动、不再当未闭项计**＝更正位见 FIX-LEDGER「本表口径」下那行现值更正）
- **服务现值（10-22 20:5x 起本行即现值，不再是"当时读数＋更正"两层）**＝web 3000 **PID 11440**（`npm run dev`）／ds 8000 **PID 13160**（`SYNC_CATCHUP=off`＋`PYTHONPATH=.`、**不带** `--reload`、不手设 `NO_PROXY`），两棵都是 **10-22 18:19** 起的。**门禁现值**＝`tsc` 0｜① vitest **458/458·49 文件**｜② ds 离线 **27 套 1064/1064**｜③ p0 15/15＋p1 14/14（主源档）｜④ 七套 `ALL DONE`·断言 197·缺口 0。计数一律现跑 `python scripts/docs-scan.py` 与 `node scripts/gate.mjs`。
- **⚠️ 10-22 20:5x 一处旧读数已搬走（只增这一行说明去处）**＝本节原有「**服务**：ds 1164／web 6108…门禁① 363/44、② 808/808」那一行（10-09 的当时读数、且是全节唯一没带「当时读数」标记的历史行）已随本轮体量治理整块搬进 [history/2026-10-22-readme-history-1016-1022.md](history/2026-10-22-readme-history-1016-1022.md) ⇒ **要查那一版读数去归档件，别在本节找**；现值以上一行（服务现值）为准。

## 文档地图

| 你要做什么 | 读哪个文件 | 说明 |
|---|---|---|
| 改需求/设计 | [PLAN.md](PLAN.md) | 需求与设计**唯一来源**——要改行为先看这里是否已定稿 |
| 改代码 | [CONSTRAINTS.md](CONSTRAINTS.md) | **改代码前必自查**：C1–C34 不得回退的约束、跨服务契约坑、数据源事实 |
| 查某功能修了没 | [FIX-LEDGER.md](FIX-LEDGER.md) | 每项修了没、怎么验的；**未闭环看板置顶** |
| 查某轮发现了什么 | [CODE-REVIEW.md](CODE-REVIEW.md) | 当前轮 CR9 的完整发现；历史轮次在 [history/](history/) |
| 回顾执行过程 | [history/](history/) | 按主题归档被压缩的过程材料，[history/README.md](history/README.md) 有索引 |

## 常用命令

- **起服务**：ds＝`cd data-service && SYNC_CATCHUP=off HTTPS_PROXY=http://127.0.0.1:7897 PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`（**解释器必须是 `.venv/Scripts/python.exe`**——全局 `python` 没有 `apscheduler`，照它起必崩，见 [FIX-LEDGER.md](FIX-LEDGER.md) 待拍板 #73；**不带 `--reload`**、不手设 `NO_PROXY`）／web＝`cd web && npm run dev`
- **位置更正（10-18 18:3x，只增一行）**＝本配方此前被三处散文指路写成 `README:74`（本文件 :33/:35/:37 那三行，随追加而漂行）⇒ **一律以上面这一行为准**；断链闸看不见这类指路（rules :140 只认 `追加N`／`第 N 项`／链接三形），所以只能在这里点名。
- **启动期旋钮的归属（10-18 19:2x 新增，只增一行）**＝`HTTPS_PROXY` 这类变量**优先由 `data-service/.env` 供**（`config.py` 的 `load_env()` 用 `setdefault`＝进程环境仍优先于该文件），上面配方里的内联 `SYNC_CATCHUP=off HTTPS_PROXY=…` 从此只用于临时探针与"这一棵到底带了什么"的对账。理由＝依赖它的三处只看 `os.environ`（`crypto_provider.py:38`／`openbb_provider.py:45`／`hotspot/pipeline.py:74`），不经配方起的那一棵（手动 uvicorn／换机／compose）此前会静默走"没有代理"分支＝海外源腿不掉消息地缺席。
- **跑测试**：web `npx tsc --noEmit && npx vitest run`；ds 离线套件逐套 `exit=0`；集成 `node web/scripts/verify-all.mjs`。**点名的套件清单与各项现值只读 [FIX-LEDGER.md](FIX-LEDGER.md)「验证门槛（权威现值）」**——本文件不复述计数（计数会随重组漂移）
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
