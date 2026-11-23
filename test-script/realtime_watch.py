#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""盘中实时行情监听器：只读经 web BFF 取实时价，逐轮落 JSONL。

用法：
    python test-script/realtime_watch.py --once
    python test-script/realtime_watch.py --interval 60 --max-rounds 30

口径（不另造规则，全部对着代码现查）：
- 只发 `GET /api/realtime?type=&code=&parts=`（`web/app/api/realtime/route.ts`），
  即详情页那条同一腿；不经 data-service 直连上游，所以 `realtime-obs` 桶账是真账。
- 腿的节律照 `web/lib/realtime.ts` 的 `partsForTick`：每 6 跳才问一次分时
  （`INTRADAY_EVERY_TICKS`），其余跳只问现价。间隔默认 60s，**不压到 TTL 以下**。
- 只在**该市场自己的钟**开着时发：A股/场内基金＝北京 09:30–11:30、13:00–15:00；
  港股＝香港 09:30–12:00、13:00–16:00；美股＝美东 09:30–16:00；加密 24/7。
  非交易时段零请求是既有规则（`RealtimeStrip` 同一条），闭市标的本件跳过不发。
- 出网自证：每轮前后取容器内 `limiter-state.json` 的 `granted` 增量（只读
  `docker compose exec`）。某轮 200 但增量全 0 ⇒ 可能是 TTL 回声，标 `egress=null`
  而不是写 1（`window_a3.py` 那一形）。`--no-bucket-probe` 关掉。
- 反向自证（默认随 `--once` 跑一发）：`parts` 写成不存在的腿 ⇒ 预期 400，
  证明入参成对校验真在生效；这一发是本地 400，不出网。

