"""backup_db.py 三条加固的自动化回归（D1/CR7-11，2026-09-25）。

背景：该脚本是全项目唯一**破坏性覆盖线上库**的代码，其三条加固此前零自动化回归——
① 备份产物 integrity_check（损坏产物删除、不残留）
② restore 前置验证（非法备份拒绝恢复，不把线上库"恢复"成空文件）
③ restore 失败自动回滚（含 -wal/-shm sidecar 还原，CR4/2026-09-14 修复）

全部用 tmp 目录构造库 + 损坏备份做离线测试，不触真实 /data/dev.db。

运行方式（无需任何服务在跑）：
    PYTHONPATH=. .venv/Scripts/python tests/test_backup_db.py
"""

import gc
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/scripts")
# CR9-14：用例名含 🔁 等非 GBK 字符，Windows GBK 控制台会 UnicodeEncodeError。
# 自带 UTF-8 输出后，跑本脚本不再需要 PYTHONIOENCODING（errors=replace 兜极端情况）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


import backup_db  # noqa: E402  （scripts/ 内模块，sys.path 已注入）

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def _make_db(path: str, rows: int = 3) -> None:
    con = sqlite3.connect(path)
    try:
        with con:
            con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
            con.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    finally:
        con.close()


def test_backup_integrity_and_corrupt_cleanup() -> None:
    """① 备份正常 → integrity ok；源损坏 → 失败产物删除不残留。"""
    with tempfile.TemporaryDirectory() as tmp:
        good_db = os.path.join(tmp, "good.db")
        _make_db(good_db)
        outdir = os.path.join(tmp, "out")
        dest = backup_db.backup(good_db, outdir)
        check("D1：正常库备份成功且产出存在", dest and os.path.exists(dest), str(dest))
        con = sqlite3.connect(dest)
        try:
            n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        finally:
            con.close()
        check("D1：备份内容完整（3 行）", n == 3, str(n))

        # 损坏源：非 SQLite 文件
        bad_db = os.path.join(tmp, "bad.db")
        with open(bad_db, "wb") as f:
            f.write(b"this is not a sqlite database" * 10)
        dest2 = backup_db.backup(bad_db, outdir)
        check("D1：损坏源备份失败返回空", dest2 == "", str(dest2))
        # CR9-15：原断言末尾挂着 `or True` → 恒真，把这条防线变成了假覆盖（C34）。
        # 去掉后按真实语义断：失败路径不得在 out 目录留下新的 dev-* 产物。
        leftovers = [
            f for f in os.listdir(outdir) if f.startswith("dev-") and f != os.path.basename(dest)
        ]
        check("D1：失败产物不残留（--list 干净）", not leftovers, str(leftovers))
        # 精确核对：out 目录中 db 文件数量 = 1（只有 good 的备份）
        dbs = [f for f in os.listdir(outdir) if f.endswith(".db")]
        check("D1：out 目录仅 1 个备份产物", len(dbs) == 1, str(dbs))


def test_restore_rejects_invalid_backup() -> None:
    """② restore 前置验证：非法备份拒绝恢复，线上库原样保留。"""
    with tempfile.TemporaryDirectory() as tmp:
        live_db = os.path.join(tmp, "dev.db")
        _make_db(live_db, rows=5)
        bad_backup = os.path.join(tmp, "bad.db")
        with open(bad_backup, "wb") as f:
            f.write(b"not sqlite at all")

        ok = backup_db.restore(bad_backup, live_db)
        check("D1：非法备份 → restore 返回 False", ok is False)
        con = sqlite3.connect(live_db)
        try:
            n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        finally:
            con.close()
        check("D1：线上库未被破坏（仍 5 行）", n == 5, str(n))

        # 空表备份（sqlite 有效但无表）同样拒绝
        empty_db = os.path.join(tmp, "empty.db")
        sqlite3.connect(empty_db).close()
        ok2 = backup_db.restore(empty_db, live_db)
        check("D1：无表备份 → 拒绝恢复", ok2 is False)
        con = sqlite3.connect(live_db)
        try:
            n2 = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        finally:
            con.close()
        check("D1：线上库仍未被破坏", n2 == 5, str(n2))


