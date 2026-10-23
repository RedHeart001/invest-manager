# END_PLAN · 收尾盘点与执行方案

> **快照说明**：本文件是 **2026-10-23** 的一次性收尾盘点，不是权威账本。逐项状态与计数一律以
> [FIX-LEDGER.md](FIX-LEDGER.md) 的状态卡＋未闭环看板为准；本轮**未启动服务、未改生产代码、未跑门禁**。
> 目的：把「预定计划里还没做的项」一次列清，并给出逐项执行方案，供后续窗口直接照做。

## 0. 结论

- **服务现状**（2026-10-23 10:35 现查）：web 3000 / ds 8000 **均未运行**（`netstat` 无监听，`curl` 000）。
  启动前提齐全：`.venv`、`web/node_modules`、根/`web`/`data-service` 三处 `.env`、`docker-compose.yml` 都在。
- **项目已进入收尾验收态**，不是「还有一批功能没写」：全仓生产代码没有 TODO/FIXME/未实现标记；
  四条原始需求（热点推送 / 智能搜索 / 产品详情页 / 金融分析 Agent）都有已定稿需求段与阶段验收。
- **真正没做完的**：真未闭 **2 项**（hk 上游态、Docker 暂缓）；代码已完成、等现场读数 **2 项**；
  处置需要一句话 **3 项**；文档残留 **5 处**；其余全是已定档/明确不做/需数据源。
- **CR10-6 只是下一个编号占位**，全仓没有它的计划正文；不存在「CR10-6 没做」。
- **今天 02:00 同步腿已错过**，起服务不会补（`SYNC_CATCHUP=off`）；`legStaleness` 会是 `missed-today`，
  这是预期读数，不是故障。下一自然轮 **2026-10-24 02:00**。

## 1. 现查读数（2026-10-23 10:35）

| 项 | 现值 | 出处 |
|---|---|---|
| web 3000 / ds 8000 | 均无监听；`curl` 返回 000 | `netstat -ano \| grep LISTENING`、`curl` 现跑 |
| `Product` 行数 | fund 28107 / stock 5575 / bond 1064 / us 507 / crypto 250 / **hk 0** | 只读 SQL 打开 `web/prisma/dev.db`（`mode=ro`） |
| `backups/state.json` | `lastRun=2026-10-22T03:30:00+08:00`、`ok=true`、`trigger=daily`、**无 `label` 键**、`kept=7` | `cat backups/state.json` |
| `sync-state.json` | `lastAttemptDate=2026-10-22`、`outcome=partial_failed`、hk 报东财 `RemoteDisconnected` | `data-service/runtime/sync-state.json` |
| `hotspot-state.json` | `lastAttemptDate=2026-10-22`、`trigger=post-market`、`outcome=completed` | `data-service/runtime/hotspot-state.json` |
| 最近服务 | 10-22 18:41 起过；日志最后写入 10-23 01:07；现两棵均无监听 | `data-service/runtime/start-both-1022-181x.out` |
| 分支/工作树 | `dev`；仅两个未跟踪 `.err`（`data-service/ds-1021-1745.err`、`web/dev-1021-1735.err`） | `git status --porcelain` |

## 2. 盘点清单

### A. 真未闭环（账本现值 2 项）

| 编号 | 事项 | 现状（证据） | 剩余动作 |
|---|---|---|---|
| **CR9-26②** | hk 列表 0 行（上游态） | 库内 hk 0 行；10-22 同步 hk 报东财 `RemoteDisconnected`；代码已有东财主源＋CR10-5 新浪第二腿 | 等东财恢复或东财真断夜触发新浪腿；到货后补 CR7-4 的 `/product/hk/00700` 手测 |
| **C31** | Dockerfile `setpriv` 进程降权的镜像构建/运行验证 | Dockerfile / compose 都在；**没有任何 `docker compose build/up` 现场回执** | 主人指示暂缓；启用 Docker 前必须验三项：容器内 uid、两容器 healthy、`compose exec` 备份正常 |

### B. 代码/测试已完成，等现场读数（2 项）

