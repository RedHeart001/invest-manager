# test-script/

一次性/手工观测脚本（非自动化测试——自动化测试在 `data-service/tests/` 与 `web/lib/*.test.ts`）。

| 脚本 | 用途 | 来源 |
|---|---|---|
| `c0_sampler.py` | C0 实测采样器：每 60s 采 `/sync/status`（分类型耗时/令牌桶状态），同步完成后样本写入 `/tmp/c0_samples.json`。用于复测同步耗时基线 | 2026-09-25 C0 实测（CR7 批次 C） |
| `realtime_probe.py` | 实时源额度探针：对腾讯/新浪/东财/CoinGecko/Yahoo/币安各按固定间隔连发，输出成功率、P50/P95 耗时、字节数与解析形态。用于给「当日实时价格」轮询区定 N。**直连上游、不经 data-service ⇒ 不碰其令牌桶状态**；东财只发 10 次@6s 以落在自家 `rate_per_min=12` 护栏内 | 2026-09-27 批次七评估轮（CR9 追加九） |
| `window_lib.py` | 10-13 两窗的共享执行件：保险丝（东财 `cooldown>0` 即停、连续 2 发非 200 即停、硬上限）、节律（同发间隔下界）、`require_keys()` 严格取键（缺键把实际键面记进回执，**不回落到 note 文案**）、回执落盘。任务书 `:30` 那两条停手判据从此不靠到场记性。⚠️ `listening_endpoint()` 的 StartTime 自 10-13 下午起**显式取 ISO 格式**（`ToString('s')`）：裸取走控制台区域设置，中文机器上是 `2026年10月13日 13:08:33`，拿去和 ISO 的 mtime 比字符串会**恒判"装载成立"**＝那一枚牙齿此前是假绿 | 2026-10-12 丙窗口准备件（P2，主人「进版本管理，按建议方案执行」）；ISO 更正＝2026-10-13 下午＝CR9-93 |
| `window_preflight.py` | P1 前置读数器：**红线自证的读数对象在 10-13 下午换过一次**——旧那一位扫的是 `quote/realtime` 这个 token 在不在（＝"1a 还没开工"的证明），CR9-92 落码后它必然命中＝常红＝等于没有；现在扫的是红线本体：**实时链路文件的 URL 字面里有没有东财家族的 host**（只认 URL 字面，散文里提 `fund.eastmoney` 不算），并读 `/health` 的 `realtime-obs` 一族有没有出现 `acquire`。＋两侧监听与装载证据（源文件 mtime ⇔ 进程 StartTime，**两侧都归一到 ISO 才比大小**，治 CR9-24 那一形）＋东财桶/落盘那本账/`coveredDays`/备份一次看全。**只连 127.0.0.1，零上游**；`--selftest` 19 枚含"中文区域格式的 StartTime 不许静默比大小"这一枚 | 同上；红线档与装载面锁步＝2026-10-13 下午（主人「按这个来执行」＝CR9-93） |
| `window_a2.py` | P3 A2 采集器：`/quote/verified` 的机器可读三态 `verifyVerdict` 逐发落盘；④ 口径编码在码里（`no_second_source` 不进分母、含「主源不可用，已降级至」那几发摘出分母）；自带声明——读数是「主链共识参考值（含东财主源）」，**不等于 OPT-3 实时区源集** | 同上 |
| `window_a3.py` | P4 A3 采样器：逐类各 1 发取「此刻谁在供货」，档位按注册面字面判；每发前后读东财桶增量以证**这一发确实出网**（200 但零增量＝可能是 TTL 回声，标为无判别力）；us/crypto 不经东财桶，把"这一维无证据"一起写出来 | 同上 |
| `window_fill.py` | P5 第 50 项三格决策表回填件：读数只准往既定的格里填，填不进来的必须自己说为什么（格三 N **拒填**——`PROFILES` 无腾讯族 ⇒ 桶算术对象错了；④ 默认**拒填实时区那一格**，除非 `--realtime-object`） | 同上 |
| `window_bond_map.py` | 刀 C 探针：`ak.bond_zh_cov()` 那张转债表里**到底有没有"正股代码"列**——E-3 里 bond 那一刀做不做，就等这一个读数。默认只读盘上锁定版源码（零 HTTP）；`--live` 才真调，并**自带请求数硬闸**（`pageSize=500` 逐页循环 ⇒ 账上原记"1 发"是错的，实测口径 ≥3 发）。直连上游、不经 data-service ⇒ 它的东财计数器不会为它动 | 2026-10-12 E-3 刀 C（主人「按推荐方案做」）；⚠️ 这一行写的 `--live` 在 10-13 之前**并不存在**（argparse 只吃 `--dry-run`，裸跑即真调）＝文档对、码错；10-13 下午补上 `--live`、把默认改成演练，与 `window_contract.py` 同形＝CR9-93。当天到场那一次是裸跑打的（回执 `windowC-bondmap-1013*.out`） |
| `window_contract.py` | 闸2 的**现场腿**：对着真响应核 `web/lib/ds-contract.ts` 登记的键面，快照里有而真响应没有＝改名/摘键；`--write` 只回写**键面**（不存数值）到 `ds-contract.snapshot.json`。走 127.0.0.1 的 data-service ⇒ 这些发会花上游额度、会动东财桶，`--dry-run` 默认一条都不发。**每发之前过 `Fuse`**（`cooldown>0` 即停／连续 2 发非 200 即停／`CAP_REQUESTS=12` 硬闸，数的是 **ds 请求数**不是上游发数）；最贵的 `/products` **不进默认计划**，要它得 `--only /products` 点名；覆盖面分母从 ts 的 `NO_LIVE_PROBE` 现查（**现值＝11**＝13 登记 − 2 枚排除；10-12 那把尺的"＝10"不回改），`--selftest` 里"探针集合==分母"会自己红；10-13 新进的探针是 `/quote/realtime`（3 发＝实时区"一次取全"那一跳）——它同时是 CR9-92 的验收腿与闸2 L3 那两条"已知陈旧"的销账动作 | 同上；保险丝与分母＝2026-10-12 23:5x（主人「挂 Fuse＋CAP＋/products 显式点名；分母口径改成 10」）＝CR9-91；`/quote/realtime` 探针与分母 10→11＝2026-10-13 09:5x＝CR9-92 |

