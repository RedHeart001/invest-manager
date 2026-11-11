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

> **【已搬归档】** - **当前轮次**：**CR10**（CR9 已于 10- —— 正文见 [2026-11-08-readme-当前状态块1108下午轮归档.md](history/2026-11-08-readme-当前状态块1108下午轮归档.md)（体量治理：整块搬迁，原地只留指针）。

> **【已搬归档】** - **当前轮次**：**CR10**（CR9 已于 10- —— 正文见 [2026-11-12-readme-当前状态块1112轮归档.md](history/2026-11-12-readme-当前状态块1112轮归档.md)（体量治理：整块搬迁，原地只留指针）。

- **当前轮次**：**CR10**（CR9 已于 10-19 12:3x 收尾）｜**真未闭＝CR10-6**（腾讯备源日 K 窄窗口；判据＝等下次上游真陈旧时窄窗是否仍含当日）｜**本轮落码＝CR10-20／R20／美股乙**（11-12：三枚写入口守卫／股票 PE 分位·近似标注／美股全量 950 页上限＋早停按实盘）｜上一轮＝CR10-18／19｜**下一可用编号＝CR10-21**。出处＝11-12 01:5x 现查 [FIX-LEDGER.md](FIX-LEDGER.md) 状态卡与看板。
- **未闭环项与待拍板**：逐项状态只认 [FIX-LEDGER.md](FIX-LEDGER.md) 的「🔴 未闭环看板」与「⚠️ 待你拍板」两节；**待你拍板现在 0 枚**。
- **数据面（11-12 01:55–01:59 只读 SQL）**：`Product` **43590** 行＝stock 5927／fund 28287／hk 4743／bond 1066／crypto 249／**us 3318**，**六类齐全**；有价覆盖＝crypto 249/249、**us 3236/3318（97.5%）**、stock 5575/5927、fund 24333/28287、hk 3148/4743、bond 312/1066（stock/fund/hk/bond 的缺口＝名单含未上市/停牌/港币债券，账上已定档"不是 bug"；us 82 只无价＝退市/无报价长尾）。
- **服务**：web 3000＝node **PID 4200**（起 11-12 01:04:19）／ds 8000＝python **PID 27088**（起 01:26:53，为装载美股乙新码与 `US_LIST_PAGES=950` 重起）。判据按**名字＋StartTime**，不拄 PID。
- **最新一次门禁＝11-12 01:57 闸1 全绿**：`tsc` 0 error／vitest 603/603·63 文件／ds 离线 29 套 1135/1135／`NEW=0`／断链 0，回执 `gate1-13-1112-0157.out`（52s；闸2 L3 绿＝10 条 KNOWN_STALE 在册，重采归下个人工付费窗口）。
- **本轮三件事已落**：三枚写入口来源守卫补齐（13 枚写方法＝11 守卫＋2 在册 ingest）／股票 PE 分位上屏（近似口径如实标注：600519＝51% 近3年 726 根，亏损股两串皆无）／美股乙全量（us 179→3318；名单两趟 913＋919 页，第二趟 3 页上游失败⇒子集声明＝R16 设计，「已取全」干净读数等自然窗口）。
- **armed 自动化**：**0 枚**。**归主人人工的一格**＝屏上 `diverged`／`stale` 那一眼（不可按需制造）。
- **未推笔数与体量都现查**：`git rev-list --count origin/dev..HEAD` ／ `python scripts/docs-scan.py`。**push 要主人当轮给字；本轮拍板＝只 commit 不 push**。
- **本块＝重写块（11-02 起）**：旧块走 `--move` 逐字节进 [2026-11-12-readme-当前状态块1112轮归档.md](history/2026-11-12-readme-当前状态块1112轮归档.md)（9 行／1,500 字符／sha256 前缀 `a69a2082ed9d133d`）；**更新＝重写本块，不再往下加行**（依据＝`.claude/rules/project.md` 文末那节 docs 现值块与压缩）。

> **【已搬归档】** - **当前轮次**：CR9（开放）；CR8 已收尾 —— 正文见 [2026-11-02-readme-当前状态块归档-1102.md](history/2026-11-02-readme-当前状态块归档-1102.md)（体量治理：整块搬迁，原地只留指针）。

## 文档地图

| 你要做什么 | 读哪个文件 | 说明 |
|---|---|---|
| 改需求/设计 | [PLAN.md](PLAN.md) | 需求与设计**唯一来源**——要改行为先看这里是否已定稿 |
| 改代码 | [CONSTRAINTS.md](CONSTRAINTS.md) | **改代码前必自查**：C1–C36 不得回退的约束、跨服务契约坑、数据源事实（`C1–C34` 那句指"按来源审查轮次分五批"的那 34 条；C35／C36 是 CR10 的两枚新发现，各自独立成块） |
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
