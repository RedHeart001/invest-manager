# 待办项落地方案评估（2026-11-01）

> **这是什么**：2026-11-01 主人提出「六里那 8 项我还是有想法想做」后，逐项做的可行性评估与落地方案。
> **不是需求文档**——需求口径仍在 [PLAN.md](PLAN.md)；**不是账本**——状态仍归 [FIX-LEDGER.md](FIX-LEDGER.md)。
> 本文件只回答三件事：**能不能做、怎么落才不出事、代价是什么。**
>
> **写它时（2026-11-01 12:5x）的现场基线**：web 3000 PID 10728／ds 8000 PID 22632；
> `legStaleness=fresh`；11-01 02:02 自然轮六类 completed；CR10-6 已实机验证通过（见 §0）。
> 所有行号与常量值都是写这一版时现查的，**引用前请重新现查**（本项目纪律：可复算数字必须带出处）。

---

## 0. 前置：CR10-6 已实机验证通过（不属本文件范围，但影响基线）

腾讯备源日 K 的窄窗口漏当日根，已在**真实上游**上验证修复：
窄窗 `20261025..20261031` / 宽窗 `20260901..20261031` / 无窗 三种入参，最后一根**全部一致**
（2026-11-01 是周日，最近交易日 10-30）。修复前窄窗会漏掉它。

⇒ **CR10-6 全链路闭合**：根因 → 代码 → 离线套件 20/20 → 两把钻 → 闸2 重采 → 真实上游。

---

## 1. 总览：8 项的可行性与建议

| # | 项 | 可行性 | 建议 | 与账本现值的关系 |
|---|---|---|---|---|
| 1 | Watchlist 清单页 | ★★★★★ | **做**（P1） | 账本 10-22 记「已拍板＝不做」，**主人 11-01 改口要做** ⇒ 需在 PLAN 加需求行 |
| 2 | 备份 restore 人工验证 | ★★★★★ | **✅ 已完成（2026-11-01 22:2x）** | 落成 `test-script/restore-verify.py`，首跑 10/10，见 §2.2 落地记录 |
| 3 | G7 完整身份鉴权 | ★★★☆☆ | **做最小版**（P4） | 账本 10-18 定档「B4 维持不动」⇒ 需新口径 |
| 4 | 美股全量「乙」913 页 | ★★★★☆ | **可做，代价明确**（P6） | 账本 10-18 定档「甲+」⇒ 改档需主人字 |
| 5 | 详情页扩展字段 | ★★☆☆☆（分层） | **先做 PE 分位**（P5） | PLAN 定档「给了数据源才谈」 |
| 6 | native TradingAgents | ★★☆☆☆ | **不建议** | 已有 B 计划替代 |
| 7 | 热点「去分析」真解读 | ★★★★☆ | **做，但换形态**（P3） | 账本未立项 ⇒ 需立项 |
| 8 | MCP 默认不启用 | — | **保持不动** | 刻意设计 |

---

## 2. 逐项落地方案

### 2.1 Watchlist 清单页（P1，推荐首先做）

#### 现状（现查）

| 组件 | 状态 |
|---|---|
| `web/app/api/watchlist/route.ts` | ✅ GET/POST/DELETE 全在 |
| `web/components/WatchButton.tsx`（详情页按钮） | ✅ 在 |
| Prisma `Watchlist` 表 | ✅ 在，且被 `web/lib/search.ts` 读用于排序加权 |
| **列表页** | ❌ **不存在**（`web/app` 下只有 chat/page/product/search 四个 page.tsx） |

⇒ **能存不能看**，这是功能闭环缺口。

#### ⚠️ 我第一版方案的错误（已修正）

我原先说「后端零改动」——**这是错的**。核实后发现两件事：

**错误一：BFF 没有批量取价路由**

```
web/app/api/ 下只有 quote/route.ts（单数，接受单个 code）
web/lib/data-service.ts:139  有 dsGetQuotes(type, codes[]) —— 能批量
但没有任何 BFF 路由把它暴露出去
```

⇒ 清单页要显示现价，**要么加一个 `/api/quotes` 路由**，要么 N 次调 `/api/quote`。

**错误二：跨 type 的分组成本被忽略**