| 编号 | 事项 | 现状 | 现场判据 |
|---|---|---|---|
| **CR10-4** | 备份 `state.json` 多一枚 `label` | 代码已落（`backup_scheduler.py` 的 `run_once` 写 `label`；`startup_catch_up(label="startup")`／`hourly` 两个入口）；当前 `state.json` 仍是旧码写的，无 `label` | 起 ds 后读 `backups/state.json`：`"label":"startup"`、`trigger:"startup-catchup"`、`ok:true`、`outcome:"completed"`、`kept:7`；`runs` 是本进程计数，新进程第一轮应为 **1**；同时看 `backups/` 新增 `dev-20261023-*.db` |
| **CR10-5** | hk 新浪降级腿 `source=sina-hk-spot` | 代码＋`test_cr10_5_hk_sina_fallback.py` 27/27 已落并装载过；尚未遇到东财真断源夜 | `sync-state.json` 的 `lastResult.results[hk].note` 出现 `source=sina-hk-spot`（通常形如 `list degraded source=sina-hk-spot：…`）；**只有新浪腿被行使才算**，东财成功不能当 CR10-5 验收 |

### C. 处置需要一句话（账本正式「等字」只有 #83）

| 项 | 选项 | 推荐 |
|---|---|---|
| **#83** | ① 不立项（空号保留）② 立项（按 CR9-118「净零行＋只引符号」） | **不立项**，零动作、不阻塞 |
| **C28 观察项** | ① 补码读 `lastFailed` ② 修订 C28 正文承认 `lastCheckedTail` | **②**：失败路径也写 `lastCheckedTail`，30 分钟抑制功能已在；①「一行」不完整（还要在尾部失败时写 `lastFailed`＋新断言），会重新耦合头/尾失败窗口。另：`web/lib/kline.ts` **不在** `DS_RESPONSE_FILES`，改它**不会**点亮闸2 L3，FIX-LEDGER :697 那句判断按现行代码不成立 |
| **下一枚「搬」** | 给「搬」字则搬进 `docs/history/`；不给则维持 | 下一轮 docs 收口再搬；只走 `python scripts/docs-scan.py --move`，不手写搬家脚本 |

### D. 文档残留（不阻塞功能，建议下一轮 docs 收口一并修）

| 位置 | 残留 | 建议 |
|---|---|---|
| `.claude/rules/project.md:89` | 「当前开放轮次 CR9」 | 改为 CR10（或「审查期 CR1–CR10」）；常驻规则每次会话都加载，误导面最大 |
| `docs/CODE-REVIEW.md:9` | 速览「当前轮次是 CR9」 | 该文件「只增不改」⇒ 在速览后加一行现值更正，指向 `:32` 已有那条 |
| `docs/README.md:29` | 文档地图「CODE-REVIEW.md：当前轮 CR9 的完整发现」 | 加一行现值更正指向 CR10 |
| `docs/PLAN.md:433` | P5 验收③仍写「TradingAgents 全程只走 vendor_adapter」，实装主力是 B 计划 `custom-multichar` | 加一行现值更正，说明 native TradingAgents 是后续增强；或保留为未来增强项 |
| `README.md:27-43` | 本地启动顺序写「data-service 终端 1、web 终端 2」 | 与已验证的「先 web 后 ds」相反；以 `docs/README.md:34` 与 `runtime/start-both-1022-181x.ps1` 为准，建议改序并注明原因 |

### E. 已定档 / 明确不做 / 需数据源（列出防误读，不是欠项）

- **G7 完整身份鉴权**：token 链路已配置且双侧生效（10-14 00:19 复读 `ingestTokenConfigured=true`、无 token 回 401）；完整身份鉴权按定档**上云或 `WEB_PORT` 对外前必补**。
- **详情页扩展字段**：股票 PE 历史分位、场内基金跟踪指数/规模/费率/折溢价、场外基金经理/风险等级——定档「给了数据源才谈」；加密市值排名/24h 量——数据源待决策；基金分红节点——数据源给不了（只有定期报告清单）。
- **热点「去分析」真解读**：当前只跳 `related[0]` 详情页 `#research` 锚点，不调 Agent；真做需另立需求。
- **美股全量「乙」913 页**：已定档「甲+」50 页（us 507 行）；乙是未选中的另一档，不是待办。
- **Watchlist 清单页**：已拍板不做（G5 写入已交付）。
- **MCP server 默认不启用**：设计如此（compose 默认 profile 不启动）。
- **P5 native TradingAgents**：后续增强；当前 `custom-multichar` 是实装主力。
- **东财限流/转债 K 线无备源**：已有多源降级/限速/熔断，记录搁置。
- **详情页四条 verdict**：`agree`（600519）与 `noSecondSource`（510300）已于 10-19 由主人在屏上亲眼验到；只剩 `diverged`/`stale` 不可按需制造，留观察项。
- **备份 restore 人工恢复一次**：机制与 19/19 测试都在，归 P7 桶，不建编号。
- **本机无自启 / 防睡本轮没起**：开机后人工起两棵；防睡未起 ⇒ 16:30、10-24 02:00/03:30 不在保护内；进程级防睡也挡不住关电源。

