# 不得回退的知识资产（CONSTRAINTS）

> **职责**：收录"改代码前必须自查、不得回退"的规则与事实。
> 需求与设计见 [PLAN.md](PLAN.md)，执行进度见 [PROGRESS.md](PROGRESS.md)，
> 审查发现见 [CODE-REVIEW.md](CODE-REVIEW.md)，修复状态见 [FIX-LEDGER.md](FIX-LEDGER.md)。
>
> **维护规则**：只收录能对应到代码位置或守护测试的条目；代码注释只写编号引用（如 `见 C17`），
> 规则正文唯一写在本文件。写不出验证方式的条目应标 ⏳ 而不是当作既成事实。
>
> 轮次编号（C1–C34 分别来自哪一次审查）见 [CODE-REVIEW.md](CODE-REVIEW.md) 顶部的「轮次对照表」。

> **速览**：改代码前必查本文件。§A 是 34 条不得回退的工程约束（C1–C34，按来源审查轮次分五批）；§B 是跨服务/跨语言契约坑（两侧各自解析的参数最易静默出错）；§C 是数据源与外部依赖的实测事实（转债 C-1 / 依赖定版 C-2 / 港股 C-3 / 主备源矩阵 C-4）；§D 是部署与容器化约束。

## A. 工程约束（C1–C34，不得回退）

### 第一批（C1–C17，来自 CR1 / CR2 / 缺陷修复）

