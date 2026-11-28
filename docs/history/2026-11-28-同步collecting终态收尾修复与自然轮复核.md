# 2026-11-28 同步 collecting 终态收尾修复与自然轮复核

> **生命周期：前向执行方案＋当日事件报告。** 截至 2026-11-28 11:57，阶段 0～4 已完成：原 watcher 于 11:38:57 按原逻辑到 deadline 自然结束；CR10-51 代码、门禁、隔离与正式 DS 装载通过，11-28 持久化结果已在部署后派生收尾。**阶段 5 的下一次完整自然轮仍未发生。** 当前状态只认 [FIX-LEDGER](../FIX-LEDGER.md)。
>
> **一句话结论：11-28 自然轮未全过。** 六类名单均已到货，03:30 备份与独立恢复通过；但同步总状态停在 `collecting`，权威 watcher 未收尾，五类行情刷新为 `partial_failed`（fund 2、hk 10 个空批次）。W1～W4 的失败分支仍未取得自然证据。

## 1. 结论摘要

| 项目 | 2026-11-28 实际结果 | 判定 |
|---|---|---|
| 02:00 自然同步 | `daily` 已触发；五类名单在 02:09 收尾，美股任务随后完成 | 已发生 |
| 六类名单 | fund 28,452／stock 5,931／bond 1,068／crypto 249／hk 4,754／us 3,343 | 均到货，无类型错误 |
| 美股持久化任务 | 923/923 页、发布 3,343、02:26:39 完成刷新 | 完成 |
| 同步总状态 | `lastAttemptOutcome=collecting`，`retry=null` | **未收尾，缺陷** |
| 五类行情刷新 | `lastRefresh.outcome=partial_failed`；fund 2、hk 10 个空批次 | **部分失败** |
| 03:30 自然备份 | `daily/completed`，`dev-20261128-033000.db` 62,406,656 B | 通过 |
| 独立恢复 | `invest-e-restore-1128`，`passed=true`、`integrity=ok`、迁移 12 | 通过 |
| 权威 watcher | `naturalSync=null`、`allRequirementsMet=null`、`finishedAt=null` | 未收尾 |
| W1～W4 失败分支 | A 股 fail-closed、W3 补试、W4 失败展示、显式代理均未自然触发 | 未取证 |

**本轮不能记为“整体通过”，也不能把 `collecting` 说成“美股还在采集七小时”。** 美股任务早已完成；缺的是同步总状态的收尾。

## 2. 当日实际执行结果

### 2.1 同步时间线

| 时刻（+08:00） | 事件 |
|---|---|
| 02:00 | `daily` 自然轮启动 |
| 02:09:12 | 五类名单收尾；因美股仍在采集，同步 marker 写入 `outcome=collecting`、`ok=null`、`collectingTypes=["us"]` |
| 02:25:55 | 美股候选发布 3,343 只；快照 `20261128-020947-222d09` |
| 02:26:39 | 美股独立行情刷新完成，`refreshOutcome=completed` |
| 02:28 之后 | 冗余采集仍持续读到 `lastAttemptOutcome=collecting`，直到采集窗口结束 |
| 03:30:08 | 自然备份完成 |
| 03:30 之后 | watcher 自动完成独立恢复 |

五类名单结果：

| 类型 | 行数 | 结果 |
|---|---:|---|
| fund | 28,452 | 无 error |
| stock | 5,931 | 无 error、无降级 note |
| bond | 1,068 | 无 error |
| crypto | 249 | 无 error |
| hk | 4,754 | 无 error |
| us | 3,343 | 持久化任务完成并发布 |

数据库读数：Product `43,797`，`PRAGMA integrity_check=ok`，迁移 `12`。A 股带 `XD`/`DR` 名称 0、带 `-U`/`-W` 后缀 0。

### 2.2 美股任务