### F. 今日运维缺口（不是账本欠项，但会影响「今天结束项目」）

- **今天 02:00 同步腿已错过**：起服务不补（`SYNC_CATCHUP=off`）；下一自然轮 10-24 02:00。若要今天全类型数据前进，只能 `POST :8000/sync/run`（全六类＋链式刷新，昂贵）。
- **今天 08:30 热点盘前腿已错过**：起 ds 约 5s 后会补跑**一整轮 pipeline**（10-22 实测 63.7s、预算上限 300s），会花东财/akshare/财联社/Tavily/LLM 额度，不是免费读数。
- **16:30 热点盘后、10-24 02:00 同步、03:30 备份**：只有进程活着才会跑；防睡未起、且挡不住关机，若机器睡眠/关机就继续丢腿。

## 3. 逐项执行方案

### A1 · CR9-26② hk（最高价值，决定 CR7-4 能否收尾）

账本 10-19 已定档「不手动买那 48 页，每晚 02:00 自带一次尝试、不设截止」⇒ 默认走零成本那条；手动那条只有给「跑」字才做。

1. **零额外成本（默认）**：保持机器与两棵服务运行到 **2026-10-24 02:00**（本机无自启，关机则顺延到下一次 02:00），日常同步腿自带一次 hk 尝试；次日读 `data-service/runtime/sync-state.json`：
   - hk `count>0` ⇒ 到货；直接做 `/product/hk/00700` 手测；
   - hk `note` 出现 `source=sina-hk-spot` ⇒ CR10-5 现场读数同时取得（再看 `count` 判断覆盖面）。
2. **今天闭环（需一句「跑」）**：`POST http://127.0.0.1:3000/api/sync?type=hk`（web BFF 的 hk 单腿；内部只调一次 ds `/products?type=hk`；东财失败则走新浪第二腿，最长约 420s）。返回体 `results[0]` 给出 `count` 与 `note`：
   - 成功到货（东财）⇒ `Product` hk 行数 > 0，随后 `/product/hk/00700` 手测 ⇒ **CR9-26② 可闭**；
   - 东财失败、新浪成功 ⇒ 返回体 `note` 出现 `list degraded source=sina-hk-spot：…` ⇒ 这是 **CR10-5 的手动腿证据**；但账本点名的载体是 ds 的 `runtime/sync-state.json`，该文件只由 ds 调度腿写，**手动 web 同步不会写它**；
   - 失败（两支都抛错）⇒ 记录原文，不重试超过 3 次，等自然轮。
3. **只想取 CR10-5 读数、不想写库**：`GET http://127.0.0.1:8000/products?type=hk`（响应看 `source`/`degraded`/`intentionalSubset`/`note`）。不写 `Product`、不触发当日幂等闸，但同样花上游额度。**只有 `source=sina-hk-spot` 才算 CR10-5 现场读数；若 `source` 是主源（`akshare-hk`），新浪腿没被行使，不能当 CR10-5 验收。**
4. **顺序约束**：热点补跑（启动后约 5s、约 64s、预算上限 300s）结束前不要发 hk 或全量同步——两者抢东财/akshare 桶，可能把热点拖成 degraded；先等 `/hotspots/status.running=false`。
5. **首次到货的保护盲区**：70% 缩水保护要求 `existingCount > 0` 才生效（`web/lib/sync.ts:223`）⇒ hk 首次到货没有基线；若上游只给回一小截，这一轮会静默成为常态。验收时同时读 `count`、`note`、`intentionalSubset`，不把「有行」直接读成「全量覆盖」。
6. **落库后价格列**：列表腿不刷快照，`lastPrice/lastChangePct` 为空；要价格列再跑 `POST :3000/api/market/refresh?type=hk`（约 4 分钟）。00700 详情页本身走 `/api/quote` 实时腿，通常不受影响。

