# test-script/

一次性/手工观测脚本（非自动化测试——自动化测试在 `data-service/tests/` 与 `web/lib/*.test.ts`）。

| 脚本 | 用途 | 来源 |
|---|---|---|
| `c0_sampler.py` | C0 实测采样器：每 60s 采 `/sync/status`（分类型耗时/令牌桶状态），同步完成后样本写入 `/tmp/c0_samples.json`。用于复测同步耗时基线 | 2026-09-25 C0 实测（CR7 批次 C） |
| `realtime_probe.py` | 实时源额度探针：对腾讯/新浪/东财/CoinGecko/Yahoo/币安各按固定间隔连发，输出成功率、P50/P95 耗时、字节数与解析形态。用于给「当日实时价格」轮询区定 N。**直连上游、不经 data-service ⇒ 不碰其令牌桶状态**；东财只发 10 次@6s 以落在自家 `rate_per_min=12` 护栏内 | 2026-09-27 批次七评估轮（CR9 追加九） |

用法示例：

```bash
# 先启动双服务，触发同步（启动补跑或 POST /sync/run）后运行采样器
PYTHONIOENCODING=utf-8 python test-script/c0_sampler.py

# 实时源探针：NO_PROXY 必须列出国内域名，否则国内源也会被代理接管 ⇒ 测的是代理不是上游
cd data-service && HTTPS_PROXY=http://127.0.0.1:<代理端口> \
  NO_PROXY="qt.gtimg.cn,ifzq.gtimg.cn,hq.sinajs.cn,push2.eastmoney.com" \
  ./.venv/Scripts/python.exe ../test-script/realtime_probe.py
```

纪律：本目录只放**只读观测**脚本；任何会写库/破坏性操作的脚本不得入内。