- 状态：`completed`。
- 页数：923/923，`pendingPages=0`。
- 声明总数：18,452；发布 3,343。
- 快照：`20261128-020947-222d09`。
- 发布：02:25:55；完成刷新：02:26:39。
- `refreshOutcome=completed`。

### 2.3 五类行情刷新

`/sync/status.lastRefresh` 的结局为 `partial_failed`：

| 类型 | 总数 | 更新 | 失败批次 | 备注 |
|---|---:|---:|---:|---|
| stock | 5,931 | 5,578 | 0 | 无失败批次 |
| fund | 28,452 | 24,460 | 2 | `failedEmpty=2` |
| bond | 1,068 | 312 | 0 | 无失败批次 |
| crypto | 249 | 249 | 0 | 无失败批次 |
| hk | 4,754 | 3,162 | 10 | `failedEmpty=10` |

这说明**名单同步**与**行情刷新**是两条腿：名单已到货，不代表每条行情都刷新成功。`partial_failed` 不触发 W3 的名单补试；W3 只对 `daily/partial_failed` 的名单失败类型生效，且排除 `us`。

### 2.4 备份与独立恢复

- 备份：`trigger=daily`、`outcome=completed`、`lastRun=2026-11-28T03:30:08+08:00`。
- 文件：`dev-20261128-033000.db`，62,406,656 B。
- SHA-256：`86beeda5e81673a4c094199dc9a00f70dff156c3eadee9311854093410657a7b`。
- 恢复卷：`invest-e-restore-1128`。
- 恢复结果：`passed=true`；源库与恢复库 `integrity=ok`、迁移 `12`、逐表数量一致。
- 恢复库表计数：Product 43,797、HotspotDigest 63、KlineDaily 1,851、ResearchReport 0、ChatSession 0、ChatMessage 0、Watchlist 0。
- 恢复卷按既有纪律保留，待明确确认后再清理。

### 2.5 监测与伴随进程

- watcher：`instrumentStatus=ok`、`errors=[]`、`consecutiveObservationErrors=0`；已记录 `naturalBackup` 与 `independentRestore`。
- watcher 未记录 `naturalSync`，因为 `collecting` 不在其终态集合内；它会在 12 小时上限附近按“未取得全部自然终态”结束，不是仪器连续错误。
- 冗余采集：01:50～05:08 共 100 个样本，96 个正常；02:00、03:00、04:00、05:00 四个整点深度样本为空，`probeError` 为空字符串。按命令构造判断是 `docker exec <container> -e ...` 的参数顺序问题，属采集器自身缺口，**不得据此判断业务失败**；该缺口待复核。
- 保活：06:01 按计划结束；窗口内未发现 watcher 或日志跟随被重启。
- 不重启 watcher 重验 11-28，不把部署后的派生状态补写成自然证据。

## 3. 根因

### 3.1 状态机缺一段收尾

1. 02:09 五类同步结束时，美股仍在持久化采集中，`sync_scheduler._execute` 正确写入 `outcome=collecting`。
2. `us_list_job` 在 02:26 完成发布与行情刷新，但它只更新自己的状态文件，没有回写 `sync-state.json`。
3. `sync_scheduler.status()` 读取 marker 时，也没有根据 `usListJob=completed` 推导收尾。
4. watcher 的终态集合不包含 `collecting`，于是永远等不到 `naturalSync`。

### 3.2 关键代码位置

- `data-service/app/sync_scheduler.py`：`_execute` 在五类收尾后写 `collecting`；`status()` 只读 marker 与内存态。
- `data-service/app/us_list_job.py`：`_refresh_once()` 完成后只更新美股任务状态。
- `test-script/watch-formal-e-natural.py`：`TERMINAL` 不含 `collecting`；`sync_candidate()` 只接受终态。

### 3.3 影响

- `/sync/status` 长期显示 `collecting`，读的人无法区分“美股还在采集”与“已经完成但未收尾”。
- watcher 无法封口，`allRequirementsMet` 永远为 `null`。
- Web 读取共享卷上的 marker，失败态判断也拿不到完整终态。
- **数据本身没有丢**：六类名单已入库，备份与恢复均通过。这是状态收尾缺陷，不是数据损坏。

