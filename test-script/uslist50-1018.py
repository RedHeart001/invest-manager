"""一次性探针（10-18，B1 甲+ 的覆盖面实测）：只跑美股名单那条腿，取 50 页、不写库。

零写入＝只调 provider 的列表方法＋只读 SQL（mode=ro）。页数由进程 env `US_LIST_PAGES`
决定（dotenv 不覆盖已存在的变量），所以主人不动 `.env` 也能在这一棵进程里读到 50。
"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import load_env
from app.providers import akshare_provider as ap


def main() -> int:
    load_env()
    pages = ap._us_list_pages()
    print(f"effective pages = {pages}（default {ap.US_LIST_DEFAULT_PAGES}／ceiling {ap.US_LIST_PAGE_CEILING}）")
    rows, meta = ap.AkshareProvider()._list_us_stocks()
    codes = [r["code"] for r in rows]
    uniq = set(codes)
    print(f"rows = {len(rows)}｜unique codes = {len(uniq)}")
    print(f"meta = {meta}")
    con = sqlite3.connect("file:../web/prisma/dev.db?mode=ro", uri=True)
    db = {c for (c,) in con.execute("select code from Product where type='us'")}
    total = con.execute("select count(*) from Product").fetchone()[0]
    con.close()
    print(f"DB us rows = {len(db)}｜DB Product total = {total}")
    print(f"new (探针有、库里没有) = {len(uniq - db)}")
    print(f"overlap = {len(uniq & db)}")
    print(f"库里独有（探针这 50 页没给到）= {len(db - uniq)}")
    print("sample new =", sorted(uniq - db)[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