| 编号 | 规则 | 守护位置 / 来源 |
|---|---|---|
| **C1** | **空载荷保护**：`syncType` 全量替换（先删后插）前必须判空——上游返回空列表时**保留旧数据并返回 error**，禁止静默清库 | `web/lib/sync.ts` |
| **C2** | **会话上下文取最近 200 条**：`getMessages` 必须 desc 取再反转时间序；asc+take 会静默丢弃最新对话 | `web/lib/chat.ts` |
| **C3** | **LLM 流必须 flush 尾帧**：最后一帧常无换行结尾（可能携带 finish_reason/tool_calls 分片）；工具调用产出**只看累积结果**，不强依赖 `finish==="tool_calls"` | `web/lib/llm.ts` |
| **C4** | **行情数值缺失一律 null**：禁止 `Number(null)===0` 式转换把"缺价"上报成"现价 0 元" | `web/lib/tools.ts#numOrNull`（**唯一防线，且至今无单测**，见 CR7-11） |
| **C5** | **`provider.get_news` 契约 = `list[dict]`**：研报采集链对 dict/list 双兼容（此前东财主源一旦真正返回新闻就 AttributeError 打挂整条研报任务，巨潮备源成死代码） | `data-service/app/research/adapter.py` |
| **C6** | **限速器成功回报时机**：HTTP 状态码校验与 JSON 解析必须在 `_em_request` 闭包**内**完成——5xx/非 JSON 不得清零熔断计数 | `data-service/app/providers/akshare_provider.py` |
| **C7** | **akshare 调用统一看门狗**：所有 provider 内 akshare 调用经 `_em_ak_request` / `_ak_request` 包装（上游挂死时按时返回降级，不永久占住线程池 worker） | `data-service/app/utils/timeout.py` |
| **C8** | **研报完成推送带会话归属**：启动时登记发起会话（`watchResearch`），完成时①落库到发起会话②广播携带 `sessionIds`，前端按当前会话过滤 | `web/lib/research.ts` |
| **C9** | **浏览器只与 web 通信**：禁止前端直连 data-service（P7 容器化后 data-service 不发布端口）；经 `POST /api/hotspots/run` 等 BFF 代理 | 各 `web/app/api/**/route.ts` |
| **C10** | **ingest 结果必须可观测**：research 落库回调失败写回任务状态（`ingestOk`/`ingestNote`），禁止"任务显示成功但研报未落库" | `data-service/app/research/tasks.py:156-166`（**写回侧在此，非 web 侧**——2026-09-24 核对：`ingestOk`/`ingestNote` 在 `web/` 零命中）；消费侧读 `web/lib/research.ts` 的 `ok`/`note` 字段 |
| **C11** | **K 线增量缓存防重复回源**：头部缺口回源失败同样进入失败窗口（`RECHECK_MS` = 30 分钟，`kline.ts:47`）；并发写入的重复行现由 **`INSERT OR IGNORE`** 吸收（`:184`，注释在 `:158` 明写"无需 catch P2002"）——**机制已换，不再是"P2002 按已写入处理"**；P2002 判定现仅存在于 `web/lib/hotspots.ts:44,219`（热点去重路径） | `web/lib/kline.ts:47,157-185,262` |
| **C12** | **快照刷新失败必须显式**：整批无可用报价计入 `failedBatches`，禁止"0 更新 0 失败"伪装成功 | `web/lib/market-snapshot.ts` |
| **C13** | **界面细节**：热点时间用北京时间（Intl timeZone）；SSE updater 内禁止副作用；ECharts 卸载必须 dispose；搜索 loading 收尾须确认请求未过期；browse 模式 sort/page 从 URL 还原；详情页五路取数并行 | 各前端页面 |
| **C14** | **安全基线**：外部抓取链接仅放行 `http(s)`；`/api/health` 不回显异常细节；`/api/tools/status` 不回显服务端路径且探测结果缓存 30s；MCP 工具名截断时附加哈希防碰撞 | `web/lib/*`、`web/app/api/health` |
| **C15** | **FTS 与主表一致性**：`rebuildFts(type)` 必须先做**孤儿清理**（`DELETE FROM Product_fts WHERE productId NOT IN (SELECT id FROM Product)`，与 type 无关），再按 type 重建。**原因**：L1 全量替换会给产品生成全新 id，按"当前 Product 表 id"定位的 DELETE 无法命中旧 id 的 FTS 行 → 每次同步累积与该类型条数相等的孤儿（实测 bond 一次同步即留 1052 行）；L1 的暂存表用完后必须 `DROP TABLE`（不得只 `DELETE`） | `web/lib/sync.ts` + 运维脚本 `web/scripts/fix-fts.mjs` |
| **C16** | **采集线程安全**：`adapter._run_with_timeout` 内对模块级计数器（`_collect_live`/`_collect_inflight`）赋值**必须声明 `global`**（L3 引入时仅声明了 `_collect_live` → `_collect_inflight += 1` 变局部变量 → **UnboundLocalError → 研报引擎全部采集即时崩溃**，且因 test-p5 复用当日已完成研报而未覆盖到）；信号量 `acquire()` **必须有超时** | `data-service/app/research/adapter.py` |
| **C17** | **进程内注册表/单例必须挂 `globalThis`**：Next dev 按需编译 / HMR 会重建模块作用域，**模块级变量随之重置** → "写入方与读取方持有不同实例"的静默故障。已发生两例：① P6 MCP 运行时注册表（每次重载重复 spawn stdio 子进程）；② P3 SSE `clients` Map（事件偶发丢失，test-p3 间歇失败）。规则：任何**跨请求共享状态的进程内单例**（连接表、注册表、缓存、锁）一律用 `Symbol.for("invest-manager.<name>")` 挂 `globalThis` | `web/lib/mcp.ts`、`web/lib/events.ts` |

### 第二批（C18–C23，来自 CR2，2026-09-13）