### A2 · C31 Docker 验证（暂缓，不主动推进）

启用 Docker 闸口时按序做（预计 15–30 分钟，含镜像构建）：

```bash
docker compose build
docker compose up -d
docker compose ps                      # 期望 web / data-service 都 healthy
docker compose exec data-service id    # 期望 uvicorn 侧 uid=1000；setpriv 生效
docker compose exec web id             # 期望 node 用户
# 再按 backup_db 的容器内命令跑一次备份，确认 /backup、/data 可写且产物可读
```

前置：根 `.env` 已有 `INGEST_TOKEN` 键（2026-10-23 只查键名：`WEB_PORT/LLM_*/TAVILY_API_KEY/NO_PROXY/INGEST_TOKEN`），compose 不会因缺 token 拒绝启动。

### B1 · CR10-4 备份 label（起服务即取）

- 起 ds 后等待启动备份完成（约 5–30 秒，取决于 71 MB 复制；`request_run` 起后台线程，完成时才写盘），读 `backups/state.json`：
  - 期望 `"label":"startup"`、`"trigger":"startup-catchup"`、`ok:true`、`outcome:"completed"`、`kept:7`；
  - `lastRun` 变为 2026-10-23 当前时刻；
  - `runs` 是本进程计数，新进程第一轮应为 **1**（不是旧文件的 2+1）；
  - `backups/` 下新增 `dev-20261023-*.db`，`dev-*.db` 仍 7 个，最老的 `dev-20261016-194206.db` 被轮换删除。
- **「有 label」不等于「备份成功」**：失败分支同样写 `label`，只是 `ok:false`、`outcome:"failed"`；必须同时看 `ok/outcome`。
- 若启动补备份没触发，等每小时 `hourly` stale check（`staleCheckNextRun`）或 10-24 03:30 日常轮，再读同两个键。

### B2 · CR10-5 新浪腿现场读数（等 ds 调度腿）

- 该腿只在 ds 调度腿（02:00 同步）里自然触发，并写 `data-service/runtime/sync-state.json`；**手动 `POST :3000/api/sync?type=hk` 不写这个文件**。
- 若 10-24 02:00 自然轮遇到东财列表失败，新码会自动走新浪 `getHKStockData`；读 `sync-state.json` 的 `lastResult.results[hk].note`：
  - 出现 `source=sina-hk-spot` ⇒ 现场读数取得；
  - 若仍抛 `ProviderError` ⇒ 记录失败原文，不重试（最多 3 次纪律）。
- 不可按需制造东财断源；只登记。

### C1 · #83（推荐不立项）

零动作，空号继续保留。若主人要立项：按 CR9-118 的「净零行＋只引符号」修
`data-service/app/providers/chain.py:67` 注释，不碰行为；是否需要同窗重采按该文件是否在闸2 构造面现查。

### C2 · C28（推荐乙：改正文承认 `lastCheckedTail`）

- 在 `docs/CONSTRAINTS.md` C28 条目补一句：尾部增量分支用独立的 `lastCheckedTail`（成功与失败都写），
  功能上等价于「失败窗口＋复查窗口」合并计时；头部缺口分支仍按 `lastFailed`／`lastChecked` 双判。
- 理由：现码在失败路径也写 `lastCheckedTail`（`kline.ts:355-358`），30 分钟内不会重复回源，
  **没有观察到功能缺陷**；C34 的对称记账已满足。另：`web/lib/kline.ts` **不在** `DS_RESPONSE_FILES`
  （`web/lib/ds-contract.ts:187-193`）⇒ 改它**不会**点亮闸2 L3；但甲若只加「读 `lastFailed`」并不完整，
  只会让头部失败顺带压尾部 30 分钟，完整甲要 2–3 行＋新断言。乙是 docs-only、零额度、零行为变更。