def test_restore_rollback_with_sidecars() -> None:
    """③ restore 中途失败 → 自动回滚，含 -wal/-shm sidecar。"""
    with tempfile.TemporaryDirectory() as tmp:
        live_db = os.path.join(tmp, "dev.db")
        _make_db(live_db, rows=7)
        # 造 sidecar（模拟 WAL 模式运行中的库）
        with open(live_db + "-wal", "wb") as f:
            f.write(b"wal-content")
        with open(live_db + "-shm", "wb") as f:
            f.write(b"shm-content")

        # 伪造"恢复源"：合法 SQLite 且有表（过前置验证），但 backup API 写回时
        # 会在中途失败——用不可写的目标路径触发。为可控注入，直接 monkeypatch
        # _connect_ro 返回的连接使 backup 抛错。
        good_backup = os.path.join(tmp, "good-bak.db")
        _make_db(good_backup, rows=1)

        orig_connect_ro = backup_db._connect_ro
        called = {"n": 0}

        def _connect_ro_then_fail(path: str):
            called["n"] += 1
            con = orig_connect_ro(path)
            if called["n"] == 2:  # 第二次调用 = restore 内写回阶段
                orig_close = con.close

                def _backup_patch(dst, **kw):
                    raise sqlite3.OperationalError("simulated mid-restore failure")

                con.backup = _backup_patch  # type: ignore[method-assign]
                # 保留 close 可用
                con.close = orig_close  # type: ignore[method-assign]
            return con

        backup_db._connect_ro = _connect_ro_then_fail
        try:
            ok = backup_db.restore(good_backup, live_db)
            check("D1：中途失败 → restore 返回 False", ok is False)
        finally:
            backup_db._connect_ro = orig_connect_ro

        # 回滚后：主库 + 两个 sidecar 全部还原
        check("D1：主库已回滚还原", os.path.exists(live_db), str(os.listdir(tmp)))
        check("D1：-wal sidecar 已还原", os.path.exists(live_db + "-wal"))
        check("D1：-shm sidecar 已还原", os.path.exists(live_db + "-shm"))
        con = sqlite3.connect(live_db)
        try:
            n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        finally:
            con.close()
        check("D1：回滚后数据完整（7 行）", n == 7, str(n))

        # 精确核对：恢复后的新库文件不存在（被回滚清理）
        check("D1：无残留半成品新库", not os.path.exists(live_db + ".journal"), "")
        gc.collect()  # Windows：释放 SQLite 连接句柄，允许 TemporaryDirectory 清理


def test_restore_success_replaces_live() -> None:
    """④（正向）合法备份恢复成功：新库生效、原库改名保留。"""
    with tempfile.TemporaryDirectory() as tmp:
        live_db = os.path.join(tmp, "dev.db")
        _make_db(live_db, rows=9)
        bak = os.path.join(tmp, "bak.db")
        _make_db(bak, rows=2)

        ok = backup_db.restore(bak, live_db)
        check("D1：合法备份恢复成功", ok is True)
        con = sqlite3.connect(live_db)
        try:
            n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        finally:
            con.close()
        check("D1：恢复后为新内容（2 行）", n == 2, str(n))
        pres = [f for f in os.listdir(tmp) if ".pre-restore-" in f]
        check("D1：原库改名保留（.pre-restore-*）", len(pres) == 1, str(pres))
        con = sqlite3.connect(os.path.join(tmp, pres[0]))
        try:
            n_old = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        finally:
            con.close()
        check("D1：保留的原库数据完整（9 行）", n_old == 9, str(n_old))
        gc.collect()  # Windows：释放 SQLite 连接句柄


# ---------- ①（2026-10-02）每日备份 job：app/backup_scheduler.py ----------
#
# 上面四条测的是**脚本**（有实现、有恢复），本段测的是**调度侧缺口**：10-01 全项目审计
# 实测 `dev.db` 63 MB 零备份——脚本没人调、`backups/` 空着。job 本身、份数轮换、
# 路径回落这三件事此前零断言，而它们才是"备份到底有没有在跑"的判据。

import app.backup_scheduler as bs  # noqa: E402


def _snapshot(outdir: str, stamp: str) -> str:
    p = os.path.join(outdir, f"dev-{stamp}.db")
    with open(p, "w", encoding="utf-8") as f:
        f.write("x")
    return p