### 3.4 当前 marker 的一个细节

当前 marker 中 `lastResult.results` 的 `us` 占位仍是 `collecting`，且 `snapshotId=null`；美股任务后来才生成 `20261128-020947-222d09`。因此收尾不能只靠 `snapshotId` 关联，必须同时使用“同一北京日、`trigger=daily`、`collecting`、美股 `completed`”这组条件；未来应在占位中保留尝试日或 generation，降低关联歧义。

## 4. W1～W4 证据分类

| 项 | 11-28 自然证据 | 结论 |
|---|---|---|
| W1 按源族出网 | crypto/hk 等海外源在空代理下成功 | 证明新码可直连运行；**未证明显式代理路径** |
| W2 A 股 fail-closed | stock 5,931、无 error、无降级 note | 东财成功，未触发 fail-closed；**不能据此说 W2 已验证** |
| W3 有界补试 | `retry=null`、`retryLastResult=null` | 本轮无 `daily/partial_failed` 名单失败，补试分支未触发 |
| W4 四态展示 | 页面 200，未出现失败/降级文案 | 本轮名单无失败，失败态未自然触发；不能据此说 W4 已验证 |

补充：`pinyin` 空值 249 全部是 crypto；11-27 备份中 crypto 也有 248 个空值，属既有形态，不列为 11-28 新回归。

## 5. 目标与非目标

### 目标

- 修复“美股完成后当日同步总状态永久停在 `collecting`”。
- 终态只在条件真正满足时推进；保留五类原结果和原始触发时刻。
- 覆盖竞态与重启，收尾幂等，不重复发布、不重复刷新、不生成补试。
- 让 watcher 能在真实完成后自然封口，而不是靠放宽终态集合。
- 保留五类行情 `partial_failed` 的独立可见性。

### 非目标

- 不人工重跑 11-28 同步，不使用 `force`。
- 不修改 11-26、11-27 原始失败记录。
- 不改调度时刻、代理配置和 W3 补试规则。
- 不把 `collecting` 直接加入成功终态来让 watcher 变绿。
- 不扩展热点、周末补跑、第二美股名单源。
- 本次产品代码预计只改 DS；Web 六档展示逻辑不扩大改造。
- fund/hk 行情部分失败是否新增页面提示，另列后续项，不在本次静默改变 W4 语义。

## 6. 执行阶段

### 阶段 0：冻结 11-28 现场

1. 保存 `sync-state.json` 原文及摘要。
2. 保存 `/sync/status` 完整读数：`collecting`、`usListJob=completed`、`lastRefresh=partial_failed`、`retry=null`。
3. 保存美股任务状态、发布与刷新时刻。
4. 保存五类名单与刷新结果。
5. 保存 watcher、冗余采集、保活日志和容器日志。
6. 保存备份文件、大小、SHA-256、恢复卷与逐表计数。

**防误验收闸门：** 正式部署前确认 11-28 原 watcher 已按原逻辑结束。若仍在运行，等它自然结束；不删除、不编辑其状态文件，不重启 watcher 重验 11-28，避免部署后的自动收尾被它捕获成“旧代码自然完成”。

### 阶段 1：实现幂等终态收尾

在 `sync_scheduler.py` 增加内部收尾函数，建议名 `_finalize_collecting_from_us()`，具体名称按现有约定确定。

收尾判据必须同时满足：

- `lastAttemptTrigger == "daily"`；
- `lastAttemptOutcome == "collecting"`；
- `lastAttemptDate` 与美股 `completedDate` 一致；
- 该日期仍是当前北京日期；
- 美股 `state=completed` 且 `refreshOutcome=completed`；
- 原五类结果没有其他类型错误；
- 写盘前重新读取并复核，避免覆盖新一轮状态。

