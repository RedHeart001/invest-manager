"""10-13 实网窗口的共享执行件：保险丝／节律／硬上限／严格取键／回执落盘。

为什么把散文字变成码（任务书 `docs/history/2026-10-13-丙-实网窗口任务书.md:30` 那两条）：
1. 「`cooldown>0` ⇒ 立刻停」「连续 2 发非 200 ⇒ 当场停」此前只写在纸上，到场时靠人记着；
   本件让**每次请求之前自己读 `/health` 判定**，停手原因落盘，不依赖到场那时刻的记性。
2. 10-08 那一窗真正的失效是「采集器读错键 ⇒ ④ 只剩 note 文本」——所以取键一律走
   `require_keys()`：缺键就抛 `SchemaDrift` 并把**实际有哪些键**记进回执，
   绝不静默回落到 note 文案（note 是给人读的，不是判据）。

口径来源（全部按盘上原文抄，别处改了我读不到）：
- `/health` 的 `limiters`＝`snapshot_all()` → 各族 `state()` 的**列表**：
  `data-service/app/main.py:112` ⇔ `data-service/app/utils/limiter.py:80-95`
  （键名 `name/cooldown/consecutiveFailures/granted/denied/seen/seenTotal`）。
- `verifyVerdict` 三态：`data-service/app/providers/chain.py:118-125`。
- ④ 的排除口径：note 含「主源不可用，已降级至」那几发测的是降级不是共识；
  `no_second_source` 不进分母（FIX-LEDGER「OPT-3」行 10-08 10:1x 段）。

只连 127.0.0.1，零第三方依赖；对回环地址**强制不走代理**——Windows 上 urllib 会读注册表
系统代理，代理接不住 127.0.0.1，报出来的 ProxyError 是我的机器、不是上游（同族口径见
CONSTRAINTS §C-4 加密那行的 ProxyError/RemoteDisconnected 之分）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # CR9-14：脚本自带 UTF-8 输出（GBK 控制台）

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = REPO_ROOT / "data-service" / "runtime"
DS_BASE = os.environ.get("DS_URL", "http://127.0.0.1:8000").rstrip("/")
BEIJING = timezone(timedelta(hours=8))

# 每个类型的主源是谁（照注册行抄：stock/fund/bond=akshare 即东财、hk=东财直连、
# us=openbb 即 yfinance、crypto=CoinGecko）⇒ 保险丝只在"这一发确实要过东财桶"时看东财。
EASTMONEY_FAMILIED_TYPES = {"stock", "fund", "bond", "hk"}
VERDICTS = ("agree", "diverged", "no_second_source")
DEGRADE_MARKER = "主源不可用，已降级至"


class FuseStop(RuntimeError):
    """保险丝判定该停手——调用方不得重试、不得换写法。"""


class SchemaDrift(RuntimeError):
    """响应里缺我要的键——把实际键面一起抛出，供回执记录。"""


class NoProxyOpener:
    """回环地址的直连 opener。"""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, url: str, params: dict[str, Any], timeout: float = 30.0):
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        full = f"{url}?{query}" if query else url
        req = urllib.request.Request(full, headers={"User-Agent": "window-probe/1"})
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:  # URLError / 超时 / 连接被拒：一律原样带上异常类型
            return None, f"{type(e).__name__}: {e}"


def http_json(opener: NoProxyOpener, path: str, params: dict[str, Any] | None = None,
              timeout: float = 30.0):
    """→ (status, parsed_dict | raw_text | None, error | None)。非 2xx 不抛，交回调用方计数。

    `timeout`＝单条探针自己的客户端预算（默认与 `NoProxyOpener.get` 同值＝30s）。
    只有 `/products` 需要抬：ds 侧那条 A 股全量名单走 `ak.stock_zh_a_spot` 的 120s 看门狗，
    30s 等不到它答完＝结构上采不到（10-19 00:29 实测 `TimeoutError`，成本已付）。
    """
    status, body = opener.get(DS_BASE + path, params or {}, timeout=timeout)
    if status is None:
        return None, None, body
    try:
        return status, json.loads(body), None
    except json.JSONDecodeError:
        return status, None, f"non-json body: {body[:200]}"


def require_keys(obj: dict, keys: tuple[str, ...], *, where: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        have = ",".join(sorted(obj.keys()))
        raise SchemaDrift(f"{where} 缺键 {missing}｜实际键面＝[{have}]")


# ---------- /health 读数 ----------


def read_health(opener: NoProxyOpener) -> dict:
    status, body, err = http_json(opener, "/health")
    if err or not isinstance(body, dict):
        raise FuseStop(f"/health 读不到（status={status} err={err}）⇒ 服务不在场，不发任何请求")
    return body


def families_of(health: dict) -> dict[str, dict]:
    """`limiters` 是列表（按族名排序），这里转成 name→state 好取值。"""
    rows = health.get("limiters")
    if not isinstance(rows, list):
        return {}
    return {r.get("name", "?"): r for r in rows if isinstance(r, dict)}


def limiter_digest(health: dict) -> dict:
    """回执里要的几眼数：东财桶 + 落盘那本账 + 备份 + 版本。"""
    fam = families_of(health)
    em = fam.get("eastmoney", {})
    window = health.get("limitersWindow") or {}
    backup = health.get("dbBackup") or {}
    return {
        "version": health.get("version"),
        "eastmoneyCooldown": em.get("cooldown"),
        "eastmoneyGranted": em.get("granted"),
        "eastmoneyDenied": em.get("denied"),
        "eastmoneyConsecutiveFailures": em.get("consecutiveFailures"),
        "familiesPresent": sorted(fam.keys()),
        "durableToday": health.get("limitersDurable"),
        "coveredDays": window.get("coveredDays"),
        "keptDays": window.get("keptDays"),
        "dbBackup": {k: backup.get(k) for k in ("lastRun", "nextRun", "lastError", "fromDisk")},
    }


# ---------- 保险丝 / 节律 / 上限 ----------


class Fuse:
    """两条停手判据（任务书 :30）＋一条硬上限，编码成每次发之前必过的一关。"""

    def __init__(
        self,
        opener: NoProxyOpener,
        *,
        max_requests: int,
        watch_eastmoney: bool = True,
        health_provider=None,
    ):
        # health_provider 是给自测留的注入口（自测不许连网络，也不许假装有服务）
        self.opener = opener
        self.max_requests = max_requests
        self.watch_eastmoney = watch_eastmoney
        self._health = health_provider or (lambda: read_health(self.opener))
        self.sent = 0
        self.consecutive_non200 = 0
        self.stopped_reason: str | None = None
        self.eastmoney_family_absent: bool | None = None
        self.last_digest: dict | None = None

    def check(self) -> None:
        if self.stopped_reason:
            raise FuseStop(self.stopped_reason)
        if self.sent >= self.max_requests:
            raise FuseStop(f"已达硬上限 max_requests={self.max_requests}，不再多发一发")
        if self.consecutive_non200 >= 2:
            self.stopped_reason = f"连续 {self.consecutive_non200} 发非 200 ⇒ 当场停"
            raise FuseStop(self.stopped_reason)
        if self.watch_eastmoney:
            health = self._health()
            digest = limiter_digest(health)
            self.last_digest = digest
            # 族桶是**懒创建**的（`snapshot_all()` 只列已注册族，limiter.py:485-493）：
            # 全新进程还没打过东财 ⇒ 列表里没有 eastmoney，此时 cooldown 定义上就是 0，
            # 不能因为"读不到"而把整窗锁死（那就成了"不发请求才安全"的死循环）。
            # 但 **`limiters` 这一位整键缺失**是另一回事＝进程装的是 #27 之前的旧码 ⇒ 必须停。
            if "limiters" not in health:
                self.stopped_reason = "/health 没有 `limiters` 这一位 ⇒ 装的是 #27 之前的旧码，停手"
                raise FuseStop(self.stopped_reason)
            if "eastmoney" not in digest["familiesPresent"]:
                self.eastmoney_family_absent = True
                return
            self.eastmoney_family_absent = False
            cd = digest["eastmoneyCooldown"]
            if isinstance(cd, (int, float)) and cd > 0:
                self.stopped_reason = f"东财桶 cooldown={cd}s > 0 ⇒ 立刻停、不重试"
                raise FuseStop(self.stopped_reason)

    def record(self, status: int | None) -> None:
        self.sent += 1
        self.consecutive_non200 = 0 if status == 200 else self.consecutive_non200 + 1


class Pacer:
    """同发间隔下界。自测/演练时 allow_sleep=False ⇒ 只报"还差几秒"，不真睡（省时且可测）。"""

    def __init__(self, min_seconds: float, *, allow_sleep: bool = True, clock=time.monotonic):
        self.min_seconds = min_seconds
        self.allow_sleep = allow_sleep
        self._clock = clock
        self._last: float | None = None

    def wait(self) -> float:
        if self._last is None:
            self._last = self._clock()
            return 0.0
        elapsed = self._clock() - self._last
        need = self.min_seconds - elapsed
        if need > 0:
            if self.allow_sleep:
                print(f"    …节律等待 {need:.1f}s（同发间隔下界 {self.min_seconds}s）")
                time.sleep(need)
            else:
                return need
        self._last = self._clock()
        return 0.0


# ---------- 树戳与装载证据（⑤ 那一形：改动对无 --reload 的进程不可见）----------


def run(cmd: list[str], timeout: float = 8.0) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=REPO_ROOT)
        return (out.stdout or "").strip() or (out.stderr or "").strip()
    except Exception as e:
        return f"<{type(e).__name__}>"


def git_stamp() -> dict:
    sha = run(["git", "rev-parse", "HEAD"])
    dirty = run(["git", "status", "--porcelain"])
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return {
        "sha": sha.splitlines()[0] if sha and not sha.startswith("<") else None,
        "dirtyPaths": len(dirty.splitlines()) if dirty and not dirty.startswith("<") else 0,
        "branch": branch.splitlines()[0] if branch and not branch.startswith("<") else None,
    }


def listening_endpoint(port: int) -> dict:
    """读-only 查监听：PID 与进程 StartTime，再与关键源文件的 mtime 比——
    mtime > StartTime ⇒ 进程装的是**旧**码（CR9-24 那一形），这一发读数就不能当新码的凭据。"""
    info: dict[str, Any] = {"port": port, "listening": False}
    try:
        with socket_connect_test(("127.0.0.1", port), 0.7):
            info["listening"] = True
    except OSError as e:
        info["connectError"] = e.strerror or type(e).__name__
        return info
    if os.name != "nt":
        info["pidNote"] = "非 Windows，跳过 PID/StartTime 取证"
        return info
    ps = (
        f"$p=(Get-NetTCPConnection -LocalPort {port} -State Listen "
        "| Select-Object -First 1 -Expand OwningProcess);"
        # 格式必须钉死成 ISO（`ToString('s')`）。裸取 `StartTime` 走控制台区域设置，中文机器上给的是
        # `2026年10月13日 13:08:33`——拿去和 ISO 的 mtime 按字符串比大小，`'-' < '年'` 恒成立，
        # 于是"装载证据"这一档在任何真实时序下都判"成立"＝常绿（10-13 18:1x 实测抓到）。
        "Get-Process -Id $p | ForEach-Object { $_.StartTime.ToString('s') }"
    )
    started = run(["powershell", "-NoProfile", "-Command", ps], timeout=15)
    info["processStartTime"] = started.splitlines()[0] if started else None
    return info


class socket_connect_test:
    def __init__(self, addr, timeout: float):
        import socket

        self._sock = socket.socket()
        self._sock.settimeout(timeout)
        self._addr = addr

    def __enter__(self):
        self._sock.connect(self._addr)
        return self._sock

    def __exit__(self, *exc):
        self._sock.close()
        return False


def source_freshness(paths: list[str]) -> list[dict]:
    """给装载证据用的另一半：这些文件的 mtime（与 processStartTime 比大小）。"""
    out = []
    for p in paths:
        f = REPO_ROOT / p
        out.append(
            {
                "path": p,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime, BEIJING).isoformat(timespec="seconds")
                if f.exists()
                else None,
            }
        )
    return out


# ---------- 回执 ----------


class Receipt:
    """JSONL 逐条落 `data-service/runtime/`（`.gitignore:48` 整目录挡住，故永不入库）。"""

    def __init__(self, name: str, *, dry: bool):
        self.name = name
        self.dry = dry
        self.lines: list[dict] = []
        self.path = RUNTIME_DIR / f"{name}-{datetime.now(BEIJING):%m%d-%H%M}.jsonl"

    def add(self, rec: dict) -> None:
        rec = {
            "atBeijing": datetime.now(BEIJING).isoformat(timespec="seconds"),
            "git": git_stamp(),
            **rec,
        }
        self.lines.append(rec)
        print(f"  [{len(self.lines)}] {json.dumps(rec, ensure_ascii=False, default=str)[:420]}")
        if not self.dry:
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def finish(self, summary: dict) -> None:
        if self.dry:
            print(f"\n[dry-run] {self.name}：演练 {len(self.lines)} 条，未落盘、未出网")
            return
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        out = self.path.with_suffix(".summary.out")
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"\n回执：{self.path.name}（{len(self.lines)} 条）＋ {out.name}")


def beijing_today() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")
