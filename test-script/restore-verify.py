#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""备份恢复验证件（P2 桶，2026-11-01 立）。

**它证明什么**：`data-service/scripts/backup_db.py` 的 `restore()` 在**真实生产库的备份**
上确实能把库还原出来，且还原结果与备份逐表一致。此前该脚本有 11 条离线单测
（`tests/test_backup_db.py`，tmp 目录合成库），但**从未在真实库上人工跑过一次**。

**它为什么必须是独立件而不是一条 shell 命令**：`restore()` 的 `--source` 参数语义是
「恢复到哪个路径」而不是「来源」（`backup_db.py:182` 的 `--source` 默认 `/data/dev.db`
⇒ 省略就覆盖生产库）。这条命令行给人手敲，迟早会漏参数。本件把 /tmp 目标写死在里面。

用法：
    PYTHONPATH=data-service python test-script/restore-verify.py
    PYTHONPATH=data-service python test-script/restore-verify.py --backup backups/dev-xxx.db
    PYTHONPATH=data-service python test-script/restore-verify.py --dry-run   # 只校验备份、不恢复

退出码：0＝全部通过；1＝有失败；2＝环境/参数问题（未执行验证）。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
PROD_DB = REPO / "web" / "prisma" / "dev.db"
BACKUP_DIR = REPO / "backups"
RUNTIME = REPO / "data-service" / "runtime"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"{'OK ' if cond else 'NG '} {name}" + (f" — {detail}" if detail and not cond else ""))


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def table_counts(path: Path) -> dict[str, int]:
    """逐表行数。打开前显式只读——绝不因为读一眼就改写生产库。"""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        out = {}
        for n in names:
            try:
                out[n] = con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
            except sqlite3.Error:
                # FTS5 影子表等可能不可直接 count；跳过而不是让整件事失败
                continue
        return out
    finally:
        con.close()


def latest_backup() -> Path | None:
    if not BACKUP_DIR.is_dir():
        return None
    items = sorted(BACKUP_DIR.glob("dev-*.db"))
    return items[-1] if items else None


def main() -> int:
    ap = argparse.ArgumentParser(description="备份恢复验证（绝不覆盖生产库）")
    ap.add_argument("--backup", help="要验证的备份文件（默认取 backups/ 下最新一枚）")
    ap.add_argument("--dry-run", action="store_true", help="只校验备份完整性，不真跑 restore")
    args = ap.parse_args()

    # ---------- 前置：把危险面挡在开始之前 ----------
    backup = Path(args.backup) if args.backup else latest_backup()
    if backup is None or not backup.exists():
        print(f"[前置] 找不到备份文件：{backup}", file=sys.stderr)
        return 2
    if not PROD_DB.exists():
        print(f"[前置] 生产库不存在：{PROD_DB}", file=sys.stderr)
        return 2

    # `restore()` 是 import 进来的，但它的行为受 cwd/相对路径影响 ⇒ 统一用绝对路径
    backup = backup.resolve()
    prod_before_md5 = md5(PROD_DB)
    prod_before = table_counts(PROD_DB)

    print(f"== 备份恢复验证 ==")
    print(f"备份  : {backup.relative_to(REPO)}  ({backup.stat().st_size:,} bytes)")
    print(f"生产库: {PROD_DB.relative_to(REPO)}  ({PROD_DB.stat().st_size:,} bytes)")
    print(f"生产库 md5（起跑前）: {prod_before_md5}")
    print()

    # ---------- ① 备份自身可读 ----------
    con = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        ic = con.execute("PRAGMA integrity_check").fetchone()
        tables = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()
    finally:
        con.close()
    check("① 备份 integrity_check = ok", bool(ic) and ic[0] == "ok", str(ic))
    check("① 备份含表（不是空壳）", bool(tables) and tables[0] > 0, str(tables))

    backup_counts = table_counts(backup)
    check(
        "① 备份有业务数据（Product 行数 > 0）",
        backup_counts.get("Product", 0) > 0,
        f"Product={backup_counts.get('Product')}",
    )

    if args.dry_run:
        print("\n[dry-run] 只校验备份，不执行 restore")
        return 0 if all(c for _, c, _ in results) else 1

    # ---------- ② 恢复到 /tmp（**绝不**用默认 --source） ----------
    sys.path.insert(0, str(REPO / "data-service"))
    sys.path.insert(0, str(REPO / "data-service" / "scripts"))
    import backup_db  # noqa: E402

    tmpdir = tempfile.mkdtemp(prefix="restore-verify-")
    target = Path(tmpdir) / "restored.db"
    print(f"\n[恢复] 目标 = {target}（临时目录，不是生产库）")
    ok = backup_db.restore(str(backup), str(target))
    check("② restore() 返回 True", ok, f"restore 返回 {ok}")

    if not ok:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return 1

    check("② 恢复产物存在", target.exists(), f"{target}")
    if not target.exists():
        # 产物都没有，后面几条"恢复库"的断言无从谈起——直接收尾报失败。
        # 以前这里会继续往下走、在 sqlite3.connect 抛 OperationalError 崩掉，
        # 读起来像是脚本坏了而不是"验证没通过"（2026-11-01 反向验证钻出来的）。
        shutil.rmtree(tmpdir, ignore_errors=True)
        passed = sum(1 for _, c, _ in results if c)
        print(f"\n== 结果：{passed}/{len(results)} 通过（恢复产物缺失，后续断言未执行）==")
        return 1

    # ---------- ③ 恢复结果与备份逐表一致 ----------
    con = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        ic2 = con.execute("PRAGMA integrity_check").fetchone()
    finally:
        con.close()
    check("③ 恢复库 integrity_check = ok", bool(ic2) and ic2[0] == "ok", str(ic2))

    restored_counts = table_counts(target)
    check(
        "③ 恢复库与备份**逐表行数相同**",
        restored_counts == backup_counts,
        _count_diff(backup_counts, restored_counts),
    )

    # ---------- ④ 生产库零改动（本件最硬的一条） ----------
    prod_after_md5 = md5(PROD_DB)
    prod_after = table_counts(PROD_DB)
    check(
        "④ 🔁 生产库 md5 前后一致（本次验证没有碰过它）",
        prod_before_md5 == prod_after_md5,
        f"{prod_before_md5} → {prod_after_md5}",
    )
    check(
        "④ 🔁 生产库逐表行数前后一致",
        prod_before == prod_after,
        _count_diff(prod_before, prod_after),
    )

    # ---------- 收尾 ----------
    shutil.rmtree(tmpdir, ignore_errors=True)
    check("⑤ 临时恢复库已清理", not target.exists(), str(target))

    passed = sum(1 for _, c, _ in results if c)
    total = len(results)
    print(f"\n== 结果：{passed}/{total} 通过 ==")
    return 0 if passed == total else 1


def _count_diff(a: dict[str, int], b: dict[str, int]) -> str:
    """只报差异，不打印整张表（35k 行的表有十几张）。"""
    diffs = [f"{k}: {a.get(k, '缺')} vs {b.get(k, '缺')}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    if not diffs:
        return ""
    return "；".join(diffs[:6]) + (f" 等 {len(diffs)} 处" if len(diffs) > 6 else "")


if __name__ == "__main__":
    sys.exit(main())