| 编号 | 规则 | 守护位置 |
|---|---|---|
| **C18** | **每轮工具循环必须重新裁剪上下文**：`chat/route.ts` 的工具循环内**不得**使用循环外一次性计算的裁剪快照——超预算时 `trimContext` 返回新数组，循环内 `messages.push()` 的工具结果不会出现在发给 LLM 的数组 → 多轮 function calling 静默失效；同步修正裁剪边界（**最后一条消息自身超预算时硬截断保留，禁止整条丢弃**） | `web/app/api/chat/route.ts` |
| **C19** | **研报订阅生命周期**：`researchWatchers` 必须挂 globalThis（C17 同类）；且 **failed 分支同样 `takeWatchers` 清理并向发起会话推送失败说明**——否则 Map 无界增长 + 发起会话收不到任何反馈 | `web/lib/research.ts` |
| **C20** | **同步/采集必须单飞**：`syncType` 用**固定名暂存表**，同类型并发同步会互相清空对方暂存行 → 事务拷入不完整集合 → Product 数据丢失；已加按类型 in-flight 单飞；暂存表清理统一放 **finally**（失败路径同样 DROP） | `web/lib/sync.ts` |
| **C21** | **数值序列化安全**：`to_float` 必须过滤**全部非有限值**（NaN 与 ±Inf，`math.isfinite`）；所有 provider 的数值字段（含 yfinance `fast_info` / K 线行）禁止裸 `float()`——非有限值进入 JSON 会因 `allow_nan=False` 抛 ValueError → 500，破坏"失败显式降级"契约 | `data-service/app/utils/num.py` |
| **C22** | **恢复类操作的先验校验与回滚**：`backup_db.py restore` 必须①恢复前对备份做 `integrity_check` + 表结构校验（非法备份拒绝执行，防止把线上库"恢复"成空文件）②清理目标库的 `-wal/-shm` 残留（旧 WAL 会被误应用）③失败自动回滚原库 | `data-service/scripts/backup_db.py`（**全项目唯一破坏性覆盖线上库的脚本，却零自动化回归**，见 CR7-11） |
| **C23** | **测试脚本不得污染开发库**：测试内的 `deleteMany({})` 等批量清理**必须限定范围**（按测试会话/标题前缀），禁止无 where 的全库删除；验收断言不得写死单一数据源 `source` 值（多源链下降级属正确行为） | `web/scripts/test-*.mjs`、`data-service/tests/*.py` |

### 第三批（C24–C25，来自 CR3 / P7 落地，2026-09-14）

| 编号 | 规则 | 守护位置 |
|---|---|---|
| **C24** | **依赖归属变更必须同步锁文件**：把包在 `dependencies` / `devDependencies` 之间移动后，**必须重跑 `npm install --package-lock-only`**——`npm ci` 与 `npm prune` 以锁文件为准，仅改 `package.json` 会导致 `--omit=dev` 把运行时必需的包（本次是 `prisma` CLI）裁掉，容器启动时 `migrate deploy` 直接失败 | `web/package-lock.json` + `web/Dockerfile` |
| **C25** | **裁剪必须在独立 stage 完成**：`npm prune` / `rm -rf` **不能在 runner 内"先 COPY 全量再删除"**——被删文件仍留在更早的层里，镜像体积不会下降（实测仍 1.62GB）。正确做法：`FROM build AS prod-deps` 内裁剪 → runner 只 `COPY --from=prod-deps` | `web/Dockerfile` |

### 第四批（C26–C33，来自 CR4，2026-09-15/16）