def test_backup_job_registered_and_rotates() -> None:
    """job 注册 ⇔ 份数轮换（C34 成对：既断删得掉，也断不该删的一个不动）。"""
    with tempfile.TemporaryDirectory() as tmp:
        # ① 时刻配置：默认 03:30，env 可覆盖，非法值回落
        check("①：默认调度时刻 03:30（排在 02:00 同步＋刷新腿预算之后）",
              bs._hour_minute() == (3, 30), str(bs._hour_minute()))
        os.environ["BACKUP_HOUR"] = "abc"  # 非法
        check("①：BACKUP_HOUR 非法 ⇒ 回落默认而不是崩", bs._hour_minute() == (3, 30),
              str(bs._hour_minute()))
        os.environ["BACKUP_HOUR"] = "99"  # 越界
        check("①：越界值夹到合法区间（23）而不是把 cron 配炸", bs._hour_minute()[0] == 23,
              str(bs._hour_minute()))
        os.environ.pop("BACKUP_HOUR", None)

        # ② 真的注册进了 APScheduler（不是只有一个函数没人调）
        bs.start_scheduler()
        try:
            ids = [j.id for j in bs._scheduler.get_jobs()]
            nxt = bs._scheduler.get_jobs()[0].next_run_time
            check("①：daily-db-backup 已注册为 job", ids == ["daily-db-backup"], str(ids))
            check("①：下次触发时刻是 03:30（Asia/Shanghai）",
                  (nxt.hour, nxt.minute) == (3, 30), str(nxt))
            check("①：/health 的 dbBackup 带得出下一档时刻（"
                  "这样才能把'今天还没到 03:30'与'job 根本没注册'分开读）",
                  "03:30" in str(bs.health().get("nextRun")), str(bs.health()))
        finally:
            bs.shutdown_scheduler()
        check("🔁 ①：shutdown 后调度器置 None（服务停了不会有 job 残留）", bs._scheduler is None)
        check("🔁 ①：调度器停掉 ⇒ nextRun 变 null（不会被读成'还在等着跑'）",
              bs.health()["nextRun"] is None, str(bs.health()))

        # ③ 份数轮换：只认 dev-<日期>-<时间>.db，别的文件永不碰
        keep_dir = os.path.join(tmp, "backups")
        os.makedirs(keep_dir)
        for stamp in ("20260920-010000", "20260921-010000", "20260922-010000",
                      "20260923-010000", "20260924-010000"):
            _snapshot(keep_dir, stamp)
        unrelated = os.path.join(keep_dir, "handmade.db")
        with open(unrelated, "w", encoding="utf-8") as f:
            f.write("keep me")
        removed = bs.rotate(keep_dir, keep=2)
        check("①：超出 BACKUP_KEEP 的最旧份被删",
              removed == ["dev-20260920-010000.db", "dev-20260921-010000.db",
                          "dev-20260922-010000.db"], str(removed))
        left = sorted(os.listdir(keep_dir))
        check("🔁 ①：只删更旧的快照，最新 2 份与非快照文件一个不动",
              left == ["dev-20260923-010000.db", "dev-20260924-010000.db", "handmade.db"],
              str(left))
        # 真产物会带 WAL sidecar（10-02 活体探针实测：在线备份 API 连源库的 journal mode
        # 一起复制过来）⇒ 删一份快照必须连它自己的 -wal/-shm 一起删，否则目录里堆孤儿文件
        with_sidecar = os.path.join(tmp, "with_sidecar")
        os.makedirs(with_sidecar)
        for stamp in ("20260920-010000", "20260921-010000"):
            for suffix in ("", "-wal", "-shm"):
                with open(os.path.join(with_sidecar, f"dev-{stamp}.db{suffix}"), "w",
                          encoding="utf-8") as fh:
                    fh.write("x")
        removed2 = bs.rotate(with_sidecar, keep=1)
        check("①：删掉的那份快照把自己的 -wal/-shm 一起带走（不留半套文件）",
              removed2 == ["dev-20260920-010000.db", "dev-20260920-010000.db-wal",
                           "dev-20260920-010000.db-shm"], str(removed2))
        check("①：保留的那份 sidecar 一个都不动（它可能是未检查点的数据）",
              sorted(os.listdir(with_sidecar)) == ["dev-20260921-010000.db",
                                                   "dev-20260921-010000.db-shm",
                                                   "dev-20260921-010000.db-wal"],
              str(sorted(os.listdir(with_sidecar))))
        check("①：keep 大于现有份数 ⇒ 零删除", bs.rotate(keep_dir, keep=9) == [])
        check("①：BACKUP_KEEP 非法 ⇒ 回落 7 而不是清空目录", bs._keep() == 7, str(bs._keep()))
        os.environ["BACKUP_KEEP"] = "0"
        check("①：BACKUP_KEEP=0 ⇒ 夹到 1（绝不配成'每轮把自己删干净'）", bs._keep() == 1)
        os.environ.pop("BACKUP_KEEP", None)


