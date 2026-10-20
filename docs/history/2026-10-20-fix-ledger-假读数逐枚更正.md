# 10-20 现查轮＝账上 10 处假读数的逐枚更正（正文档，活跃档只留指针）

> **为什么单开这一档**：FIX-LEDGER 全档现值 115,751／FILE 阈 120,000＝余 4,249，装不下这十枚的正文；按 `docs/README.md` 的三层结构，**过程明细与逐枚读数进 `history/`、活跃档只写指向**。
> **纪律**＝只增不改：下面每一枚的"旧句"在活跃档里**一字不回改**；唯一更正位＝FIX-LEDGER「当日轮明细 · 10-20」那一行指针＋本档。
> **触发**＝主人的字「结合现在项目完成情况，全面梳理一遍项目代码，然后看下这些点具体要怎么做？推荐下方案」＋批准那份计划；取证＝两枚只读 Explore（零出网、未跑测试、未动文件）。

| # | 旧句住在哪（内容锚，不用行号） | 账上那句（原样、不回改） | 盘上现值 | 复跑判据 |
|---|---|---|---|---|
| 1 | 未闭环看板 **CR9-26 行 ②** 那一格 | 「列表 48 页要 `clist/get`」 | 载体文件＝`data-service/app/providers/hk_provider.py:259-327`（**不在 `akshare_provider.py`**）；一次 `pz=10000`、页大小按返回条数反推、`pages>100` 才截；族＝**eastmoney**（`_em_json`→`_em_request`），`min_interval 5.0`／burst 2 ⇒ ≈48 次 acquire ⇒ **≥4 分钟** | `grep -n clist data-service/app/providers/hk_provider.py` |
| 2 | 门槛区／「本轮不做」里那句「打一次 `/sync/run`」 | 隐含"可按类补" | `POST /sync/run`（`main.py:392-405`）只有 `trigger`＋`force`、**无 `type=`** ⇒ 补就是全六类；只补一类走 BFF `POST :3000/api/sync?type=hk&force=1`（`web/app/api/sync/route.ts:26-38`） | `grep -n "def run_sync\|trigger\|force" data-service/app/main.py \| sed -n '390,410p'` |
| 3 | 「本轮不做」B1／乙 那两行 | 「两道夹都被 `test_cr9_59_us_list.py:236/:238` 钉着」 | 测试只钉 pages／ceiling（`:244/:246/:249/:252/:254`，其中 `:252` 判 `== akp.US_LIST_PAGE_CEILING`）；**`US_LIST_WHOLE_TIMEOUT_S=150.0`（`akshare_provider.py:221`）无任何断言** ⇒ 放宽它不需要改测试 | `grep -n "WHOLE_TIMEOUT\|CEILING" data-service/tests/test_cr9_59_us_list.py` |
| 4 | 「本轮不做」乙 那两行末句 | 「每夜 ≈216 次腾讯请求」 | 按码面＝**≈365 GET/夜**：18,241 ÷ `BATCH=100`（`web/lib/market-snapshot.ts:18`）＝183 次 `/quotes`，tencent 备源每次切 60（`tencent_provider.py:151-154`）＝2 GET。**甲+ 那档（505 只）＝12 GET 那句仍成立** | 读上面四个常量自己乘 |
| 5 | 待拍板 **第 81 项** 末行（✅ 10-17 20:0x 那块） | 「刀 4 走甲＝`chain.py:61`／`main.py:183` 那两处注释没碰」 | 已由 **CR9-117** 改（10-18 11:4x「先补全B3文案与修复注释」＝甲→改）⇒ 盘上现值＝新文案「10-18 更正：CR9-115 删掉双源核对按钮…」；「本轮不做」里 10-18 11:4x 那一行才是真面 | `sed -n '58,66p' data-service/app/providers/chain.py` |
| 6 | 「本轮不做」**B4** 那行 | 「要动＝三处同改（BFF／ds／闸2）」 | **闸2 不适用**＝`DS_CONTRACT` 只登记 ds 路径；真第三处＝`web/scripts/test-p2.mjs:423-433`（现断 400/403，加 token 变 401）。**另记账上没有的一枚**＝链式腿 `/api/market/refresh`（`sync_scheduler.py:322`）同样不带 token | `grep -n "checkRequestOrigin" web/app/api/sync/route.ts` |
| 7 | 待拍板 **19:2x 处置块** ＋ **#92** 那块 | 「转债那两列＝正股代码＋**债项评级**」 | 上游 `akshare.bond_zh_cov` 那列实名＝**`信用评级`**（`债项评级` 属另一枚 API）；三列（正股代码／转股溢价率／信用评级）真在源表，丢弃点＝`akshare_provider.py:1213-1216` 与 `:959-966`。改动面按码数＝**15 处**（ds 3＋闸2 2＋prisma 1＋migration 1＋`sync.ts` 5＋`browse.ts` 3）＝**加强**「定档＝不做」的证据，定档本身不动 | `.venv` 里那份 `bond_zh_cov.py` 的列名表 |
| 8 | 待拍板 **#81** 末两块 ＋ OPT-3 表行 | 「**四条 verdict 字面**」 | verdict 只有**三态**（`agree｜diverged｜no_second_source`，`web/lib/realtime.ts:16`、`app/realtime.py:395/:403`）；**`stale` 不是 verdict**＝客户端 `isStale`（`realtime.ts:135-139`，测试 `:135-138`）⇒ 「`stale` 不可按需制造」这句说过头了：任何一次 `/api/realtime` 失败即出（服务停／超时／断网） | `grep -n "isStale\|verdict" web/lib/realtime.ts data-service/app/realtime.py` |
| 9 | 「本轮不做」**C4** 那行 | 「出现即记录」 | **盘上读不到**＝`realtime.py` 不 import logging、不写盘（`:37-59`）；`limiter-state.json` 的 `realtime-obs seenTotal` 只数**逐源调用次数**、没有 verdict 维度；`cache.inflightMaxSeen`（`:483`）是进程态 ⇒ 要"出现即记录"必须新加 durable 计数＝碰 `realtime.py`＝闸2 构造面＝同场一次付费重采 ⇒ **推荐仍留观察项** | `grep -n "logging\|open(" data-service/app/realtime.py` |
| 10 | 状态卡 **armed 格**那句备份判据（前置 20 的「runs 1→2」） | 「`dbBackup.runs` 由 1→**2**」 | `runs` 是**进程态**、重启归零＝今晚已被证一次（18:24 那发本地补份写出 `dev-20261020-182432.db`，而 `/health` 读回 `runs=1`）⇒ **判据换形**＝看 `lastRun` 时刻＋`backups/` 里有没有当天新文件；`trigger` 恒写 `startup-catchup` 不能用来分"自然"还是"复查" | `curl -s :8000/health \| python -c "import json,sys;print(json.load(sys.stdin)['dbBackup'])"`；`ls -t backups/*.db \| head -2` |

## 另外两枚"不是更正、是新知识"

1. **起序＝额度开关**：`_catch_up_decide` 只在 ds 起后 **5 秒**问 web 一次、不重试（`app/hotspot/scheduler.py:239`→`:246-294`），且 `finally` 无条件把 `catchUpResolved` 置成今天（`:243`）⇒ **先 web 后 ds＝真补跑一发**（花额度）／**只起 ds＝走 `catch-up check failed` 那一支**（零出网、但当天热点从此无产出，之后起 web 也不再补）。
2. **进程内账与 durable 账在同一天也会短暂不一致**：18:25:59 那次 flush 落 `eastmoney denied 1`，而进程内已是 `denied 9`；下一次 flush 后才对齐 3/9 ⇒ 抄"哪本账"这条纪律仍要，但**别把短暂不等当成归因 bug**（A2 那条定档不批不变）。