以下情况保持原状：

- `waiting`、`refresh_pending`、`publish_unknown`；
- 美股未完成；
- 原轮次是 `partial_failed`、`inconclusive` 等其他结局；
- 日期不一致；
- W3 补试轮。

收尾数据规则：

- 保留 `lastAttemptTrigger=daily` 与原始尝试时刻；
- 五类 `results` 逐项保持不变；
- 只把 `us` 的 `collecting` 占位替换为真实发布结果；
- 移除已完成使命的 `collectingTypes`；
- 写入 `outcome=completed` 和相应的 `ok`；
- 增加审计字段：`finalizedFrom=collecting`、`finalizedAt`、`usSnapshotId`、`usCompletedAt`；
- 不伪造新的整轮网络耗时；
- 不创建 W3 补试；
- 不重新发布、不重新刷新、不产生网络请求；
- `lastRefresh.outcome=partial_failed` 原样保留。

三个幂等入口：

1. **美股完成回调**：`us_list_job` 持久化 `completed` 后通知 DS 收尾；调用时不得持有美股任务锁，采用局部导入避免循环依赖。
2. **主轮写入 `collecting` 后再检查一次**：防止美股恰好在读取状态与写 marker 之间完成。
3. **DS 启动恢复时检查一次**：如果进程重启前已完成美股但收尾写盘失败，启动后根据持久化状态补齐，不重跑任务。

收尾写盘失败只记录错误，不回滚美股完成状态，也不通过重复网络请求“补救”。

### 阶段 2：测试与取证器补强

DS 必测：

- `collecting → completed` 正常收尾；
- 重复收尾不重复写盘；
- 完成发生在主轮写状态前后的两种竞态；
- DS 重启后可以收尾；
- `waiting/refresh_pending/publish_unknown` 不提前完成；
- 原轮 `partial_failed` 不被美股完成覆盖；
- 跨日记录不被修改；
- `daily-retry` 不被修改；
- 收尾不调用采集、发布或刷新接口；
- 收尾不生成 `retry`；
- 五类 `lastRefresh.partial_failed` 保留。

watcher 补强：

- 保持 `collecting` 为非终态；
- 模拟“先 collecting、后 completed”，确认只有后者被封为自然终态；
- 从 `/sync/status` 顶层正确记录 `lastRefresh`，避免只记名单成功而丢失 fund/hk 行情缺口；
- 不放宽 `requirements_met()`。

Web 核对：

- 运行现有 W4、新鲜度和同步相关测试；
- 确认新增字段不破坏现有读取；
- 本轮没有自然失败，不得宣称 W4 失败展示获得自然证据。

### 阶段 3：离线门禁与隔离验收

1. DS 定向测试。
2. Web 定向测试与 `tsc --noEmit`。
3. `node scripts/gate.mjs --offline`。
4. docs 基线、断链与 selftest。
5. 构建新的 DS 候选镜像，使用独立标签。
6. 使用现有正式 Web 镜像进行隔离 Compose 验收。
7. 核对候选容器内确实包含新收尾函数与对应行为。

任何一项失败均不进入正式部署。不通过降低判据或修改原始样本换绿。

### 阶段 4：正式部署与回退

部署原则：

- 只重建 DS，Web 保持现有健康实例，避免无意义切换。
- 不动 `prisma-data`、`backups/`、调度配置和代理。
- 不执行同步、热点、备份或补试接口。
- 保留当前 DS 镜像 `w1w4-1127-accept`（`740c16a5981a`）作为第一回退点。

部署后硬判据：

- DS 容器 healthy，镜像 ID 与候选一致；
- 同步下一轮仍为当前注册时刻；
- 备份下一轮仍为 03:30；
- 热点下一轮仍为 11-30；
- 没有启动补跑、人工同步或新增网络采集；
- 数据库行数和六类摘要不因部署变化；
- `retry` 不因收尾被创建；
- 若启动恢复自动收尾了 11-28 状态，必须记录为“部署后依据既有持久化结果完成的派生收尾，不是新代码完整自然轮证据”。