def test_backup_run_once_end_to_end_and_paths() -> None:
    """`run_once` 两条分支 ⇔ 路径回落链（容器挂载点／dev 仓库内）。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "dev.db")
        _make_db(src, rows=4)
        out = os.path.join(tmp, "backups")
        orig_env = {k: os.environ.get(k) for k in ("DB_PATH", "BACKUP_DIR", "BACKUP_KEEP")}
        orig_state = dict(bs._state)
        try:
            os.environ.update({"DB_PATH": src, "BACKUP_DIR": out, "BACKUP_KEEP": "7"})
            r = bs.run_once("unit-test")
            produced = [f for f in os.listdir(out) if bs.SNAPSHOT_NAME.match(f)]
            check("①：run_once 产出一份快照且回 ok=True",
                  r.get("ok") is True and len(produced) == 1, str(r))
            con = sqlite3.connect(os.path.join(out, produced[0]))
            try:
                n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            finally:
                con.close()
            check("①：快照内容是真库（4 行，走在线备份 API 而非文件拷贝）", n == 4, str(n))
            check("①：健康位带得出最后时刻与次数",
                  bs.health()["ok"] is True and bs.health()["runs"] == 1, str(bs.health()))
            check("🔁 ①：观测位不回显绝对路径（/health 不是文件系统清单）",
                  tmp not in str(bs.health()), str(bs.health()))

            # 失败分支：源库不存在 ⇒ 必须"看得见地失败"，且一个字节都不写
            os.environ["DB_PATH"] = os.path.join(tmp, "nope", "dev.db")
            os.remove(os.path.join(out, produced[0]))
            r2 = bs.run_once("unit-test")
            check("①：源库不存在 ⇒ ok=False ＋ skippedReason=source-not-found",
                  r2.get("ok") is False and r2.get("skippedReason") == "source-not-found",
                  str(r2))
            check("🔁 ①：失败轮不产出半成品快照（空目录不会被误读成'有备份'）",
                  [f for f in os.listdir(out) if bs.SNAPSHOT_NAME.match(f)] == [], str(os.listdir(out)))
            # #29 之后这条口径要说满：目录里**不是全空**——`state.json` 是状态位不是快照，
            # 判"有没有备份产物"必须按 SNAPSHOT_NAME 过滤（上面那条 🔁 已按此收紧）。
            check("#29：失败轮同样落 state.json（'没备'必须比'备过'更容易读出来）",
                  os.path.exists(os.path.join(out, bs.STATE_NAME)), str(os.listdir(out)))
            st = bs.read_state(out) or {}
            check("#29：磁盘状态带得回失败那轮的 ok/skippedReason/trigger",
                  st.get("ok") is False and st.get("skippedReason") == "source-not-found"
                  and st.get("trigger") == "unit-test", str(st))
            check("🔁 #29：磁盘状态里不写绝对路径（落盘不能变成新的路径泄露面）",
                  tmp not in open(os.path.join(out, bs.STATE_NAME), encoding="utf-8").read(),
                  str(st))
            check("🔁 #29：原子写不留 `.tmp`（读到半截的可能被排除）",
                  not os.path.exists(os.path.join(out, bs.STATE_NAME + ".tmp")), str(os.listdir(out)))
        finally:
            for k, v in orig_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            bs._state.clear()
            bs._state.update(orig_state)

        # 路径回落：不设 env 时，dev 侧必须落在仓库里的真实 dev.db 上
        os.environ.pop("DB_PATH", None)
        os.environ.pop("BACKUP_DIR", None)
        resolved_src = bs._source_db()
        check("①：无 DB_PATH ⇒ 回落到 web/prisma/dev.db（配错路径的 job 会每晚静默 no-op）",
              resolved_src.endswith(os.path.join("web", "prisma", "dev.db")), resolved_src)
        check("①：回落后的源库在本机确实存在", os.path.exists(resolved_src), resolved_src)
        resolved_dir = bs._backup_dir()
        check("①：无 BACKUP_DIR ⇒ 回落到仓库根 backups/（已被 .gitignore 挡住）",
              resolved_dir.endswith("backups") and os.path.isdir(resolved_dir), resolved_dir)


def test_backup_captures_uncheckpointed_wal_rows() -> None:
    """① 的真前提：**WAL 未检查点**的写入也必须进快照（`cp` 做不到，在线备份 API 做得到）。

    dev.db 是 WAL 模式，web 是常驻 writer ⇒ "备份有没有落盘"完全取决于取快照的方式。
    这条用例锁的就是 2026-09-30 记过的那次仪器错的同类根因（只复制主文件＝读过期快照）。
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "dev.db")
        con = sqlite3.connect(src)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            with con:
                con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
                con.execute("INSERT INTO t (v) VALUES ('committed-not-checkpointed')")
            out = os.path.join(tmp, "backups")
            dest = backup_db.backup(src, out)
            check("①：未检查点的 WAL 写入仍在源连接持有期间被快照收下", bool(dest), str(dest))
            ro = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
            try:
                rows = [r[0] for r in ro.execute("SELECT v FROM t")]
            finally:
                ro.close()
            check("①：快照里查得到那一行（不是空库快照）",
                  rows == ["committed-not-checkpointed"], str(rows))
        finally:
            con.close()


