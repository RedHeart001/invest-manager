"""③ 实网回执的树戳（#78）：一份判据，两处出口——p0/p1 直接 import，④ 用 `--line` spawn 同一份。

为什么不复用 `test-script/window_lib`：它在 import 时就执行 `reconfigure(encoding="utf-8")`，而
CPython 会把没显式给的 `errors` 打回 `strict` ⇒ 反向 import 会把 CR9-14 给这两枚套件加的
`errors="replace"` 拆掉（那枚修复的由来是 GBK 控制台崩在用例名的 🔁 上）。本模块被 import 时对
stdout 不做任何事，reconfigure 只住在 `__main__` 分支里。

为什么比 epoch 而不是比 ISO 串：进程 StartTime 经 PowerShell 出来受控制台区域设置影响
（中文机器上是 `2026年10月13日 13:08:33`），拿去和 ISO 串按字符串比大小，`'-' < '年'` 恒成立
⇒ 装载判据在任何真实时序下都判"成立"＝常绿，10-13 18:1x 实测抓到过一次。整数对整数没有这一维。

为什么装载判据看**源码 mtime** 而不是提交时刻（#82，10-17 落）：本项目的工序是「改码→重启验证→
再提交」⇒ `git log -1 --format=%ct` 恒晚于进程 StartTime，拿它比是**必然假阴**（10-17 两次现场：
18:5x 与当晚 ④ 回执抬头都读 `装载=旧码`，而盘上 mtime 那枚读"成立"）。mtime 法对「改了不提交」与
「提交了没重启」两侧都读 `旧码`＝只会更严、不会变松。`appCommit` 仍照打：它说的是另一维（HEAD 是否
描述被测码，与 `dirtyApp` 配合读），不参与装载判定。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
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


def newest_app_mtime_epoch(root: Path | None = None) -> int | None:
    """app 源码 mtime 的 max（epoch 秒，递归全子树）。

    目录缺失／一枚 `.py` 都没有 ⇒ None（"读不出"），绝不兜底成 0——兜成 0 会让判据恒判"成立"。
    """
    base = REPO_ROOT / APP_PATHSPEC if root is None else root
    newest: int | None = None
    for path in base.rglob("*.py"):
        try:
            stamp = int(path.stat().st_mtime)
        except OSError:
            continue
        if newest is None or stamp > newest:
            newest = stamp
    return newest


def load_verdict(newest_mtime_epoch: int | None, ds_start_epoch: int | None) -> str:
    """三态字面（`成立／旧码／读不出`）一字不改：p0/p1 打印它、④ 把它抄进付费回执抬头。"""
    if newest_mtime_epoch is None or ds_start_epoch is None:
        return "读不出"
    return "成立" if ds_start_epoch >= newest_mtime_epoch else "旧码"


def iso(epoch: int | None) -> str:
    return datetime.fromtimestamp(epoch, BEIJING).isoformat(timespec="seconds") if epoch else "-"


def stamp_line(
    port: int = 8000,
    collect_fn=collect,
    start_fn=ds_start_epoch,
    mtime_fn=newest_app_mtime_epoch,
) -> str:
    """三枚读数可注入＝selftest 才钉得住"装载那一枚读的是 mtime 还是提交时刻"（#82 的牙齿）。"""
    c = collect_fn()
    start = start_fn(port)
    mtime = mtime_fn()
    return (
        f"树戳：HEAD={c['sha'] or '?'} dirty={c['dirtyAll']}/{c['dirtyApp']} "
        f"ds={iso(start)} appCommit={iso(c['appCommitEpoch'])} appMtime={iso(mtime)} "
        f"装载={load_verdict(mtime, start)}"
    )


def _selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def ck(name: str, cond) -> None:
        checks.append((name, bool(cond)))
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")

    ck("进程 StartTime 晚于 app 源码 mtime ⇒ 装载成立", load_verdict(1000, 2000) == "成立")
    ck("两半样本：交换大小必须翻回旧码（否则判据恒真）", load_verdict(2000, 1000) == "旧码")
    ck(
        "任一读数取不到 ⇒ 判读不出，绝不静默判成立",
        load_verdict(None, 5) == "读不出" and load_verdict(5, None) == "读不出",
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "sub").mkdir()
        empty = root / "empty"
        empty.mkdir()
        old_py, new_py = root / "a.py", root / "sub" / "b.py"
        old_py.write_text("x = 1\n", encoding="utf-8")
        new_py.write_text("y = 2\n", encoding="utf-8")
        os.utime(old_py, (1000, 1000))
        os.utime(new_py, (2000, 2000))
        ck("mtime 取的是全子树的 max（递归，不只顶层）", newest_app_mtime_epoch(root) == 2000)
        ck("目录不存在 ⇒ None（读不出，不兜底成 0）", newest_app_mtime_epoch(root / "nope") is None)
        ck("目录里一枚 .py 都没有 ⇒ 同样 None", newest_app_mtime_epoch(empty) is None)

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

    # 这两枚钉的是"抬头那一位到底读的是哪一枚数"：fake 的 appCommit=1700000000 远晚于 start=2000，
    # 谁把判据退回 `%ct` ⇒ 第一枚当场翻成旧码（＝#82 那枚必然假阴的回归样本）。
    header = stamp_line(collect_fn=lambda: collect(run=fake), start_fn=lambda port: 2000,
                        mtime_fn=lambda root=None: 1000)
    ck(
        "抬头的装载判据读 mtime、不读提交时刻（appCommit 晚于 start 也不许翻成旧码）",
        header.endswith("装载=成立") and "appMtime=" in header and "appCommit=" in header,
    )
    header2 = stamp_line(collect_fn=lambda: collect(run=fake), start_fn=lambda port: 2000,
                         mtime_fn=lambda root=None: 3000)
    ck("两半样本：mtime 晚于 StartTime ⇒ 抬头必须翻回旧码", header2.endswith("装载=旧码"))

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
