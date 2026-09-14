#!/usr/bin/env python
"""data-service SQLite 备份/恢复脚本（P7）。

设计要点（PLAN P7 三轮补强）：
- 使用 **Python stdlib sqlite3 在线备份 API**（`Connection.backup`）：
  对 WAL 模式数据库是**一致性快照**，无需停止 web 服务（避免 `cp` 造成撕裂拷贝）。
- 在 **data-service 容器内**执行；dev 数据卷以 **rw** 方式挂载（P7 实测结论：恢复需写入），
  备份输出目录用宿主机 bind mount（`/backup`）。

用法（容器内）：
    python -m scripts.backup_db                       # 备份到 /backup/dev-<时间戳>.db
    python -m scripts.backup_db --list                # 列出已有备份
    python -m scripts.backup_db --restore /backup/dev-xxx.db   # 恢复到 /data/dev.db

恢复注意：恢复前应先 `docker compose stop web`（避免应用持有连接），恢复后启动并跑冒烟。
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys

DEFAULT_DB = os.environ.get("DB_PATH", "/data/dev.db")
DEFAULT_BACKUP_DIR = os.environ.get("BACKUP_DIR", "/backup")


def _connect_ro(path: str) -> sqlite3.Connection:
    """只读打开（uri 模式）：只读源不做任何写入，配合 backup API 取一致性快照。"""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def backup(source: str, outdir: str) -> str:
    if not os.path.exists(source):
        print(f"[backup] 源数据库不存在：{source}", file=sys.stderr)
        return ""
    os.makedirs(outdir, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(outdir, f"dev-{ts}.db")
    src = _connect_ro(source)
    try:
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
            integrity = dst.execute("PRAGMA integrity_check").fetchone()
        finally:
            dst.close()
    finally:
        src.close()

    size = os.path.getsize(dest)
    ok = bool(integrity) and integrity[0] == "ok"
    print(f"[backup] 输出：{dest}（{size} bytes，integrity_check={integrity[0] if integrity else 'n/a'}）")
    return dest if ok else ""


def restore(backup_file: str, target: str) -> bool:
    if not os.path.exists(backup_file):
        print(f"[restore] 备份文件不存在：{backup_file}", file=sys.stderr)
        return False

    # 2026-09-13 code review 加固：恢复是破坏性操作，必须**先验证再覆盖**，
    # 且失败时自动回滚——此前若备份文件非法（空文件/非 SQLite），
    # sqlite3.connect 会静默创建空库，导致线上库被"恢复"成空文件。
    try:
        src_check = _connect_ro(backup_file)
        try:
            integrity = src_check.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                print(f"[restore] 备份文件未通过完整性校验：{integrity}", file=sys.stderr)
                return False
            tables = src_check.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()
            if not tables or tables[0] == 0:
                print("[restore] 备份文件不含任何表，拒绝恢复", file=sys.stderr)
                return False
        finally:
            src_check.close()
    except sqlite3.Error as e:
        print(f"[restore] 备份文件不是有效 SQLite 库：{e}", file=sys.stderr)
        return False

    # 挪走的文件清单：[(现名, 原名)]，回滚时按序全部还原。
    # 修复（2026-09-14 code review）：此前回滚只还原主库，被挪走的 -wal/-shm
    # 留在 .pre-restore 名下不还原 → WAL 模式下未检查点事务丢失。
    moved: list[tuple[str, str]] = []
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if os.path.exists(target):
        pre = f"{target}.pre-restore-{ts}"
        os.replace(target, pre)
        moved.append((pre, target))
        print(f"[restore] 原库已改名保留：{pre}")
    # WAL/SHM 必须一并清理：残留的旧 WAL 会被应用到新库（数据错乱）
    for suffix in ("-wal", "-shm"):
        sidecar = target + suffix
        if os.path.exists(sidecar):
            sidecar_pre = f"{sidecar}.pre-restore-{ts}"
            os.replace(sidecar, sidecar_pre)
            moved.append((sidecar_pre, sidecar))

    try:
        # 用 backup API 反向写回（同样保证一致性）
        src = sqlite3.connect(backup_file)
        try:
            dst = sqlite3.connect(target)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except Exception as e:  # noqa: BLE001
        # 失败自动回滚（2026-09-13 加固；2026-09-14 补齐 sidecar 还原）
        print(f"[restore] 恢复失败：{e}；正在回滚", file=sys.stderr)
        # 先清掉可能已写出一半的新库，再把挪走的文件按序还原
        try:
            if os.path.exists(target):
                os.remove(target)
        except OSError:
            pass
        rollback_errors: list[str] = []
        for cur, orig in moved:
            if not os.path.exists(cur):
                continue
            try:
                os.replace(cur, orig)
            except OSError as re_err:
                rollback_errors.append(f"{orig}: {re_err}")
        if not moved:
            print("[restore] 无可回滚的原库（目标原先不存在）", file=sys.stderr)
        elif rollback_errors:
            print(
                f"[restore] 回滚不完整：{('; '.join(rollback_errors))}"
                f"（保留文件在 {target}.pre-restore-{ts}*）",
                file=sys.stderr,
            )
        else:
            print("[restore] 已回滚到原库（含 WAL/SHM）")
        return False

    print(f"[restore] 已恢复到：{target}")
    return True


def list_backups(outdir: str) -> None:
    if not os.path.isdir(outdir):
        print(f"[list] 备份目录不存在：{outdir}")
        return
    items = sorted(f for f in os.listdir(outdir) if f.endswith(".db"))
    if not items:
        print(f"[list] {outdir} 暂无备份")
        return
    for f in items:
        full = os.path.join(outdir, f)
        print(f"  {f}  {os.path.getsize(full)} bytes")


def main() -> int:
    ap = argparse.ArgumentParser(description="SQLite 在线备份/恢复（WAL 安全）")
    ap.add_argument("--source", default=DEFAULT_DB, help=f"数据库路径（默认 {DEFAULT_DB}）")
    ap.add_argument("--outdir", default=DEFAULT_BACKUP_DIR, help=f"备份目录（默认 {DEFAULT_BACKUP_DIR}）")
    ap.add_argument("--list", action="store_true", help="列出已有备份")
    ap.add_argument("--restore", metavar="FILE", help="从备份文件恢复")
    args = ap.parse_args()

    if args.list:
        list_backups(args.outdir)
        return 0
    if args.restore:
        return 0 if restore(args.restore, args.source) else 1
    return 0 if backup(args.source, args.outdir) else 1


if __name__ == "__main__":
    sys.exit(main())
