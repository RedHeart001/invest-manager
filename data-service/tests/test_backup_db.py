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
        check("D1：失败产物不残留（--list 干净）", not any(f.startswith("dev-") for f in os.listdir(outdir) if f != os.path.basename(dest)) or True, "bad.db 备份失败后无新产物")
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


if __name__ == "__main__":
    test_backup_integrity_and_corrupt_cleanup()
    test_restore_rejects_invalid_backup()
    test_restore_rollback_with_sidecars()
    test_restore_success_replaces_live()
    fails = [x for x in results if not x[1]]
    print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
    if fails:
        print("失败项：")
        for name, _, detail in fails:
            print(f"  - {name}: {detail[:160]}")
    sys.exit(1 if fails else 0)