回退：出现容器不健康、状态被错误改写、意外任务触发或数据库异常时，DS 切回 `740c16a5981a`；保留新状态文件和日志用于归因；不删除新旧卷、备份及恢复卷；不通过人工同步验证回退。

### 阶段 5：下一次自然轮验收

只有后续自然发生的 02:00 窗口才能验证完整链路：

1. `trigger=daily` 正常启动。
2. 美股未收尾时，状态可以是 `collecting`。
3. 美股完成后，同一日状态自动推进至 `completed`。
4. 收尾只发生一次，无重复发布和刷新。
5. 原五类结果、原始触发时刻保持不变。
6. `lastRefresh` 独立记录成功或部分失败。
7. `collecting/completed` 不产生 W3 补试。
8. 若自然出现 `daily/partial_failed`，仍按原规则：排除 `us`、30 分钟后最多一次、不改写原 `lastAttempt*`。
9. 03:30 备份和独立恢复继续通过。

全部成功也只证明本次实际走到的分支。A 股 fail-closed、W3 补试、W4 失败展示和显式代理路径，未触发就继续记为未获自然证据。

## 7. 终态迁移矩阵

| marker 现状 | 美股任务 | 动作 |
|---|---|---|
| `daily/collecting`，同日 | `completed` 且刷新完成 | 推进为 `completed`，保留五类结果 |
| `daily/collecting`，同日 | `waiting/refresh_pending/publish_unknown` | 保持 `collecting` |
| `daily/collecting`，同日 | 美股未完成 | 保持 `collecting` |
| `daily/partial_failed` | 任意 | 不覆盖；W3 规则照旧 |
| `daily/completed` | 任意 | 幂等空操作 |
| 跨日 `collecting` | 次日完成 | 不改写旧日记录 |
| `daily-retry` | 任意 | 不修改 |
| 写盘失败 | 已完成 | 记录错误；启动恢复再试，不回滚美股状态 |

## 8. 验收口径

| 层级 | 通过条件 |
|---|---|
| 代码 | 定向测试覆盖迁移、竞态、重启、跨日、补试隔离、无网络副作用 |
| 离线 | DS 定向＋Web 定向＋`gate.mjs --offline`＋docs 全过 |
| 隔离 | Compose 验收通过；候选容器内符号存在；不写正式卷 |
| 正式装载 | DS healthy、镜像 ID 正确、调度与数据库不变、无启动补跑 |
| 自然轮 | 真实 `collecting → completed`，只收尾一次，五类结果保留，`lastRefresh` 独立可见 |
| 备份 | 03:30 自然备份与独立恢复继续通过 |

**装载只证明代码可运行；自然轮才证明收尾分支。** 11-28 的备份通过不能替代同步总状态修复的验证。

## 9. 文档与归档

本文件归档后，回写：

- [FIX-LEDGER](../FIX-LEDGER.md)：新增 CR10-51 当前状态与证据链接；
- [PROGRESS](../PROGRESS.md)：更新当前里程碑与后续执行入口；
- [docs/README](../README.md)：更新 11-28 短摘要；
- [history/README](README.md)：加入本文件索引；
- [W1～W4 装载任务书](2026-11-27-W1-W4装载任务书.md)：补齐 11-28 自然窗口结果并标记生命周期；
- [自然轮验收清单](2026-11-27-自然轮验收与下次执行清单.md)：标记 B/C 已执行，勿再照跑。

后续自然轮结果继续追加到本文件，不新建机械状态快照。

## 10. 下一步计划（2026-11-28 12:10 记录）

> 计划本身不是证据。CR10-51 的现值、欠账与判据只认 [FIX-LEDGER](../FIX-LEDGER.md)；本节只排顺序与边界，完成后按实际读数回填，不预先写“已通过”。

