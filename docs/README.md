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

> **【已搬归档】** - **当前轮次**：**CR10**（CR9 已于 10- —— 正文见 [2026-11-08-readme-当前状态块归档-1108.md](history/2026-11-08-readme-当前状态块归档-1108.md)（体量治理：整块搬迁，原地只留指针）。

- **当前轮次**：**CR10**（CR9 已于 10-19 12:3x 收尾）｜**真未闭＝CR10-6**（腾讯备源日 K 窄窗口；11-01 19:2x 实机＝`inconclusive`；真闭判据＝等下次上游真陈旧时窄窗是否仍含当日）｜**本轮落码＝CR10-15／16／17**（11-08 凌晨：crypto 同 symbol 撞唯一键致整类 0 行／现场腿 `/products` 探测预算 180s 结构性不足／`test-p5.mjs` 冷启动必红）｜上一轮＝**CR10-14**（undici `headersTimeout` 默认 300s 压过 600s 预算）｜**下一可用编号＝CR10-18**。出处＝11-08 02:0x 现查 [FIX-LEDGER.md](FIX-LEDGER.md) 状态卡与看板节。
- **未闭环项与待拍板**：逐项状态只认 [FIX-LEDGER.md](FIX-LEDGER.md) 的「🔴 未闭环看板」与「⚠️ 待你拍板」两节（本块不复述条目）；**待你拍板现在 0 枚**＝`#95` 的乙（"同一 `(type,code)` 留哪一条"）11-08 已由主人拍定并落码＝CR10-15（留首次出现＝市值靠前）。
- **数据面（11-08 01:2x 现查）**：`Product` **40451** 行＝stock 5927／fund 28287／hk 4743／bond 1066／**crypto 249**／us 179，**六类齐全**。⚠️ 11-07 那句「crypto 整类 0 行且是环境限制」**作废**：真因是 CoinGecko 名单里同 `symbol` 两枚币撞 `Product` 唯一键（CR10-15），代理只是第一层。
- **服务**：web 3000＝node／ds 8000＝python，**11-08 01:1x 重起过 ds 两次**（装载 `.env` 代理、再装载 CR10-15 代码；监听 PID 17144 → 26072 → 32140）。**判据按名字＋StartTime，不拄 PID**。**起两棵本身不买额度**（CR9-95／CR9-94 的盘上日键把补跑挡在问 web 之前）。
- **最新一次全量测试＝11-08 01:25–01:47，全绿**：闸1（`tsc` 0 error／vitest 566/566·61 文件／ds 离线 29 套 1113/1113／`NEW=0`／断链 0，回执 `gate1-9-1108-0125.out`）＋付费实网三道（p0 15/15／p1 14/14／p6_mcp 7/7）＋七套集成（合计 213 条断言、`ALL DONE`）。逐枚字面住在 [FIX-LEDGER.md](FIX-LEDGER.md) 看板节＋[PROGRESS.md](PROGRESS.md) 的状态总览。
- **armed 自动化**：**0 枚**（11-03 07:30 那枚只读验收件已准点跑完并自删）。**归主人人工的一格**＝屏上 `diverged`／`stale` 那一眼（不可按需制造）。
- **未推笔数与体量都现查**：`git rev-list --count origin/dev..HEAD` ／ `python scripts/docs-scan.py`（报警·断链·表格三读数）。**push 要主人当轮给字；本轮给了**（原话「最后commit和push」）。
- **本块＝重写块（11-02 起）**：旧块走 `--move` 逐字节进 [2026-11-08-readme-当前状态块归档-1108.md](history/2026-11-08-readme-当前状态块归档-1108.md)（11 行／3,514 字符／sha256 前缀 `1725346efe5b93e3`）；**更新＝重写本块，不再往下加行**（依据＝`.claude/rules/project.md` 文末那节 docs 现值块与压缩）。

> **【已搬归档】** - **当前轮次**：CR9（开放）；CR8 已收尾 —— 正文见 [2026-11-02-readme-当前状态块归档-1102.md](history/2026-11-02-readme-当前状态块归档-1102.md)（体量治理：整块搬迁，原地只留指针）。

## 文档地图

| 你要做什么 | 读哪个文件 | 说明 |
|---|---|---|
| 改需求/设计 | [PLAN.md](PLAN.md) | 需求与设计**唯一来源**——要改行为先看这里是否已定稿 |
| 改代码 | [CONSTRAINTS.md](CONSTRAINTS.md) | **改代码前必自查**：C1–C34 不得回退的约束、跨服务契约坑、数据源事实 |
| 查某功能修了没 | [FIX-LEDGER.md](FIX-LEDGER.md) | 每项修了没、怎么验的；**未闭环看板置顶** |
| 查某轮发现了什么 | [CODE-REVIEW.md](CODE-REVIEW.md) | **当前开放轮次**的完整发现（轮次号与取号权威＝FIX-LEDGER 状态卡，此处不复述）＋「附录 · 已核验排除的误报」；**CR9 及更早轮次的发现原文已于 11-03 整节搬进 [history/](history/)**，本文件里只剩带标签的指针行 |
| 回顾执行过程 | [history/](history/) | 按主题归档被压缩的过程材料，[history/README.md](history/README.md) 有索引 |
| 评估「想做但还没做」的项 | [BACKLOG-PLAN.md](BACKLOG-PLAN.md) | 8 项待办的**可行性＋落地方案＋代价**；不是需求、不是账本，只答"能不能做、怎么落不出事" |
| 收尾清单（历史快照） | [END_PLAN.md](END_PLAN.md) | 2026-10-23 那轮的收尾计划快照，**已过期、不是现值**——里面的体量数／行号锚／编号一律不采信（11-03 现查实证：它 `:60/:61` 两行指路的 `CODE-REVIEW.md:9` 与 `README.md:29` 两处早已不在那些位置）。现状只看 [FIX-LEDGER.md](FIX-LEDGER.md) 与上表的 BACKLOG-PLAN；距今天数请现查，不在本格钉数字 |

> **【已搬归档】** > **位置更正（10-30，只增这一行；上面表格原句不回改 —— 正文见 [2026-11-02-readme-当前状态块归档-1102.md](history/2026-11-02-readme-当前状态块归档-1102.md)（体量治理：整块搬迁，原地只留指针）。

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