| 编号 | 规则 | 守护位置 |
|---|---|---|
| **C26** | **跨类型共享实体必须带 type 作用域**：A股与基金/转债代码段大量重叠（如 `000001` = 平安银行 stock 与 华夏成长混合 fund 并存）。凡以 `code` 参与唯一键或查询的实体（`ResearchReport` 等）**必须把 `type` 纳入唯一键与 where 条件**——唯一键已由 `(code,date)` 升级为 `(type,code,date)` | `web/prisma/schema.prisma` |
| **C27** | **进程内缓存/单例一律挂 `globalThis`（C17 补漏）**：C17 的适用范围明确包含**缓存**——`kline.lastChecked/lastFailed`、`events` 缓存亦须挂 `Symbol.for`（dev HMR 重置会使 `lastFailed` 限流窗口失效，叠加回源放大）。**C17+C27 合并口径：任何跨请求共享的进程内单例（连接表、注册表、缓存、锁、watcher）都必须挂 `globalThis`，无例外** | `web/lib/kline.ts`、`web/lib/events.ts` |
| **C28** | **K 线缓存窗口抑制必须双向对称**：`kline.ts` 的**头部缺口补齐分支与尾部增量分支**都必须同时判断 `lastFailed`（失败窗口）与 `lastChecked`（复查窗口），且头部缺口"成功但空响应"同样要写入 `lastFailed`——否则上市不足区间的标的每次加载都整段回源头部缺口 | `web/lib/kline.ts` |
| **C29** | **限速器以"逻辑请求"为单位计次**：多 host/多轮重试的**同一逻辑请求**必须包在**单个** `_em_request` 闭包内，只 `acquire()` 一次、只回报一次成功/失败——按 host 逐次计次会在 `failure_threshold=2` 下被两次抖动触发全源族熔断（第 3 个 host 永远轮不到）；状态码校验与 JSON 解析仍必须在闭包内完成（C6） | `data-service/app/providers/akshare_provider.py` |
| **C30** | **数值转换禁止裸 `float()`（C21 补漏）**：重申适用于 **sina_provider 的 K 线行 / crypto_provider 的 quote+kline / pipeline 板块涨跌幅**等此前漏网处；裸 `float()` 拦不住 NaN（`float(nan)` 不抛异常）会污染缓存与落库文本 | `data-service/app/providers/*.py` |
| **C31** | **长驻进程不以 root 运行，但保持 exec 语义**：data-service 容器默认用户保持 root（`compose exec` 备份/恢复需写 `/backup`、`/data`），仅 **uvicorn 经 `setpriv` 降权到 uid 1000**（与 web 容器 node 用户同号）；`setpriv` 缺失时回退 root 直跑并告警。**⚠️ 此约束的镜像构建/运行验证尚未执行**（主人指示暂不推进 Docker），启用前必须先验证容器内进程 uid、两容器 healthy 与 `compose exec` 备份正常 | `data-service/Dockerfile` |
| **C32** | **前端在途请求与定时器必须可取消**：① 加载型 fetch（图表区间/对比、搜索）必须用 `AbortController` + 请求序号守卫，**过期响应不得写入状态**，收尾 `setPending(false)` 仅限当前请求；② 轮询 `setInterval` 必须有清理路径与**次数上限**，且 effect 内 `await` 之后设置定时器前须检查 `cancelled` 标志；③ 轮询循环（如热点触发）须挂卸载标志 | `web/app/**/*.tsx` |
| **C33** | **对外接口输入必须白名单校验**：路由层禁止信任 TS 类型（运行时无约束）——`sessions PUT` 的 `role`、`research/start` 的 `type`/`code`、`search` 的 `q` 长度一律显式校验（type 白名单、code `[\w.-]{1,20}`、q ≤100 字符）；`code`/`type` 会拼入研报推送的 markdown 链接，收紧字符集可抑制外链注入面。**⚠️ 已知覆盖不全**：`/api/kline`、`/api/quote` 两个 GET 端点仍无 code 校验（见 CR7-6） | `web/app/api/**/route.ts`、`web/lib/validate.ts`（**待建**） |

### 第五批（C34，来自 CR5，2026-09-17）

- **C34 缓存窗口/计数必须与成功路径对称记账**：任何"失败负缓存 / 限流计数 / 熔断计数 / 复查窗口"的写入点，**必须与成功路径成对存在**——只写成功、不写失败的守卫会因此恒假而**静默失效**（代码看起来有防护，实际是死代码）。本次两例：① CR5-1 CoinGecko `_markets_fail_ts` 仅在 `__init__` 与成功路径置 0、失败路径从不写入 → 守卫 `now - fail_ts < COOLDOWN` 恒真失效，不可达时每请求空烧 ~41s；② C28 的 kline `lastFailed`/`lastChecked` 头部缺口分支漏写（CR4-4）。
  **验收要求**：此类修复必须附**反向验证**（临时回退修复，确认对应断言会失败），防止"声称已修实则失效"再次发生。

> **CR5 修复的需求映射**（CR5 未新增需求编号，其修复回填到既有需求）：
> CR5-1 → R15；CR5-2 → R16（新增）；CR5-3 → R17（新增）；CR5-P5 → R5/R16；
> CR5-P1 → C17/C27；CR5-P2/P3/P6 → R10/C33；CR5-D1 → R13（暂不处理）；
> CR5-D2/D3 → M1 webhook / M2 LLM 兜底（暂不处理）；CR5-P4 写接口鉴权 → 上云前必补。