自选可能跨 stock/fund/bond/crypto/hk/us 六类，而 ds 的 `/quotes` **一次只接受一个 type**。
10 个自选跨 3 类 ⇒ 3 次请求；跨 6 类 ⇒ 6 次。

#### 修正后的落地方案

```
第 1 步（后端，约 40 行）
  新增 web/app/api/quotes/route.ts
    ├─ 白名单校验 type + codes（复用 lib/validate.ts 的 CODE_SET）
    ├─ 调 lib/data-service.ts 的 dsGetQuotes（已存在，:139）
    └─ 返回 { quotes, usesEastmoney }

第 2 步（页面，约 120 行）
  web/app/watchlist/page.tsx —— 用 Server Component
    ├─ prisma.watchlist.findMany()
    ├─ 按 type 分组 → 每组一次 dsGetQuotes
    ├─ 渲染：分组卡片，每组内是「代码 / 名称 / 现价 / 涨跌幅」
    └─ 空态：「还没有自选，去搜索页添加」

第 3 步（入口）
  导航加一项（需先读现有导航组件，不能凭空加）
```

#### 为什么选 Server Component 而不是 Client Component

**这不只是风格选择**——`C32` 要求「前端在途请求必须可取消、过期响应不得写入状态」。
Server Component 在服务端渲染完才下发，**天然没有"在途请求"**，直接规避了 C32 的全部约束。

若做成 Client Component（比如要实时刷新），就得实现 `AbortController` + 请求序号守卫，
成本翻倍且要过 C32 的验收。

⇒ **清单页不需要实时性，选 Server Component 是正确解，不是偷懒。**

#### 代价与风险

| 项 | 值 |
|---|---|
| 预估工时 | 2–3 小时 |
| 新增文件 | `web/app/api/quotes/route.ts`、`web/app/watchlist/page.tsx` |
| 改动文件 | 导航组件（1 处） |
| 碰 `DS_RESPONSE_FILES`？ | **否** ⇒ 不触发闸2 重采 |
| 测试 | vitest 加 BFF 路由守卫测试（跨站 403、非法 type 400）；集成测试可选 |

#### ⚠️ 与账本的口径冲突（必须先解决）

`FIX-LEDGER` 10-22 记：**`Watchlist` 已拍板＝不做**（主人的字）。
现在主人要做 ⇒ **这不算"打脸"，是需求变更**，但按项目纪律必须：
1. 在 `PLAN.md` 加一条需求行（M 编号或 R 编号），注明「2026-11-01 主人改口」；
2. `FIX-LEDGER` 那行不改（只增不改），另加一行现值更正指向新需求行。

**不能跳过这一步直接写代码**——否则账本与代码失同步。

---

### 2.2 备份 restore 人工验证（P2，30 分钟）

#### 现状（现查）

```
data-service/scripts/backup_db.py
  :75  def restore(backup_file: str, target: str) -> bool
       ├─ :84  _connect_ro(backup_file) + PRAGMA integrity_check
       ├─ :90  校验有表
       └─ 失败自动回滚
  tests/test_backup_db.py  19/19 在册
```

⇒ 机制齐全、测试齐全，**但从没在真实库上人工跑过一次**。

#### ⚠️ 我第一版方案的错误（已修正）

我原先写的是隐患版：

```bash
python -m scripts.backup_db --restore backups/xxx.db --source /tmp/restore-test.db
```

**参数名极具误导性**：`--source` 在这里是「恢复到哪个路径」，不是「来源」。
看 `main()`：

```python
ap.add_argument("--source", default=DEFAULT_DB)   # 默认 = web/prisma/dev.db
ap.add_argument("--restore", metavar="FILE")
...
if args.restore: return restore(args.restore, args.source)
```

⇒ **忘了带 `--source` 就会直接覆盖生产库** `web/prisma/dev.db`。

#### 修正后的落地方案（三段式，每步可回退）