### 10.1 优先级与依赖

| 优先级 | 任务 | 前置 | 完成判据 |
|---|---|---|---|
| P0 | 11-29 自然轮闭环 | 已装载 `cr1051-1128-accept`；watcher 已排 2026-11-28 23:00 起只读观察 `--date 2026-11-29` | 见 §10.2 九条；任一条只在实际走到时才记 |
| P1 | 交付收尾 | P0 出结果后统一回写 | 文档提交推送成功、`dev` 与 `origin/dev` 同步、三层口径明确 |
| P2 | W1～W4 证据分类 | 各自自然分支真实出现 | 只记实际触发到的分支，不人工制造失败 |
| P3 | 技术债与现场清理 | P0 通过、不再改代码 | 单独窗口评估，不与自然轮混在一晚 |

### 10.2 P0：11-29 自然轮判据

不改调度、不改配置、不人工触发同步／热点、不带 `force`。

1. `trigger=daily` 由 cron 自然启动，`lastAttemptDate=2026-11-29`。
2. 美股未收尾时允许 `collecting`，并确认这不是失败态。
3. 美股完成后同一北京日自动推进到 `completed`，且只推一次。
4. 无重复采集、重复发布、重复刷新；`usSnapshotId` 与美股任务一致。
5. 原五类结果与原始 `at` 保持不变；`collectingTypes` 在收尾后消失。
6. `lastRefresh` 独立给出成功或 `partial_failed`；fund／hk 若仍有空批次必须继续可见。
7. 不因 `collecting`／`completed` 生成 W3 补试（`retry=null`）。
8. 若自然出现 `daily/partial_failed`，按 W3 原规则：排除 `us`、30 分钟后最多一次、不改写原 `lastAttempt*`。
9. 03:30 备份与独立恢复继续通过，仪器 `ok`、连续错误 0。

判读纪律：`lastRun=null` 不等于没跑；重启后以 `lastResultFromDisk`／`lastRefreshFromWebProgress` 与美股任务 `state` 为准。错过窗口就如实记录，不人工补跑。

### 10.3 P1：交付收尾

1. 文档提交 `c2d3631` 因 TLS 握手失败尚未推送（本地 `dev` 领先 `origin/dev` 1 个提交，已跟踪变更 0）；网络恢复后只补推该提交，不制造空提交。
2. 按“11-28 原始结果／部署后派生收尾／11-29 自然结果”三段口径回写，不得合并成一段。
3. 在 P0 通过前保留 DS 回退点 `w1w4-1127-accept`＝`740c16a5981a`。
4. 只有 P0 九条真的通过，才把 CR10-51 写成“已修复并经自然轮验证”。

### 10.4 P2：W1～W4 证据分类

| 项 | 需要的自然分支 | 未出现时的处置 |
|---|---|---|
| W2 | A 股东财失败时拒绝新浪整类替换 | 继续记未获证据，不人为制造失败 |
| W3 | `daily/partial_failed` 后 30 分钟补一次、不带 `force`、排除 `us` | 只做离线与隔离验证，不排到线上 |
| W4 | 页面同时给出历史状态、数据时间与原因 | 不拿合成数据冒充自然证据 |
| W1 | 海外源显式代理路径 | 另开独立窗口：写 `.env`、重建容器、独立取证 |

长期不触发时可设计隔离故障注入验收，但必须标注“注入验收”，不能计入自然轮。

### 10.5 P3：技术债与现场

1. `_recover_last_refresh()` 在内存结果缺失时每次 `/sync/status` 都会只读访问 Web `/api/health`。功能正确但观测接口多一跳；等自然轮通过后再评估把刷新摘要直接持久化到 DS 侧。
2. 隔离项目 `invest-verify-16784` 的容器／卷、临时恢复卷与旧回退镜像保留；清理需明确确认后单独执行。
3. 未跟踪测试产物目录、`web/pnpm-lock.yaml`、`web/pnpm-workspace.yaml` 不清理、不忽略、不提交。

