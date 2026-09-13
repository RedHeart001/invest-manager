#!/usr/bin/env python
"""data-service SQLite 备份/恢复脚本（P7）。

设计要点（PLAN P7 三轮补强）：
- 使用 **Python stdlib sqlite3 在线备份 API**（`Connection.backup`）：
  对 WAL 模式数据库是**一致性快照**，无需停止 web 服务（避免 `cp` 造成撕裂拷贝）。
- 在 **data-service 容器内**执行；dev 数据卷以**只读**方式挂载（`/data:ro`），
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
    if os.path.exists(target):
        ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        pre = f"{target}.pre-restore-{ts}"
        os.replace(target, pre)
        print(f"[restore] 原库已改名保留：{pre}")
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