```bash
# ① 保险：先复制一份生产库（放 runtime/，已 gitignore）
cp web/prisma/dev.db data-service/runtime/restore-guard-$(date +%Y%m%d-%H%M%S).db

# ② 恢复到临时路径（--source 显式指定，绝不省略）
python -m scripts.backup_db \
  --restore data-service/runtime/<最新备份>.db \
  --source /tmp/restore-test.db

# ③ 校验恢复出来的库
python -c "import sqlite3;c=sqlite3.connect('/tmp/restore-test.db');\
print(c.execute('select type,count(*) from Product group by type').fetchall())"

# ④ 通过后删临时库，guard 副本保留 3 天
```

#### 建议写成可复用件

按项目纪律「可复用件入册」（`test-script/` 只放只读观测件），本步应落成
`test-script/restore-verify.py`：参数化备份文件、自动建 guard、校验后输出对照表。
**下次再验不用重新推理。**

#### ✅ 落地记录（2026-11-01 22:2x，已完成）

已按上节落成 `test-script/restore-verify.py`（并在 `test-script/README.md` 入册）。
首跑 **10/10 通过**，两钻精确命中：

- 摘掉恢复产物 ⇒ `②` 红；并钻出真缺陷——旧版会崩在 `sqlite3.connect`，已修成干净失败。
- 改一个表的计数 ⇒ `③ 逐表行数相同` 红（`ChatMessage: 44 vs 45`），仅此一条。

**关键设计**：目标路径 `tempfile.mkdtemp()` 写死在脚本里，人敲不到 `--source` 那个坑；
生产库 md5 前后一致是断言之一（`④`），不是"小心一点"。详见 [PROGRESS.md](PROGRESS.md)。

#### 代价与风险

| 项 | 值 |
|---|---|
| 预估工时 | 30 分钟（脚本化后 10 分钟/次） |
| 风险 | **低**——只要 `--source` 指向 `/tmp` |
| 唯一风险点 | 参数省略导致覆盖生产库 ⇒ 用 guard 副本兜住 |

---

### 2.3 G7 完整身份鉴权（P4，最小版）

#### 现状（现查）

| 端点 | 保护措施 | ds 调用时带 token？ |
|---|---|---|
| `/api/hotspots/ingest` | `x-ingest-token` 校验（配了才校验） | ✅ 带 |
| `/api/research/ingest` | 同上 | ✅ 带 |
| `/api/sync` | 仅 `checkRequestOrigin`（防浏览器跨站，不防 curl） | ❌ **不带** |
| `/api/market/refresh` | 同上 | ❌ **不带** |
| `/api/hotspots/run` | 同上 | ❌ **不带** |
| `/api/research/start` | 同上 | ❌ **不带** |

#### ⚠️ 我第一版方案的错误（已修正）

我原说「三处同改」，但**没说清漏了会怎样**：

**如果直接给 `/api/sync` 加 `requireToken`：**
- ds 的 02:00 同步调度腿调它会 **401**
- ⇒ **整夜不跑同步**，第二天 `legStaleness=missed-today`
- 而这正是 10-31 刚踩过的坑（虽然那次是进程不在场）

#### 修正后的方案：新增独立 `WRITE_TOKEN`，初始为空

```
不改 INGEST_TOKEN 的语义（它管服务间回调）
新增 env: WRITE_TOKEN（初始不设 = 不校验）

web/lib/guard.ts（新文件）
  export function requireWriteToken(req): string | null {
    const expected = process.env.WRITE_TOKEN
    if (!expected) return null          // 未配置 ⇒ 放行（本机默认态）
    const got = req.headers.get('authorization')?.replace(/^Bearer /,'')
              ?? req.headers.get('x-write-token')
    return got === expected ? null : 'unauthorized'
  }
```

应用到 4 个写端点，放在 `checkRequestOrigin` **之后**。

#### 为什么这样最省事

| 阶段 | `.env` 里 `WRITE_TOKEN` | 行为 | 需改调用方？ |
|---|---|---|---|
| 现在（本机） | 不设 | 全部放行 | **否** |
| 上云前 | 设一个值 | 全部校验 | 是（ds 4 处） |

⇒ **零破坏上线**：现在合并不会断任何腿；等到真要上云，把环境变量一填、ds 四处加头，一次性生效。

#### ⚠️ 但要说清一个真相

本机部署时所有请求都来自 `127.0.0.1`，**加 token 在本机的安全收益接近零**——
本机其他进程本来就能读 `.env`。它的真正价值是「上云后无痛生效」。