def test_backup_state_survives_process_death() -> None:
    """#29（10-03 断电实测）：备份结果必须比进程活得久——落盘、可回落读、轮换永不碰它。

    C34 成对三组：`fromDisk` 两态（内存空才回落 ⇔ 内存有值不得被旧文件盖住）；
    有文件 ⇔ 没文件／坏文件；**写盘失败 ⇔ 备份本身照旧成功**（观测不得拖垮主功能）。
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "dev.db")
        _make_db(src, rows=2)
        out = os.path.join(tmp, "backups")
        state_path = os.path.join(out, bs.STATE_NAME)
        orig_env = {k: os.environ.get(k) for k in ("DB_PATH", "BACKUP_DIR")}
        orig_state = dict(bs._state)
        try:
            os.environ.update({"DB_PATH": src, "BACKUP_DIR": out})
            bs._state.update({"running": False, "lastRun": None, "lastResult": None, "runs": 0})
            r = bs.run_once("unit-test")
            st = bs.read_state(out) or {}
            check("#29：成功轮同时落盘（stateWritten=True，磁盘那份 ok/outcome 齐）",
                  r.get("stateWritten") is True and st.get("ok") is True
                  and st.get("outcome") == "completed", f"{r} / {st}")

            # 轮换永不碰状态文件：它和快照同目录，正是 rotate 只按 SNAPSHOT_NAME 删才安全
            _snapshot(out, "20260101-000000")
            _snapshot(out, "20260102-000000")
            removed = bs.rotate(out, 2)
            check("#29：轮换只删快照，`state.json` 永不被 prune（放在 backups/ 里的前提）",
                  os.path.exists(state_path) and bs.STATE_NAME not in removed, str(removed))

            # 模拟进程死亡：内存清空，磁盘那份还在 ⇒ 一条 curl 仍判得出"昨晚备过"
            saved = dict(bs._state)
            bs._state.update({"running": False, "lastRun": None, "lastResult": None, "runs": 0})
            h_disk = bs.health()
            check("#29：内存清空 ⇒ 回落到磁盘那份并标 fromDisk=True（断电重启后可读）",
                  h_disk.get("fromDisk") is True and bool(h_disk.get("lastRun"))
                  and h_disk.get("ok") is True, str(h_disk))
            bs._state.clear()
            bs._state.update(saved)
            h_mem = bs.health()
            check("🔁 #29：内存跑过就用内存那份、fromDisk=False（旧文件不得盖住新事实）",
                  h_mem.get("fromDisk") is False and h_mem.get("lastRun") == saved["lastRun"],
                  str(h_mem))

            os.remove(state_path)
            bs._state.update({"running": False, "lastRun": None, "lastResult": None, "runs": 0})
            h_none = bs.health()
            check("🔁 #29：磁盘也没有状态文件 ⇒ lastRun=None／runs=0（'从没备过'与'昨晚备过'分得开）",
                  h_none["lastRun"] is None and h_none["runs"] == 0
                  and h_none["fromDisk"] is False, str(h_none))
            with open(state_path, "w", encoding="utf-8") as f:
                f.write("{not json")
            check("#29：损坏的 state.json 当'没有'读，不抛（观测位不得把 /health 变成 500）",
                  bs.read_state(out) is None, "")
            os.remove(state_path)

            orig_replace = os.replace
            try:
                os.replace = lambda *a, **kw: (_ for _ in ()).throw(OSError("disk busy"))
                r2 = bs.run_once("unit-test")
            finally:
                os.replace = orig_replace
            check("🔁 #29：状态写不进去（磁盘忙）⇒ 只置 stateWritten=False，备份本身仍判成功",
                  r2.get("ok") is True and r2.get("stateWritten") is False, str(r2))
            check("🔁 #29：写失败不留 `.tmp` 残件",
                  not os.path.exists(state_path + ".tmp"), str(os.listdir(out)))
        finally:
            for k, v in orig_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            bs._state.clear()
            bs._state.update(orig_state)


if __name__ == "__main__":
    test_backup_integrity_and_corrupt_cleanup()
    test_restore_rejects_invalid_backup()
    test_restore_rollback_with_sidecars()
    test_restore_success_replaces_live()
    test_backup_job_registered_and_rotates()
    test_backup_run_once_end_to_end_and_paths()
    test_backup_captures_uncheckpointed_wal_rows()
    test_backup_state_survives_process_death()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