---

## B. 跨服务 / 跨语言契约坑

> 这一节按"踩过的坑"记，不按接口记。每一条都曾造成**静默错误**（不报错、测试也不挂）。

| 契约 | 事实 | 教训 |
|---|---|---|
| **日期格式（web 侧）** | `/api/kline` 的 `normalizeRange`（`web/lib/kline.ts`）**只接受 ISO 带连字符** `/^\d{4}-\d{2}-\d{2}$/` | 不匹配即**静默回落默认值**（`start=today-90`、`end=today`），既不报错也不写 note |
| **日期格式（akshare 侧）** | akshare 入参要**紧凑 8 位** `YYYYMMDD`（如 `ak_stock_disclosures`） | 两个契约方向相反，改代码时极易误伤另一个 |
| **已发生的实例** | `data-service/app/research/adapter.py` 的 `_iso_days_ago`/`_today_iso` 曾用 `strftime("%Y%m%d")` 回读 web `/api/kline` → 被静默回落 → **研报的 K 线/阶段维度永远是 90 日口径**，`days` 参数整个是装饰品，「研报与详情页归因同源」在窗口长度上并不成立 | CR7-2（修复状态见 [FIX-LEDGER.md](FIX-LEDGER.md)）。**两侧都有数据返回，集成测试不会失败**——与 V1 同族 |
| **Prisma DateTime 在 SQLite 的存储** | Prisma 存的是 **Unix 毫秒整数**（实测 `typeof(date)='integer'`） | 原生 `INSERT` 若传 ISO 字符串，该行与 Prisma 生成的 `date >= ? / <= ?`（数字比较）**不匹配** → 带日期范围的查询**静默漏行**。V1 实测污染 3 行，导致 K 线图少一根、缓存天数虚高、R13 交叉验证失败。**规则：原生写入必须传 `dayStart(d).getTime()`** |
| **北京时间口径** | web 侧用北京时间建/查 `(type,code,date)`；data-service 侧曾全部用**本地时区** `date.today()` | TZ≠Asia/Shanghai 时，北京时间 00:00–08:00 区间会出现"回调带 D-1 → D 行永久 running + D-1 重复行"与每日限额错位。**规则：data-service 一律用 `app/utils/timeutil.py` 的 `beijing_*()`，禁用 `date.today()`**（CR-06） |
| **`/api/kline` 的 `phases` 字段** | 研报与详情页归因同源的契约（P5 落地定稿新增） | 改动 `/api/kline` 响应结构时须同步 `research/adapter.py` |
| **provider 的 `currency` 字段** | provider 早已返回（hk=HKD / us=USD / sina-bond=CNY），但 `web/lib/data-service.ts` 的 `Quote` 类型**没有该字段**，全 web 侧 `grep currency` 零命中 | 港股在列表与详情页显示成无单位数字（`100` 实为 100 港币）。CR7-4（修复状态见 [FIX-LEDGER.md](FIX-LEDGER.md)） |

**新增跨语言/跨服务参数的通用规则**：凡是跨进程传递、且两侧各自解析的参数（日期、代码前缀、枚举值），**必须在两侧都写断言**——一侧写错而另一侧静默回落，是本项目已发生两次的错误模式（V1、CR7-2）。

---

## C. 数据源与外部依赖事实

### C-1 可转债链路（2026-09-13 定稿；实现见 `data-service/app/providers/sina_bond_provider.py`）