⇒ **这不是"安全加固"，是"为将来铺路"。** 别把它记成"已解决安全问题"。

#### 完整版（OIDC / 反代 Basic Auth）

留到真要对外暴露时做。方案：BFF 边缘加统一鉴权中间件 + 保留 `x-ingest-token` 作服务间凭据
+ 生产环境缺配置 fail-closed + 按调用方限流。

| 项 | 值 |
|---|---|
| 预估工时（最小版） | 3–4 小时含测试 |
| 预估工时（完整版） | 2–3 天 |
| 碰 `DS_RESPONSE_FILES`？ | 否 |

#### ✅ 落地记录（2026-11-02 00:5x，最小版已完成）

主人的字（11-02 盘点轮四答）＝「深入分析p3+p4」⇒ 最小版本轮落地。**实际落点比上面方案窄一处，理由是现查的**：
方案原写"应用到 4 个写端点"，逐个查调用方＝ds 只调 `/api/sync`（`sync_scheduler.py:445`）与
`/api/market/refresh?type=all`（`:89/:320`）两个；`/api/hotspots/run`（`HotspotFeed.tsx:187` 手动按钮）与
`/api/research/start`（详情页按钮＋聊天 L2）都是**浏览器端调用方**——浏览器持不了 secret，挂上守卫＝设
`WRITE_TOKEN` 那一刻这两个按钮死 ⇒ **排除**（上表把 hotspots/run 记在"ds 调用"一列是误记，实况 ds 从不调它）。
落地＝`web/lib/guard.ts` 的 `requireWriteToken`（未设/空串 ⇒ 放行＝本机零破坏；`Authorization: Bearer` 或
`x-write-token`），挂两条路由、位置在 `checkRequestOrigin` 之后、拒绝回 401；**ds 侧零改动**（上云前设值时在
`sync_scheduler.py` 两处调用点同批加头）。测＝`web/lib/guard.test.ts` **11 条**（三态 7＋接线 2＋排除面牙齿 2），
C34 钻＝摘 sync 接线 ⇒ **恰 1 红**、复原后全绿。

---

### 2.4 美股全量「乙」913 页（P6）

#### ⚠️ 我第一版方案的三个硬错误（已修正）

**错误一：只改 `US_LIST_PAGES` 无效**

现查 `akshare_provider.py`：

```
:218  US_LIST_PAGE_CEILING = 50          ← 代码常量，会把你改的 913 夹回 50
:221  US_LIST_WHOLE_TIMEOUT_S = 150.0    ← 看门狗预算
:219  US_LIST_PAGE_INTERVAL_S = 0.5      ← 页间自睡
:229-230  env_capacity("US_LIST_PAGES", ...), US_LIST_PAGE_CEILING
```

看 `:229-230`：`_us_list_pages()` 取 `min(env, CEILING)`
⇒ **只改 `.env` 里的 `US_LIST_PAGES=913`，实际仍是 50。**

**错误二：时间算错了**

我原先写「913 页 × 0.5s ≈ 8 分钟」。但账本 10-18 记过整条名单是**一枚** `_ak_request`，
页间 0.5s 自睡**之外**还有每页的实际请求耗时。实测基线：50 页 → `tookMs=50405`（50 秒）
⇒ **约 1 秒/页** ⇒ 913 页 ≈ **15 分钟**，不是 8 分钟。

**错误三：`intentionalSubset` 语义会翻转**

当前 50 页是「主动停」⇒ provider 声明 `intentionalSubset: true` ⇒ web 的缩水闸放行。
改成 913 若真拿全了，就**不能再声明子集**（否则放行一次"看起来缩水实则全量"的替换）。

#### 修正后的方案

```python
# data-service/app/providers/akshare_provider.py
US_LIST_PAGE_CEILING = 950        # :218  50 → 950
US_LIST_WHOLE_TIMEOUT_S = 900.0   # :221  150 → 900（15 分钟 + 余量）

# data-service/.env
US_LIST_PAGES=913

# 重启 ds（归主人）
```

#### 验收判据（三条，缺一不可）

