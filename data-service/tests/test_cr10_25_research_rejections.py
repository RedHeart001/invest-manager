"""CR10-25：研报拒绝原因必须是结构化三态，容量满不得伪装成同标的运行。

只构造内存任务表，不启动线程、不调用 LLM 或任何外部服务。
运行：PYTHONPATH=. .venv/Scripts/python tests/test_cr10_25_research_rejections.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# CR9-14：Windows GBK 控制台会把「通过」等汇总字写成乱码，闸1 汇总解析因此读不出。
# 自带 UTF-8 输出后，跑本脚本不再需要 PYTHONIOENCODING（errors=replace 兜极端情况）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from app.research import tasks
from app.utils.timeutil import beijing_today

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    results.append((name, bool(condition), str(detail)))
    print(f"{'OK ' if condition else 'NG '} {name}" + (f" — {detail}" if not condition else ""))


def _running(task_id: str, key: str) -> dict:
    return {"id": task_id, "key": key, "status": "running", "finishedAt": None}


def main() -> None:
    old_tasks = tasks._tasks.copy()
    old_daily = tasks._daily_done.copy()
    try:
        tasks._tasks.clear()
        tasks._daily_done.clear()

        tasks._tasks["same"] = _running("same", "stock:600000")
        same = tasks.start_research("stock", "600000")
        check("同标的去重 → reason=running", same.get("reason") == "running", same)
        check("同标的去重保留原 taskId", same.get("taskId") == "same", same)

        tasks._tasks["other"] = _running("other", "stock:600001")
        capacity = tasks.start_research("stock", "600002")
        check("全局容量满 → reason=capacity", capacity.get("reason") == "capacity", capacity)
        check("容量满不创建新任务", set(tasks._tasks) == {"same", "other"}, list(tasks._tasks))

        tasks._tasks.clear()
        tasks._daily_done["stock:600003"] = beijing_today()
        done = tasks.start_research("stock", "600003")
        check("当日完成 → reason=today_done 且兼容 todayDone",
              done.get("reason") == "today_done" and done.get("todayDone") is True, done)
    finally:
        tasks._tasks.clear()
        tasks._tasks.update(old_tasks)
        tasks._daily_done.clear()
        tasks._daily_done.update(old_daily)

    failed = [r for r in results if not r[1]]
    print(f"===== {len(results) - len(failed)}/{len(results)} 通过 =====")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