| 项 | 事实 |
|---|---|
| 行情备源 | 新浪 `ak.bond_zh_hs_cov_spot()` 全量快照（约 320 只沪深转债，含真实成交）。**非东财域名**，绕开东财 IP 级限流。实现要点：快照缓存 60s + 锁内双检 + 看门狗 |
| 列表备源 | 同源 `cov_spot`（东财限流兜底；覆盖度较低，属降级可用） |
| **K 线无备源** | 仅东财一个源。限流时**显式降级即正确行为**（R10/R12），不得当作缺陷去"修" |
| 未上市 / 已退市转债 | 不在 `cov_spot` 列表内（如 113710 四方转债、123285 润禾转02），其行情与 K 线本不可得 → 取数时须报**明确错误**，不得静默缺失。**此前 P2 遗留的"转债 K 线 2 项失败"即因测试动态选中了此类未上市标的，被长期误归因为东财限流** |
| 活跃代码段 | 沪 111/113/118、深 123/127/128（`110xxx` 多为沪市老债/已到期段，通常无行情） |

**已实测排除的 K 线路由 —— 勿重复尝试**：

| 路径 | 排除原因 |
|---|---|
| `ak.bond_zh_hs_cov_daily`（新浪转债日线） | 接口返回空（JS 解码后无数据，已废弃） |
| 腾讯 `fqkline` / `kline` | 转债 `day` 恒为空，不覆盖转债 K 线 |
| 腾讯 `qt.gtimg.cn` | 格式兼容，但非交易时段恒为面值 100.000 / 零成交，不可靠 |
| 新浪通用 K 线（`CN_MarketData.getKLineData`） | 转债返回 null |
| 网易 `chddata` | 沙箱内 502 —— **本机环境待验证**，仍作为候选源记录在 PLAN，**非彻底排除** |

### C-2 依赖定版（`data-service/requirements.txt`，2026-09-20 逐条核对一致）

| 包 | 版本区间 | 为什么钉住 |
|---|---|---|
| `fastmcp` | `>=2.0,<3` | **4.x 依赖 `starlette>=1.0.1`（移除 `on_startup`），与 FastAPI 的 `starlette<0.51` 硬冲突，装上后 data-service 直接起不来** |
| `fastapi` | `>=0.115,<0.126` | 与上一条互锁 |
| `starlette` | `>=0.40,<0.51` | 与上一条互锁 |
| `httpx` | `>=0.27,<1` | `search_products` 工具回调 web BFF 用（fastmcp 4.x 才会拉 httpx2，2.x 用 httpx） |
| `yfinance` | `>=0.2` | M6/P5 美股 provider（`openbb_provider.py` 免费档后端）；此前漏写，全新环境会缺 |

其余直接依赖：`akshare>=1.16`、`pypinyin>=0.53`、`apscheduler>=3.10`、`requests>=2.32,<3`、`pandas>=1.3`。
（`providers` / `hotspot` / `research` 直接 import 这些包，此前靠 akshare 传递依赖，P6 重建 venv 时暴露。）

### C-3 港股（2026-09-20 实测，不得回退）

- **东财 CDN 节点可用性因网络而异，禁止依赖单一节点**：实测 `72.push2.eastmoney.com`（akshare `stock_hk_spot_em` **硬编码**的节点）返回 `RemoteDisconnected`，而 `push2delay.eastmoney.com` / `7.push2.eastmoney.com` 返回 200 真实数据（`89988 阿里巴巴-WR`）。故 `hk_provider` **不套用 akshare 封装**，改为直连东财 + 多 host 按序降级（`HK_SPOT_HOSTS` = push2 / push2delay / 7.push2 / 72.push2；`HK_HIST_HOSTS` = push2his / 33.push2his / 63.push2his），走同一源族限速器 + 看门狗，全失败才抛 `ProviderError`。
  **同理适用于任何复用 akshare 封装的路径**：akshare 硬编码单节点 = 绕过本项目的多 host 降级能力。