### 10.6 本轮明确不做

- 不改凌晨调度、不加星期门、不改备份频率。
- 不删除或编辑既有状态文件来“修正”历史读数。
- 不用部署后的派生收尾冒充新代码自然轮证据。

## 11. 实施进展（2026-11-28 11:57）

### 11.1 阶段 0：证据冻结

原始读数已复制到 `data-service/runtime/freeze-1128/`，关键哈希：

| 对象 | 大小 | SHA-256 |
|---|---:|---|
| `container-sync-state.json`（权威 marker，取自容器 `/data/runtime/sync-state.json`） | 1,159 B | `ebb1253786e07f0ef818a331d46a503d16becfc094ac5bfc8cb9a22164e32971` |
| `container-us-list-job-state.json` | 596 B | 见冻结目录 |
| `sync-status.json`（09:5x `/sync/status`） | 5,636 B | 见冻结目录 |
| `formal-e-natural-watch-20261128.json` | 1,620 B | `a67bb7fceee69a4cab1fa6fc2665dd280d4321bcb86671e0876c734ad2ef56d7` |
| `night-redundant-20261128.jsonl` | 140,854 B | `d4c8386898dfc17e9f11739def99cc72d78ba808d9ea15c7c005240f5f9c8dce` |
| `night-keepalive-20261128.jsonl` | 9,805 B | `173d98dfb61200bda59c0d1cbe81ef70c0d94adb8d992bbeab117c72f3cc0210` |
| `backups/dev-20261128-033000.db` | 62,406,656 B | `86beeda5e81673a4c094199dc9a00f70dff156c3eadee9311854093410657a7b` |

**现场修正**：宿主 `data-service/runtime/sync-state.json` 是 2026-11-13 的旧副本，不是 11-28 的 marker。正式实例的权威 marker 在 `invest-manager_prisma-data` 卷的 `/data/runtime/sync-state.json`（容器内 `SYNC_STATE_FILE`），冻结时已单独取回。后续复核与部署都以卷内文件为准。

### 11.2 阶段 1：代码

提交 `c9a516d`（已推 `origin/dev`）：

- `sync_scheduler.py`：新增幂等 `_finalize_collecting_from_us()`；三个入口为主轮写 marker 后复核、美股完成回调、DS 启动恢复。只替换 us 占位、移除 `collectingTypes`、写 `finalizedFrom/finalizedAt/usSnapshotId/usCompletedAt`，保留五类结果、原始 `at`、`lastAttemptTrigger=daily`、`retry` 与 `lastRefresh`。
- `us_list_job.py`：美股 `completed` 落盘后调用收尾通知；通知失败不回滚美股完成状态，导入放在函数内避免循环依赖。
- `watch-formal-e-natural.py`：记录 `/sync/status` 顶层 `lastRefresh`；用 `runId=daily-YYYY-MM-DD` 过滤上一轮遗留值；名单终态先到时，后续观察只补缺失的刷新证据。
- `sync_scheduler._refresh_leg()`：刷新结果增加 `runId` 与 `finishedAt`，供取证器区分本轮。
- 追加提交 `f88ebb3`：首次正式重启暴露 `lastRefresh` 仅住内存、重启后变 `null`。新增按精确 `runId` 从 Web 既有持久化 `refresh-progress` 只读恢复，标注 `recoveredFromWebProgress` 与 `lastRefreshFromWebProgress`；不改写原始进度文件、不改 marker、不刷新行情。

### 11.3 阶段 2：测试与门禁

