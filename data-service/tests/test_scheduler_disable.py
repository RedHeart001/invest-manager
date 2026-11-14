"""SCHEDULERS_ENABLED 隔离启动开关：默认开启，显式 0 时三类调度均不启动/不关闭。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import app.main as main  # noqa: E402


async def exercise(value: str | None) -> tuple[list[str], list[str]]:
    started: list[str] = []
    stopped: list[str] = []
    names = ("hotspot", "sync", "backup")
    modules = (main.hotspot_scheduler, main.sync_scheduler, main.backup_scheduler)
    originals = [(m.start_scheduler, m.shutdown_scheduler) for m in modules]
    previous = os.environ.get("SCHEDULERS_ENABLED")
    try:
        for name, module in zip(names, modules):
            module.start_scheduler = lambda name=name: started.append(name)
            module.shutdown_scheduler = lambda name=name: stopped.append(name)
        if value is None:
            os.environ.pop("SCHEDULERS_ENABLED", None)
        else:
            os.environ["SCHEDULERS_ENABLED"] = value
        async with main.lifespan(main.app):
            pass
    finally:
        for module, (start, stop) in zip(modules, originals):
            module.start_scheduler = start
            module.shutdown_scheduler = stop
        if previous is None:
            os.environ.pop("SCHEDULERS_ENABLED", None)
        else:
            os.environ["SCHEDULERS_ENABLED"] = previous
    return started, stopped


def check(name: str, condition: bool) -> None:
    print(f"{'OK' if condition else 'NG'} {name}")
    if not condition:
        raise AssertionError(name)


def run() -> None:
    started, stopped = asyncio.run(exercise(None))
    check("缺省仍启动全部日常调度", started == ["hotspot", "sync", "backup"])
    check("缺省退出仍关闭全部日常调度", stopped == ["hotspot", "sync", "backup"])
    started, stopped = asyncio.run(exercise("0"))
    check("显式 0 不启动任何调度/启动补跑", started == [])
    check("显式 0 不调用未启动调度器的关闭", stopped == [])


if __name__ == "__main__":
    run()
    print("===== 4/4 通过 =====")