```
① POST :8000/sync/run 后读 /sync/status 的 results[us].note
   ⇒ 应含「只取前排 913 页」，且不再有「intentionalSubset」为 true
② 只读 SQL：select count(*) from Product where type='us'  ⇒ 期望 ≈ 18000（不是 505）
③ 同轮刷新腿总耗时 < callbackTimeoutS(2400s)；当前全类型已用 ~18 分钟
   ⇒ 加 15 分钟 = 33 分钟，踩线但不超——要盯
```

#### 代价与风险

| 项 | 值 |
|---|---|
| 预估工时 | 1 小时改码 + 一次夜间验证 |
| 副作用 1 | `akshare-obs` 族被独占 15 分钟 ⇒ 基金定期报告等同族请求排队 |
| 副作用 2 | DB 体积 +约 15MB |
| 副作用 3 | 夜间刷新腿逼近 40 分钟预算上限 |
| 回滚 | 改回三个常量 + 重启即可 |

**建议**：先手动 `POST :8000/sync/run` 验证一次，不要直接等 02:00 自然轮。

---

### 2.5 详情页扩展字段（P5，分层做）

#### ⚠️ 我第一版方案的问题：把两层依赖混在一张表

重新梳理依赖深度：

| 字段 | 数据是否已有 | 要动的层 | 成本 |
|---|---|---|---|
| **股票 PE 历史分位** | ✅ 完全够（`peTtm` 在 quote 里、历史价在 `KlineDaily`） | **只动 web** | **最小** |
| 场内基金 跟踪指数/规模/费率 | ⚠️ 要新取（东财 `fund_etf_spot_em`） | provider + ds 端点 + BFF + 页面 | 3–4 倍 |
| 场外基金 经理/风险等级 | ❌ 要爬天天基金详情页 | 同上 + 爬虫 | 最高 |
| 加密 市值排名/24h 量 | ⚠️ CoinGecko 免费档有限 | 需先评估额度 | 未知 |
| 基金 分红节点 | ❌ 数据源给不了（只有定期报告清单） | — | 不做 |

#### 修正后的顺序：先做股票 PE 分位

**理由**（这是选型的依据，不是偏好）：
1. 数据完全够用，不需要新 provider 方法
2. **只动 web 侧，不碰 `DS_RESPONSE_FILES`** ⇒ 不触发闸2 重采
3. 纯展示增强，不改任何既有契约

```
第 1 步（web/lib/metrics.ts，新文件）
  computePePercentile(peTtm, history)  —— 用 KlineDaily 的历史 close + 当前 peTtm 反推历史 pe
  注意：这是近似（用价格比反推 PE），要在一行注释里写清口径

第 2 步（ProductCharts 或详情页槽位）
  渲染「PE 分位 23%（近 3 年）」，带一行 tooltip 说明近似口径
```

**⚠️ 必须诚实标注**：这不是真 PE 历史分位——那需要历史 `peTtm` 序列，库里没有。
用「当前 PE × (历史价/当前价)」反推是对**盈利不变**的假设，财报季会失真。
要么如实标「近似值」，要么先补历史 PE 采集（成本高得多）。

#### 代价与风险

| 项 | 值 |
|---|---|
| 预估工时（PE 分位） | 1 天（含口径说明与测试） |
| 风险 | 中——近似口径若标不清会误导使用者 |
| 场内基金那个 | 2 天，另立项 |

---

### 2.6 native TradingAgents（不建议）

#### 不建议的三条理由

1. **架构不匹配**：现有是「web 唯一写库方、ds 无状态」。native TradingAgents 要 Python 侧持有会话状态。
2. **依赖重量**：账上记过 torch ⇒ 镜像 +2GB。
3. **收益不明确**：B 计划 `custom-multichar` 已跑通多角色分析（p4 23/23、p5 18/21/22 门禁在册）。

#### 替代方案

增强 `custom-multichar` 的角色提示词与工具调用，成本是其 1/10。
**要做的话先说明想要 native 的哪个能力**，再判断能不能在 custom 里实现。

---

### 2.7 热点「去分析」真解读（P3）

#### 现状

热点卡片的"去分析"只跳 `related[0]` 详情页的 `#research` 锚点，不调 Agent。

#### ⚠️ 我第一版方案的判断（这条我认为是对的，但要说清理由）