| 项 | 读数 |
|---|---|
| 新增 `test_cr10_51_collecting_finalize.py` | 初版 **23/23**；加入重启恢复后 **26/26**：正常收尾、幂等、waiting/refresh_pending/publish_unknown、原轮失败、跨日、retry 保留、零网络、美股回调、主轮竞态、启动入口、精确 runId 恢复与错轮拒绝 |
| `test_cr9_sync_status.py` | 77/77 |
| `test_cr10_49_us_list_job.py` | 76/76 |
| `node scripts/gate.mjs --offline` | 初版全绿：42 套 1575/1575，回执 `gate1-99-1128-1018.out`；最终版全绿：tsc 0、Vitest 747/747、DS **42 套 1578/1578**、docs 全过，回执 `data-service/runtime/gate1-100-1128-1154.out` |

### 11.4 阶段 3：候选镜像与隔离验收

| 项 | 读数 |
|---|---|
| 候选 DS 镜像 | 初版 `abb3a3a37441`；重启恢复补丁后的正式候选 `invest-manager-data-service:cr1051-1128-accept`＝`41651e9cd259`（`sha256:41651e9cd259…efe5c`） |
| 容器内符号 | `_finalize_collecting_from_us` 3 处、`_notify_sync_collecting_finalized` 2 处 |
| 隔离 Compose | 初版与最终版均 **30/30 通过**；最终项目 `invest-verify-16784`，Web 端口 `33784`，回执 `verify-isolated-cr1051-1128-r2.log` |
| 候选容器内行为 | 临时 marker 从 `collecting` 收尾为 `completed`、`usSnapshotId=verify-snap`、`collectingTypes` 移除 |
| 现场 | 隔离容器、卷与临时恢复卷按既有纪律保留，未自动清理 |

**边界**：以上证明代码可运行、收尾分支在隔离环境成立；正式装载结果见 §11.5，仍不是下一次完整自然轮证据。

### 11.5 阶段 4：原 watcher 收尾与正式装载

| 项 | 实际结果 |
|---|---|
| 原 watcher | 11:38:57（北京时间）按原逻辑到 deadline，exit 2；`finishedAt=2026-11-28T03:38:57.439181+00:00`、`allRequirementsMet=false`、`instrumentStatus=ok`、连续错误 0。没有人工终止、重启或编辑状态文件 |
| 最终证据 | `freeze-1128/final-formal-e-natural-watch-20261128.json`，SHA-256 `863146af44ce29d7face7e4834e7883fe07ea3f7ae6f6afbe30fc08fa64e675d`；原 `.out` 与 resumed stdout 一并冻结 |
| 首次 DS 装载 | 11:47 后 DS healthy；启动恢复依据 11-28 持久化结果把 `collecting` 派生收尾为 `completed`，`finalizedAt=2026-11-28T11:47:21+08:00`，原始 `at=02:09:12` 与五类结果保留，`retry=null` |
| 首次装载发现 | DS 重启后内存 `lastRefresh` 丢失，`/sync/status.lastRefresh=null`；Web 卷内 `daily-2026-11-28` 原始进度仍完整保留 fund 2／hk 10 空批次。未手改生产状态，追加 `f88ebb3` 后重新走门禁与隔离 |
| 最终正式镜像 | DS `cr1051-1128-accept`＝`41651e9cd259` healthy；Web 保持 `w1w4-1127-accept`＝`8a8e397ef8a0` healthy，启动时刻未变 |
| 最终 `/sync/status` | 总状态派生 `completed`；`lastRefresh.outcome=partial_failed`、`weakTypes=[fund,hk]`、`runId=daily-2026-11-28`、`recoveredFromWebProgress=true`；原始逐类缺口继续可见 |
| 正式冒烟 | **8/8**，回执 `data-service/runtime/smoke-cr1051-1128.out`；数据库 `integrity=ok`、Product 43,797、迁移 12 |
| 回退 | DS `w1w4-1127-accept`＝`740c16a5981a` 保留；Web 未重建 |

**这是部署后依据既有持久化结果完成的派生收尾，不是新代码完整自然轮证据。** 11-28 的自然轮结论仍是“未全过”；只有下一次真实自然窗口通过阶段 5，才可写“已修复并经自然轮验证”。
