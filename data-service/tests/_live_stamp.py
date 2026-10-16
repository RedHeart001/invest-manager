"""③ 实网回执的树戳（#78）：一份判据，两处出口——p0/p1 直接 import，④ 用 `--line` spawn 同一份。

为什么不复用 `test-script/window_lib`：它在 import 时就执行 `reconfigure(encoding="utf-8")`，而
CPython 会把没显式给的 `errors` 打回 `strict` ⇒ 反向 import 会把 CR9-14 给这两枚套件加的
`errors="replace"` 拆掉（那枚修复的由来是 GBK 控制台崩在用例名的 🔁 上）。本模块被 import 时对
stdout 不做任何事，reconfigure 只住在 `__main__` 分支里。

为什么比 epoch 而不是比 ISO 串：进程 StartTime 经 PowerShell 出来受控制台区域设置影响
（中文机器上是 `2026年10月13日 13:08:33`），拿去和 ISO 串按字符串比大小，`'-' < '年'` 恒成立
⇒ 装载判据在任何真实时序下都判"成立"＝常绿，10-13 18:1x 实测抓到过一次。整数对整数没有这一维。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATHSPEC = "data-service/app"
BEIJING = timezone(timedelta(hours=8))


def _run(cmd: list[str]) -> str | None:
    """外部命令一律"成功才有读数"：非 0／超时／缺二进制 ⇒ None，由调用方判"读不出"，不兜底成 0。"""
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, cwd=REPO_ROOT
        )
    except Exception:
        return None
    return (out.stdout or "").strip() if out.returncode == 0 else None


def _count_lines(text: str | None) -> int:
    return len([line for line in (text or "").splitlines() if line.strip()])


def _first(text: str | None) -> str | None:
    return text.splitlines()[0].strip() if text else None


def collect(run=_run) -> dict:
    """`dirty=<全仓>/<app scoped>` 两枚分开报：落账轮里全仓恒 ≥1，只有 scoped 那枚说"HEAD 是否真描述被测码"。"""
    porcelain = ["git", "status", "--porcelain"]
    app_ct = _first(run(["git", "log", "-1", "--format=%ct", "--", APP_PATHSPEC]))
    return {
        "sha": _first(run(["git", "rev-parse", "--short", "HEAD"])),
        "branch": _first(run(["git", "rev-parse", "--abbrev-ref", "HEAD"])),
        "dirtyAll": _count_lines(run(porcelain)),
        "dirtyApp": _count_lines(run(porcelain + ["--", APP_PATHSPEC])),
        "appCommitEpoch": int(app_ct) if app_ct and app_ct.isdigit() else None,
    }


def ds_start_epoch(port: int = 8000, run=_run) -> int | None:
    ps = (
        f"$p=(Get-NetTCPConnection -LocalPort {port} -State Listen | "
        "Select-Object -First 1 -Expand OwningProcess);"
        "if ($p) {[DateTimeOffset]::new((Get-Process -Id $p).StartTime).ToUnixTimeSeconds()}"
    )
    tail = _first(run(["powershell", "-NoProfile", "-Command", ps]))
    return int(tail) if tail and tail.isdigit() else None


def load_verdict(app_commit_epoch: int | None, ds_start_epoch: int | None) -> str:
    if app_commit_epoch is None or ds_start_epoch is None:
        return "读不出"
    return "成立" if ds_start_epoch >= app_commit_epoch else "旧码"


def iso(epoch: int | None) -> str:
    return datetime.fromtimestamp(epoch, BEIJING).isoformat(timespec="seconds") if epoch else "-"


def stamp_line(port: int = 8000) -> str:
    c = collect()
    start = ds_start_epoch(port)
    return (
        f"树戳：HEAD={c['sha'] or '?'} dirty={c['dirtyAll']}/{c['dirtyApp']} "
        f"ds={iso(start)} appCommit={iso(c['appCommitEpoch'])} "
        f"装载={load_verdict(c['appCommitEpoch'], start)}"
    )


def _selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def ck(name: str, cond) -> None:
        checks.append((name, bool(cond)))
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")

    ck("进程晚于最后一枚 app 提交 ⇒ 装载成立", load_verdict(1000, 2000) == "成立")
    ck("两半样本：交换大小必须翻回旧码（否则判据恒真）", load_verdict(2000, 1000) == "旧码")
    ck(
        "任一读数取不到 ⇒ 判读不出，绝不静默判成立",
        load_verdict(None, 5) == "读不出" and load_verdict(5, None) == "读不出",
    )

    two = "M docs/README.md\nM data-service/app/main.py"
    def fake(argv: list[str]) -> str:
        if argv == ["git", "status", "--porcelain"]:
            return two
        if argv == ["git", "status", "--porcelain", "--", APP_PATHSPEC]:
            return "M data-service/app/main.py"
        if argv[:3] == ["git", "rev-parse", "--short"]:
            return "abc1234"
        if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return "dev"
        if argv[:2] == ["git", "log"]:
            return "1700000000"
        raise AssertionError(f"未预期的命令：{argv}")

    def fake_no_pathspec(argv: list[str]) -> str:
        # 负对照＝把 scoped 那枚命令的 pathspec 摘掉（写错时它悄悄退化成全仓计数＝又一枚常真的键）。
        return fake(["git", "status", "--porcelain"] if argv[:3] == ["git", "status", "--porcelain"] else argv)

    got = collect(run=fake)
    stripped = collect(run=fake_no_pathspec)
    ck(
        "scoped 计数走带 pathspec 的第二枚命令（全仓 2／app 1／sha／%ct 都取到）",
        (got["dirtyAll"], got["dirtyApp"], got["sha"], got["appCommitEpoch"]) == (2, 1, "abc1234", 1700000000),
    )
    ck(
        "两半样本：摘掉 pathspec ⇒ app 计数必须翻回 2（这枚键不是常真）",
        stripped["dirtyApp"] == 2 and stripped["dirtyAll"] == 2,
    )

    fails = [name for name, ok in checks if not ok]
    print(f"\n== 树戳自测：{len(checks) - len(fails)}/{len(checks)} 通过 ==")
    for name in fails:
        print(f"  - 失败：{name}")
    return 1 if fails else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(stamp_line())
