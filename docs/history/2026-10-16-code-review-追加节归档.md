# CODE-REVIEW.md 归档（2026-10-16）

> **这是什么**：[../CODE-REVIEW.md](../CODE-REVIEW.md) 的以下块整体搬迁（体量治理：FILE 余量掉到 490⇒搬两节无活口追加节（主人 10-16 给「搬」字，主会话 15:3x 执行） 触发，机械，必进）。
> **内容逐字保留、未做任何改写**；本文件只作历史对照，不在此维护状态。

---

#### 追加六十九 · 10-15 01:4x–01:5x（W0 落地轮：CR9-100／101／102 三枚——#70 扩到 6 枚、#71 一行、#72 改落点；全量闸全绿＋真账本闸前后逐字不变）

① **字＝「先做w0，就按照你的推荐方案来做，做完之后进行全量测试，测试没问题再进行归档docs和add、commit」**。生产码一行（`sync_scheduler.py` 的 dirname 层数）＋测试件 7 枚（6 枚补隔离＋1 枚补 encoding＋1 枚加断言；`test_p2_m8.py` 同时属 #71）。

② **#70＝CR9-100：登记口径 4 枚不够，实测扩到 6 枚**。4 枚（`test_cr9_45_health_async`／`test_cr9_45_inflight_cap`／`test_cr9_59_us_list`／`test_opt2_news_fusion`）照 `test_p2_m8.py` 写法各指临时落点后**首跑闸②仍见真账本变**＝`eastmoney granted 3→6`（`sha c0efb1d6→01f2ec28`）。⇒ **逐套定位**（对 `tests/test_*.py` 逐枚跑、逐枚对账本 hash）抓到剩余写者＝**`test_g6_hk.py` 与 `test_p6_mcp.py`**（同为离线套件、运行时真走到东财族门），一并补隔离。**终验＝闸1 复跑两枚（`gate1-65`／`gate1-66`）真账本 size＋sha256 前后逐字不变（`10a3c81a…`、2249B）**——这一对"变了→不变"就是本条的 🔁（负/正对照都在实测里）。

③ **⚠️ 一处我的失误，记进出网账（不藏）**：定位循环用的是裸 `for f in tests/test_*.py`，**没过 `offlineSuites()` 过滤** ⇒ 把 live 套件 `test_p0.py`／`test_p1.py` 也各误跑了一遍（它们是 HTTP 套件、打 `:8000` 真上游）。实测代价＝ds 进程内 `akshare-obs granted 2／eastmoney granted 2`、`denied 7`（本地拒、零出网）⇒ **真上游 ≈4 发**。这 4 发记在 ds 进程内、将在它下次落盘时进 10-15 那格 ⇒ **W1.1 读 Q2-1 时把这 4 发从"02:00 那轮的"里摘出去**（#70 行末已写同句）。教训＝逐套循环必须走 `gate.mjs` 的同一把过滤器，不许手写清单。

④ **#71＝CR9-101**：`test_p2_m8.py:1387` 的 `subprocess.run` 补 `encoding="utf-8", errors="replace"`。两种起法复跑＝不带该变量（闸1②内）**149/149**、带（单跑 `PYTHONIOENCODING=utf-8`）**149/149**，exit 均 0（修前带该变量是 `AttributeError` 崩）。

⑤ **#72＝CR9-102**：`sync_scheduler.py` 的 dirname 层数 ×3→×2（落 `data-service/runtime/`，与 limiter／hotspot 同语义）；`test_c1_catchup_yield.py` 新增 2 枚断言（33→35）。**反向验证 🔁**＝临时回退成 ×3 ⇒ **恰好 2 枚红**、detail 逐字＝`E:\person_projects\invest-manager\runtime\sync-state.json`；恢复后 **35/35**。⚠️ 时效两条：**(a)** 02:00 那轮跑的是**旧进程**（内存里仍是 ×3）⇒ 仓库根那份 `runtime/sync-state.json` 今晚仍会生成一次（`?? runtime/` 属预期、**别提交**），重启装载新码后落点才切走、届时仓库根那份可直接删；**(b)** 我中途有一次恢复命令因 `cd` 相对路径失败而没执行（钻态多留了一跑），已按备份恢复并复跑 35/35——"恢复要验证、别信命令没报错"这一形记在案。