- 需一个「改」字（docs-only）。

### C3 · 「搬」四枚巨行

需「搬」字；只允许走 `python scripts/docs-scan.py --move` 的四种切块，不手写搬家脚本；搬完跑断链扫描。
建议与 D 类文档残留同一轮做，减少窗口。

### D · 文档残留

建议下一轮 docs 收口一次修：`.claude/rules/project.md:89` 改 CR10；`CODE-REVIEW.md:9`、`README.md:29`、
`PLAN.md:433`、根 `README.md:27-43` 各加一行现值更正（`CODE-REVIEW` 只增不改）。

### E · 已定档项

全部零动作；触发条件见上表。G7 的完整鉴权设计（上云前）：BFF 边缘加统一鉴权中间件
（Auth.js/OIDC 或反代 Basic Auth），保留 `x-ingest-token` 作服务间凭据，生产环境缺配置时 fail-closed，
并按调用方限流。

### F · 今日运维缺口

- 要今天全类型数据前进：`POST :8000/sync/run`（全六类＋链式刷新，约 10–15 分钟列表＋刷新腿最长约 40 分钟），需「跑」。
- 要 16:30 / 10-24 02:00 / 03:30 三腿在场：起防睡（进程级，挡不住关机），需「起防睡」。

## 4. 若批准执行的推荐顺序

1. **预检（只读，零出网）**：确认 3000/8000 无监听；读 `backups/state.json`、`sync-state.json`、
   `hotspot-state.json`、`limiter-state.json`；`git status --porcelain` 确认没有新改动。
2. **先起 web**：`cd web && npm run dev`；等 3000 监听；`curl :3000/api/health` 期望 `status:ok, db:ok`；
   `curl "http://127.0.0.1:3000/api/hotspots/ingest?date=2026-10-23"` 期望 `count:0`。
3. **再起 ds**：`SYNC_CATCHUP=off`、`PYTHONPATH=.`、`.venv/Scripts/python.exe -m uvicorn app.main:app
   --host 127.0.0.1 --port 8000`；**不带 `--reload`**、**不手设 `NO_PROXY`**；`HTTPS_PROXY` 由
   `data-service/.env` 提供。
4. **等两个补跑收敛**：备份启动即触发，等 5–30s 读 `label`；热点约 5s 触发，轮询
   `/hotspots/status.running=false`（最多等 300s）。**热点跑完前不要发 hk/全量同步。**
5. **记录四条腿 nextRun**：同步 10-24 02:00、备份 10-24 03:30、热点 10-23 16:30、备份 stale check 约 11:3x。
6. **免费读数**：`/health`（`ingestTokenConfigured:true`、`abandonedWatchdogs:0`、`dbBackup` 新时刻）、
   `/hotspots/status`（`lastAttemptDate=2026-10-23`）、`/sync/status`（`legStaleness=missed-today`）、
   `backups/state.json`（`label:"startup"`）、`limiter-state.json`（出现 `2026-10-23` 日格）。
7. **需字动作**（默认不做）：hk `GET` 取读数 / hk `POST` 落库 / `market/refresh?type=hk` 补价格列 /
   `sync/run` 补全量 / C28「改」/ 搬「搬」/ 防睡「起防睡」。

## 5. 验证与边界

- 验证命令：`netstat -ano | grep LISTENING | grep -E ":(3000|8000)\s"`；`curl -s :3000/api/health`；
  `curl -s :8000/health`；`curl -s :8000/hotspots/status`；`curl -s :8000/sync/status`；
  `cat backups/state.json`；`cat data-service/runtime/limiter-state.json`；
  只读 SQL `select type, count(*) from Product group by type`。
- **本轮边界**：不新增审查发现；不把「可选扩展」当欠项；不制造自然事件读数
  （`diverged`/`stale`、东财断源夜、新浪腿现场值）；不重复手动买 hk 48 页。
- **不做**：C31 Docker、G7 完整鉴权、数据源类扩展、美股乙、Watchlist 清单页、MCP 默认启用、
  native TradingAgents；这些均维持已定档状态。
- **提交纪律**：本文件单独 commit，只 add `docs/END_PLAN.md`；不 push；不提交任何 `.env`、数据库、
  `backups/` 文件或密钥。
