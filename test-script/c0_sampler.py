"""C0 采样器（只读观测，不改任何代码/数据）。

每 60s 采一次 /sync/status，直到同步完成（running=False 且 runs>=1）或超时 40 分钟。
样本写入 /tmp/c0_samples.json。

运行：PYTHONIOENCODING=utf-8 python scripts/c0_sampler.py
"""

import json
import time
import urllib.request
from datetime import datetime


def main() -> None:
    samples = []
    deadline = time.time() + 40 * 60
    while time.time() < deadline:
        try:
            d = json.loads(urllib.request.urlopen("http://localhost:8000/sync/status", timeout=10).read())
            ts = datetime.now().strftime("%H:%M:%S")
            lr = d.get("lastResult") or {}
            results = lr.get("results") or {}
            per = {k: v.get("tookMs") for k, v in results.items()} if isinstance(results, dict) else results
            samples.append(
                {
                    "t": ts,
                    "running": d.get("running"),
                    "runs": d.get("runs"),
                    "tookMs": lr.get("tookMs"),
                    "per": per,
                    "error": lr.get("error"),
                }
            )
            print(
                f"{ts} running={d.get('running')} runs={d.get('runs')} "
                f"tookMs={lr.get('tookMs')} per={per} err={lr.get('error')}",
                flush=True,
            )
            if not d.get("running") and d.get("runs", 0) >= 1:
                print(">>> 同步完成，采样结束", flush=True)
                break
        except Exception as e:  # noqa: BLE001
            print(datetime.now().strftime("%H:%M:%S"), "sample error:", e, flush=True)
        time.sleep(60)

    with open("/tmp/c0_samples.json", "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=1)
    print("samples saved:", len(samples))


if __name__ == "__main__":
    main()