用法示例：

```bash
# 先启动双服务，触发同步（启动补跑或 POST /sync/run）后运行采样器
PYTHONIOENCODING=utf-8 python test-script/c0_sampler.py

# 实时源探针：NO_PROXY 必须列出国内域名，否则国内源也会被代理接管 ⇒ 测的是代理不是上游
cd data-service && HTTPS_PROXY=http://127.0.0.1:<代理端口> \
  NO_PROXY="qt.gtimg.cn,ifzq.gtimg.cn,hq.sinajs.cn,push2.eastmoney.com" \
  ./.venv/Scripts/python.exe ../test-script/realtime_probe.py

# 10-13 两窗：三件都带 --dry-run（一次 HTTP 都不发，含 /health）与 --selftest（fixture 自证）
python test-script/window_preflight.py            # 到场第一步，零上游
python test-script/window_a2.py --dry-run         # 先看计划与上限，不花钱
python test-script/window_a3.py                   # 真跑（服务在位时才发）
python test-script/window_fill.py                 # 读数往三格里填，拒填的会自己说明原因
python test-script/window_contract.py --dry-run   # 闸2 现场腿：先看会点哪几条、各几发
python test-script/window_bond_map.py --dry-run   # 刀 C：翻页成本 ≥3 发，件内硬闸 4
```

纪律：本目录只放**只读观测**脚本；任何会写库/破坏性操作的脚本不得入内。
本目录唯一的写动作是 `window_contract.py --write`：它回写的是仓库内的**键面快照**（`web/lib/ds-contract.snapshot.json`，只有键名、不存行情数值、不碰 SQLite／Prisma），且必须显式带 `--write`。⚠️ 两个后果：**(a)** 那是**版本管理里的文件** ⇒ 采完会多一笔 dirty，要单独一笔提交；**(b)** 保险丝停过手那一轮**拒写**（半截清单不该被抄成快照）。