**不该在热点卡片上直接跑 Agent**：
- 一次 LLM 调用 10–30 秒
- 热点页是列表，N 张卡同时触发会打爆 LLM 配额
- 且 C32 要求在途请求可取消 ⇒ 每张卡都要 AbortController

#### 修正后的方案：复用 chat 链路

```
热点卡片 → 点击「深入分析」
  ↓
跳转 /chat?prompt=<热点标题+摘要>（URL 编码）
  ↓
chat 页读取 prompt 参数，预填输入框（不自动发送）
  ↓
用户确认后发送 → 走现有 chat 流式链路
```

优点：
- 零新增 LLM 调用点（复用 chat）
- 用户可看到流式输出、可追问
- 不触碰 C32（chat 页已有完整的请求管理）

**预估**：半天；**风险**：低（只是 URL 参数透传 + 预填）。

#### ✅ 定档记录（2026-11-02 00:4x，本轮落地）

主人的字（11-02 盘点轮四答）＝「深入分析p3+p4」⇒ 本项本轮落地。需求本体落 [PLAN.md](PLAN.md) **R19**；
CR8-2 旧拍板「接口与跳转一律不动」的**跳转半句被本定档推翻**（代码内旧注释同批更新为指向 R19，账上原句不回改）。
按钮字面「去分析 <标的>」一字不改；prompt 模板＝`热点深入分析：{title}\n{summary}`（措辞按 10-17 先例由 AI 拟、交回 before/after，要改字面请给一句字）。

---

### 2.8 MCP 默认不启用（保持不动）

#### 现状（现查 `web/mcp.json`）

```json
"servers": [
  { "name": "local-util", "enabled": true, ... },   ← 已启用（本地小工具，零依赖）
  { "name": "tavily",     "enabled": false, ... }   ← 禁用（要 API key + npx）
]
```

compose 里 `mcp` 服务在 `profiles: [mcp]`，默认不启动。

#### 为什么建议不动

「默认不启用」是**刻意设计**：MCP server 挂掉会拖慢对话链路（虽有降级，但有延迟）。
`local-util` 已启用 ⇒ 证明链路是通的。

**要做的话**：把 `tavily.enabled` 改 `true` + 确保 `TAVILY_API_KEY` 在环境里，10 分钟即可。
**随时可做，不需要提前规划。**

---

## 3. 推荐执行顺序

| 优先级 | 项 | 工时 | 前置条件 |
|---|---|---|---|
| **P1** | Watchlist 清单页 | 2–3h | **先在 PLAN 加需求行**（账本现值是「不做」） |
| **P2** | 备份 restore 验证 | 30min | **✅ 已完成（11-01 22:2x）** |
| **P3** | 热点「深入分析」→ 预填 chat | 半天 | 无 |
| **P4** | G7 最小版（`WRITE_TOKEN`，初始空） | 3–4h | 无破坏，可随时合 |
| **P5** | 股票 PE 分位（近似口径） | 1 天 | 需先说清「近似」二字是否可接受 |
| **P6** | 美股乙 913 页 | 1h + 夜间验证 | 三个常量同改；盯刷新腿预算 |
| — | native TradingAgents | — | 先说明想要哪个能力 |
| — | MCP 启用 | 10min | 随时 |

---

## 4. 需要主人先定的三件事

| # | 事项 | 选项 |
|---|---|---|
| 1 | Watchlist 与账本现值冲突（账本写「不做」） | 是「需求变更」还是「暂不做」？若做，我需在 PLAN 加需求行 |
| 2 | 股票 PE 分位是**近似值**（反推，非真实历史 PE） | 接受近似并标注，还是先补历史 PE 采集（成本高得多）？ |
| 3 | 美股乙的刷新腿会逼近 40 分钟预算上限 | 接受踩线，还是先把刷新腿拆成两段？ |

---

## 5. 本文件不做什么

- **不改代码**——只做评估与方案
- **不改账本**——`FIX-LEDGER` 的状态列仍以账本为准；本文件的建议要真正落地时，
  按「只增不改」在账本加现值更正行
- **不新增 CR 编号**——真要立项时按 `FIX-LEDGER` 状态卡的「下一可用编号」取（现值 **CR10-7**）
