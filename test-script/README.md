# test-script/

一次性/手工观测脚本（非自动化测试——自动化测试在 `data-service/tests/` 与 `web/lib/*.test.ts`）。

| 脚本 | 用途 | 来源 |
|---|---|---|
| `c0_sampler.py` | C0 实测采样器：每 60s 采 `/sync/status`（分类型耗时/令牌桶状态），同步完成后样本写入 `/tmp/c0_samples.json`。用于复测同步耗时基线 | 2026-09-25 C0 实测（CR7 批次 C） |

用法示例：

```bash
# 先启动双服务，触发同步（启动补跑或 POST /sync/run）后运行采样器
PYTHONIOENCODING=utf-8 python test-script/c0_sampler.py
```

纪律：本目录只放**只读观测**脚本；任何会写库/破坏性操作的脚本不得入内。