⑥ **全量闸终态**（10-15 01:48，对着 `dev 711a19a dirty=9`）＝`gate1-66-1015-0148.out`：① `tsc` 0 错＋vitest **434/434（49 文件）**｜② ds 离线 **23 套 907/907**（905→907＝＋2 枚 CR9-102 断言）｜docs **NEW=0／KNOWN 13/13**、断链 **0**、`--selftest` PASS；账本前后 `10a3c81a…` 逐字不变。三枚回执成对＝`gate1-64`（dirty=7，**首跑**、账本 3→6 的见证）／`gate1-65`（dirty=9，补隔离后**不变**）／`gate1-66`（dirty=9，**终态不变**）。


#### 追加六十七 · 10-14 19:1x–19:3x（CR9-99＝#69 定档乙 落码轮；批次② 按甲就位）

① **字＝「1、批次② 走甲 2、#69 走乙 3、执行完做全量测试、通过则更新 docs 并 commit」**。生产码两处＝`app/utils/limiter.py` 加 `_flush_at_exit()`＋`atexit.register`（退出不节流、补一次 `flush(force=True)`，异常只 warning）；`tests/test_p2_m8.py` 加五枚 CR9-99 断言＋本套件 `finally` 的顺序修正。

② **摘钩钻**＝注释掉 `atexit.register` 那行 ⇒ **148/149**，唯一那枚红的 detail 逐字就是缺陷本体：`bucket={'denied':0,'granted':0,'seen':{'ak.both':1},'seenTotal':1}`（＝「追加六十五」⑧ 那一形，现在由我自己的用例复现）。恢复后 149/149、DRILL 残留 0。**五枚里只有 ① 判别这枚钩子**：②（无增量不碰文件）／③（纯 observe 不虚增）／④（写不进仍以 0 退出）摘钩后照样绿，账上不许把它们算成钩子的牙齿。

③ **本刀放大出来的危害比原缺陷更值钱**：钩子读的是**退出那一刻**的 env，而 `finally` 先把 `LIMITER_STATE_FILE` 恢复成未设 ⇒ 收尾落盘把测试计数倒进**仓库**那本账。实测 18:35→19:3x `akshare-obs granted 0→24`（4 次 run × 6 发；`ak.stock_zh_a_spot 16`／`ak.bond_zh_hs_cov_spot 8`）＝**测试流量，不是生产流量**。修＝在窗口内先 `_lim.flush(force=True)` 再恢复 env；复验＝套件跑完那本账 size＋sha256 前后一致（2069／`4df2dc172fc8d548`）；并补 ⑤ 枚替身用例（两枚临时落点：把窗口内那次 flush 摘掉 ⇒ 换走的落点被写上、⑤ 精确红）。⇒ **丙（给那 16 枚补隔离）从可选变必须**：闸1 的 ② 整批现在一次写进真账本 `akshare-obs granted +11／eastmoney +3`（钩子之前只 +2）。

④ **批次②（甲）已就位＋已装载**＝web 7080、cron `nextRun 2026-10-15 02:00:00`；三枚判据照「追加六十六」④ 全在盘上，Q2-1 读 ds 进程内 `/health limiters[]`。✅ **22:32 字＝「重启加载新码」**＝ds **21620 @22:33:29 ＞ `b861faf` 19:30:20 ⇒ CR9-99 已装载**（本枚无运行时新键可读，装载证据只有时间戳法）；启动零出网＝进程内两族全 0、热点补跑读盘报 `already attempted today`。

⑤ **闸1**＝`data-service/runtime/gate1-57-1014-194x.out`（抬头 `dev 1472f6c dirty=2`、50s）＝① `tsc` 0 错＋vitest **434/434**（49 文件）｜② 23 套 **905/905**（900→905＝＋5 枚 CR9-99）｜docs NEW=0／KNOWN 21/21、断链 0。docs 尾账另用 `docs-scan --baseline` 复跑——本轮只改文字，不重买 ② 里那一发真报价。