- **港股代码为 5 位数字，与 A 股/基金的 6 位不同 → 腾讯符号映射必须按类型显式分派**：`_hk_symbol(code)`（5 位补零 → `hkXXXXX`；非数字或 >5 位返回 `None`）与 `_symbol_for(type_, code)`（`type_=="hk"` 走港股映射，否则走原 `_symbol`）。**禁止复用 A 股的 `_symbol`**——其前缀规则会把 `00700` 误判为 `sz00700`、`89988` 误判为 `sh89988`。**禁止改用"按长度猜类型"的隐式约定**（与 CR-17 同类反模式）。
- **东财港股列表必须分页，且列表接口禁止用于行情路径**：
  - 东财 `clist/get` 对港股**忽略大分页参数**：`pz` 给 100/1000/10000 均只返回 **100 条**；港股 `total≈4707` → 必须按 `total` 分页遍历（约 48 页）。
  - **接口分工红线**：单股行情用 `/api/qt/stock/get`（1 次请求）、批量行情用 `/api/qt/ulist.np/get`（1 次请求）、**全量列表才用 `clist/get` 分页**。**行情路径严禁触发列表分页**——早期版本让 `get_quote` 复用列表快照，实测查询单个港股需拉取 4700 条、耗时约 4 分钟，属设计缺陷（已修正，并由单测 `test_quote_does_not_trigger_list_paging` 锁定）。
  - **同步耗时与其对 BFF 超时的要求**：48 页经源族限速器（最小间隔 5s）→ 实测约 **236s**。故 BFF `lib/sync.ts` 拉取 `/products` 的超时由 180s 放宽至 **600s**（`/api/sync` 的 `maxDuration=800` 覆盖）；**同步期间的其它东财请求会排队**（共享源族额度），属 R15 有意设计，凌晨低峰执行影响可控。

### C-4 主备源矩阵（各类别实测结论）

| 数据类别 | 主源 | 备源（已实测） |
|---|---|---|
| A股/场内基金 行情 | 东财 ulist | 腾讯 `qt.gtimg.cn`（✅ 实测 200） |
| A股/场内基金 日K | 东财 push2his | 腾讯 `web.ifzq.gtimg.cn/fqkline`（✅ 43 行）；场内基金再备新浪 `fund_etf_hist_sina`（✅ 3584 行） |
| 板块成分（概念/行业） | 东财 cons_em | **新浪 `stock_sector_spot/detail`（✅ 实测：84 行业+175 概念，成分股可得）**；同花顺成分接口当前 akshare 版本不存在 |
| 财经新闻 | Tavily（key 已配置 ✅） | 财联社电报（✅）/ 东财快讯 |
| 可转债 行情 | 东财 | **新浪 `bond_zh_hs_cov_spot`**（详见 §C-1） |
| 可转债 日K | 东财 | **确认无可用备源** → 限流时降级为显式缺口说明（R10 语义：可用或显式降级，均属正确行为） |
| 可转债 列表 | 东财 `bond_zh_cov`（1052 只，含未上市） | **新浪 cov_spot（约 320 只在交易标的）**——覆盖度较低属降级可用 |
| 场外基金净值 | 东财天天基金（独立域名族，限流期间实测可用） | 待补（蛋卷/新浪需验证） |
| 加密 | CoinGecko（R12 代理优先） | 待补（OKX/币安经代理） |
| 港股 行情 | 东财 `push2` 系（`clist/get` 多 host 降级） | **腾讯 `qt.gtimg.cn`（✅ 2026-09-20 实测：`hk00700` HTTP 200 / 78 字段，字段位置与 A 股一致）**——`tencent_provider` 注册为 hk 备源（position=1） |
| 港股 日K | 东财 `push2his` 系（多 host 降级） | **腾讯 `web.ifzq.gtimg.cn/fqkline`（✅ 2026-09-20 实测：`hk00700,day,...` 返回 day 数组，行格式与 A 股同，`qfqday or day` 回退已覆盖）**；复权口径与主源一致（均前复权） |
| 港股 列表 | 东财 `clist/get`（多 host 降级） | **确认无可用备源**（腾讯无全量港股列表接口）→ 显式降级：已有数据保留（C1 空载荷保护 + 降级缩水保护）+ 同步显式报错（R10 语义） |

---

## D. 部署与容器化（P7 落地定稿，不得回退）