本件不改任何代码、不写库、不碰正式卷，读数是**本机 dev 副本**，不是自然验收证据。
"""
from __future__ import annotations

import argparse
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
from zoneinfo import ZoneInfo

for stream in (sys.stdout, sys.stderr):  # 上游 note 里有 ⇒／中文，GBK 控制台会直接崩（同 watch-formal-e-natural.py）
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
TZ_BJ = ZoneInfo("Asia/Shanghai")
INTRA_EVERY = 6  # 与 web/lib/realtime.ts 的 INTRADAY_EVERY_TICKS 同值
DEFAULT_SUBJECTS = ["stock:600519", "stock:000001", "fund:510300", "hk:00700", "us:AAPL", "crypto:BTC"]

# (时区, 开市区间) —— None＝该市场连续交易
SESSIONS = {
    "stock": ("Asia/Shanghai", [(timedelta(hours=9, minutes=30), timedelta(hours=11, minutes=30)),
                                (timedelta(hours=13), timedelta(hours=15))]),
    "fund": ("Asia/Shanghai", [(timedelta(hours=9, minutes=30), timedelta(hours=11, minutes=30)),
                               (timedelta(hours=13), timedelta(hours=15))]),
    "bond": ("Asia/Shanghai", [(timedelta(hours=9, minutes=30), timedelta(hours=11, minutes=30)),
                               (timedelta(hours=13), timedelta(hours=15))]),
    "hk": ("Asia/Hong_Kong", [(timedelta(hours=9, minutes=30), timedelta(hours=12)),
                              (timedelta(hours=13), timedelta(hours=16))]),
    "us": ("America/New_York", [(timedelta(hours=9, minutes=30), timedelta(hours=16))]),
    "crypto": (None, None),
}


def market_open(mtype: str, now_utc: datetime) -> bool:
    spec = SESSIONS.get(mtype)
    if spec is None:
        return False
    tzname, spans = spec
    if tzname is None:
        return True
    local = now_utc.astimezone(ZoneInfo(tzname))
    if local.weekday() >= 5:
        return False
    clock = local - local.replace(hour=0, minute=0, second=0, microsecond=0)
    return any(a <= clock < b for a, b in spans)


def get_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body[:200]}
        return e.code, payload
    except Exception as e:  # 连不上／超时：如实记，不重试成"看起来在跑"
        return None, {"error": f"{type(e).__name__}: {e}"}


def bucket_state() -> dict | None:
    """容器内 limiter 账（只读）。取不到就交 None，不猜。

    盘上形状是 `{"day": ..., "days": {"<day>": {"<family>": {...}}}}`；
    `realtime-obs` 是纯观测族，`granted` 恒 0，出网证据在 `seenTotal`／`seen` 上，
    所以三个计数都取，别把"观测族不计 granted"读成"没出网"。
    """
    try:
        p = subprocess.run(
            ["docker", "compose", "exec", "-T", "data-service", "cat", "/data/runtime/limiter-state.json"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        if p.returncode != 0:
            return None
        data = json.loads(p.stdout)
        day = data.get("day")
        fams = (data.get("days") or {}).get(day) or {}
    except Exception:
        return None
    out = {}
    for name, st in fams.items():
        if isinstance(st, dict):
            out[name] = {"granted": st.get("granted"), "denied": st.get("denied"),
                         "seenTotal": st.get("seenTotal")}
    return out or None


def one_round(base: str, subjects: list[str], tick: int) -> list[dict]:
    parts = "price,intraday" if tick % INTRA_EVERY == 0 else "price"
    now_utc = datetime.now(timezone.utc)
    rows = []
    for subj in subjects:
        mtype, _, code = subj.partition(":")
        if not code or not market_open(mtype, now_utc):
            continue
        q = urllib.parse.urlencode({"type": mtype, "code": code, "parts": parts})
        t0 = time.monotonic()
        status, payload = get_json(f"{base}/api/realtime?{q}")
        row = {
            "ts": now_utc.astimezone(TZ_BJ).isoformat(timespec="seconds"),
            "tick": tick,
            "parts": parts,
            "type": mtype,
            "code": code,
            "http": status,
            "elapsedMs": round((time.monotonic() - t0) * 1000),
        }
        if status == 200 and isinstance(payload, dict):
            price = payload.get("price") or {}
            intra = payload.get("intraday") or {}
            row.update({
                "price": price.get("price"),
                "changePct": price.get("changePct"),
                "quoteSource": price.get("source"),
                "quoteTs": price.get("timestamp"),
                "intradayDate": intra.get("date"),
                "intradayBars": intra.get("bars"),
                "intradaySource": intra.get("source"),
                "hasTodayData": payload.get("hasTodayData"),
                "intradayDateIsToday": payload.get("intradayDateIsToday"),
                "crossChecked": payload.get("crossChecked"),
                "verifyVerdict": payload.get("verifyVerdict"),
                "consensus": (payload.get("consensus") or {}).get("verdict"),
                "provisional": (payload.get("consensus") or {}).get("provisional"),
                "degraded": payload.get("degraded"),
                "note": payload.get("note"),
                "legs": [{"kind": l.get("kind"), "source": l.get("source"), "ok": l.get("ok"),
                          "latencyMs": l.get("latencyMs"), "detail": l.get("detail")}
                         for l in (payload.get("sources") or [])],
            })
        else:
            row["error"] = (payload or {}).get("error") if isinstance(payload, dict) else str(payload)[:200]
        rows.append(row)
    return rows


def negative_probe(base: str) -> dict:
    """反向自证：不存在的腿必须被 400 挡在出网之前。"""
    q = urllib.parse.urlencode({"type": "stock", "code": "600519", "parts": "price,no_such_leg"})
    status, payload = get_json(f"{base}/api/realtime?{q}")
    return {"event": "negative_probe", "expect": 400, "got": status, "error": (payload or {}).get("error")}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:3000")
    ap.add_argument("--codes", default=",".join(DEFAULT_SUBJECTS), help="逗号分隔的 type:code 清单")
    ap.add_argument("--interval", type=float, default=60.0, help="两轮之间秒数（≥ 分时原生粒度，不压 TTL）")
    ap.add_argument("--max-rounds", type=float, default=1e9)
    ap.add_argument("--once", action="store_true", help="只跑一轮，并做一发反向自证")
    ap.add_argument("--no-bucket-probe", action="store_true", help="不取容器内 limiter 账")
    ap.add_argument("--out", default=str(ROOT / "data-service" / "runtime" / f"realtime-watch-{datetime.now(TZ_BJ):%Y%m%d}.jsonl"))
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    subjects = [s.strip() for s in args.codes.split(",") if s.strip()]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def emit(obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        print(line, flush=True)
        with out.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    emit({"event": "start", "base": args.base, "subjects": subjects, "interval": args.interval,
          "out": str(out), "note": "本机 dev 副本读数，不是自然验收证据"})
    if args.once:
        emit(negative_probe(args.base))

    prev = None if args.no_bucket_probe else bucket_state()
    max_rounds = 1 if args.once else args.max_rounds
    tick = 0
    try:
        while tick < max_rounds:
            open_now = [s for s in subjects if market_open(s.partition(":")[0], datetime.now(timezone.utc))]
            if not open_now:
                emit({"event": "idle", "tick": tick, "reason": "所有标的所在市场均未开市（非交易时段零请求）"})
            else:
                for row in one_round(args.base, open_now, tick):
                    emit(row)
            if not args.no_bucket_probe:
                cur = bucket_state()
                deltas = {}
                if cur and prev:
                    for fam, st in cur.items():
                        p = prev.get(fam, {})
                        deltas[fam] = {k: (st.get(k) or 0) - (p.get(k) or 0) for k in ("granted", "denied", "seenTotal")}
                    moved = any(v["granted"] > 0 or v["seenTotal"] > 0 for v in deltas.values())
                emit({"event": "bucket_delta", "tick": tick, "deltas": deltas,
                      "egress": moved if deltas else None})
                prev = cur
            tick += 1
            if tick < max_rounds:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        emit({"event": "interrupted", "ticks": tick})
        return 130
    emit({"event": "finished", "ticks": tick})
    return 0


if __name__ == "__main__":
    sys.exit(main())