| 约束 | 内容 |
|---|---|
| **Python 版本必须与锁文件一致** | 镜像用 `python:3.12-slim`（对齐开发 venv）。实测教训：曾用 Windows/py3.12 venv 的 freeze 结果去装 3.11 镜像 → `numpy==2.5.3` 要求 Python ≥3.12 → 安装失败。**规则：`requirements-lock.txt` 必须在目标镜像内生成**（`docker run <image> pip install -r requirements.txt && pip freeze`），且不得混入 Windows 专属包（pywin32 等） |
| **web 镜像的 base 阶段禁止设 `NODE_ENV=production`** | 会使 `npm ci` 跳过 devDependencies，而 `@tailwindcss/postcss`（构建必需）与 `prisma` CLI（运行时 `migrate deploy` 必需）都是 devDependency → 构建/启动失败。`NODE_ENV` 只在 runner 阶段设置 |
| **基础镜像走国内镜像源** | docker.io 直连在当前网络被拦截（auth 502）→ 基础镜像走 `docker.m.daocloud.io` 前缀，经 `NODE_IMAGE` / `PY_IMAGE` build args 可覆盖；npm 走 npmmirror + 长超时；pip 走阿里源 + `--timeout 120 --retries 10` |
| **数据卷必须 rw 挂载进 data-service** | 备份用只读 URI 读取，恢复需写入；**恢复前必须 `docker compose stop web`** |
| **全新数据卷只有表结构、无业务数据** | 首次部署需 `POST /api/sync` 同步产品主数据（冒烟脚本会区分"未初始化"与"检索故障"） |
| **启动顺序** | `data-service depends_on web: service_healthy`（其启动补跑与落库回调需要 web 就绪）；web 不反向依赖（避免依赖环） |
| **容器内服务互访接线** | data-service 容器须设 `WEB_BASE_URL=http://web:3000`（hotspot ingest / research ingest / vendor_adapter 回读 web `/api/kline` 三处共用；默认 `http://localhost:3000` 在容器内指向自身必挂）；web 容器须设 `DATA_SERVICE_URL=http://data-service:8000`。**已知小缺陷：回调变量名不统一**（`WEB_BASE_URL`（hotspot/research）vs `WEB_API_BASE`（mcp_server search 回调））——compose 两值同设 + `mcp_server` 读 `WEB_BASE_URL` 兜底 |
| **healthcheck 约束** | slim 镜像无 curl——web 用 `node -e`、data-service 用 `python -c urllib` 探活 |
| **web 镜像需补装 `openssl` + `ca-certificates`** | 骨架验证实测：Prisma 引擎在 slim 镜像的 openssl 探测告警，补装即消 |
| **`.dockerignore` 红线** | 必须排除 `.env`、`prisma/dev.db`、`node_modules`、`.next`、`.venv*`、`__pycache__`；**必须包含 `skills/`、`mcp.json`**（P6 产物随镜像分发） |
| **MCP server 容器化策略** | **默认不进容器**（宿主侧按需 `python -m app.mcp_server --http` 即可）；如需容器化用 compose profile `mcp`——**容器内必须绑 `0.0.0.0`**（绑 127.0.0.1 时宿主机经端口映射也访问不到），宿主机映射 `127.0.0.1:8765:8765` 仅本机暴露 |
| **镜像体积（2026-09-14 实测闭环）** | `docker images` 口径 **1.62GB → 1.25GB（-23%）**；容器内实际占用 **1.29GB → 0.89GB**；精确 `.Size`（压缩后）279MB。**重要认知：devDependencies 不是体积大头**——裁剪后 `node_modules` 仍 833MB，主体是运行时依赖（`@next` SWC 273MB、`next` 156MB、`@prisma` 112MB、`prisma` CLI 67MB、`echarts` 62MB、`@img/sharp` 46MB）；"预期 ~0.9GB"的原估算口径有误（0.89GB 是容器内占用而非 `docker images` 口径） |
| **可选进一步瘦身（未做，评估记录）** | ① 把 `prisma migrate deploy` 拆成独立 one-shot 服务，web 镜像可再省 67MB；② 项目未使用 `next/image`，`@img/sharp` 46MB 理论上可去（需验证 `next start` 不强制加载）；③ musl/wasm 平台变体已在本轮裁剪（省 165MB） |
| **C31 进程降权尚未验证** | 见 §A 第四批 C31 |
