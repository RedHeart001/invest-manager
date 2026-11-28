# Invest Manager

个人投资理财助手。需求与设计见 [docs/PLAN.md](docs/PLAN.md)，执行进度见 [docs/PROGRESS.md](docs/PROGRESS.md)。

## 文档

| 文件 | 内容 |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | 需求与设计（单一来源）：R 需求、M1–M8 模块、实施阶段、配置项、验证方式、决策记录 |
| [docs/PROGRESS.md](docs/PROGRESS.md) | 执行进度账本：状态总览 + 倒序日志 + 阻塞与问题 |
| [docs/CONSTRAINTS.md](docs/CONSTRAINTS.md) | 改代码前必自查：C1–C41 约束、跨服务契约坑、数据源事实、部署约束 |
| [docs/CODE-REVIEW.md](docs/CODE-REVIEW.md) | 各轮代码审查发现了什么（只增不改）+ 轮次↔编号↔commit 对照表 |
| [docs/FIX-LEDGER.md](docs/FIX-LEDGER.md) | 每项修了没、怎么验的；未闭环看板置顶 |
| [docs/history/](docs/history/) | 归档：逐项做法、改动文件清单、一次性操作记录 |

> **约束计数口径**：C1–C34 按来源审查轮次分五批；C35～C36 是 CR10 的两条跨层发现（传输层上限必须高于业务预算、外部名单业务键唯一性是假设）；C37～C41 是 11-27／11-28 的同步与出网系列（按源族出网、名单唯一可发布源 fail-closed、补试有界、`collecting` 非终态与失败上屏、运行态持久化与恢复优先级）⇒ 现读 **C1–C41**（见 [docs/CONSTRAINTS.md](docs/CONSTRAINTS.md)）。另：`web/instrumentation.ts` 是 Next 启动钩子（只装 undici 传输层上限），`pnpm dev`／`next build` 自动加载，**不需要**改启动命令。

## 结构

```
web/           Next.js（App Router + TS + Tailwind + Prisma/SQLite）
web/skills/    技能目录（Anthropic Agent Skills 格式：skills/<name>/SKILL.md）
web/mcp.json   第三方 MCP server 白名单（不自动安装）
data-service/  Python FastAPI（AkShare/OpenBB 数据适配层，不写业务库；运行态落 runtime/）
               app/mcp_server.py 把统一行情能力暴露为 MCP server
scripts/       容器冒烟脚本
```

## 本地启动

> **顺序是「先 web、后 ds」**：ds 启动约 5s 后热点补跑要 `GET` web 的 `/api/hotspots/ingest`，**web 不在**时当天热点补跑直接跳过，且该进程不再重试（当天热点就丢了）。
> 权威配方见 [docs/README.md](docs/README.md) 的「常用命令」。ds 侧四条必要条件：`SYNC_CATCHUP=off`（只关启动补跑，不影响每日 cron）、`PYTHONPATH=.`、解释器用 `.venv/Scripts/python.exe`、**不带** `--reload`；**不要手设** `NO_PROXY`。

```bash
# 1) web（终端 1）—— 必须先起
cd web
npm install
npx prisma migrate dev       # 首次运行建库
npm run dev                  # http://localhost:3000

# 2) data-service（终端 2）
cd data-service
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt          # Windows
SYNC_CATCHUP=off PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# PowerShell 写法：
#   $env:SYNC_CATCHUP="off"; $env:PYTHONPATH="."
#   .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

> **代理只在需要海外源时才配，且不做全局代理**：海外源（CoinGecko／yfinance／Tavily／HKEX）读 `HTTPS_PROXY`／`HTTP_PROXY`，未配时按直连尝试；国内源与容器间调用一律显式直连，不依赖 `NO_PROXY` 是否写得全（`data-service/app/utils/http.py`）。当前仓库的代理值保持为空，海外源直连实测可用；要配就写进 `data-service/.env`（`config.py` 会加载），**不要**在 shell 里 export 成全局代理。

### MCP（P6，可选）

```bash
# 本项目的行情能力对外暴露为 MCP server（只读）
cd data-service
.venv/Scripts/python -m app.mcp_server            # stdio（供 Claude Code 等本地客户端）
.venv/Scripts/python -m app.mcp_server --http     # 仅 127.0.0.1:8765（streamable-http）

# Tool Gateway 状态（内置工具 / 技能 / MCP 连接与降级）
curl http://localhost:3000/api/tools/status
```

> 第三方 MCP server 走 `web/mcp.json` 白名单：只连接其中声明的 server，**不自动安装**任何东西；
> 密钥用 `${ENV_VAR}` 占位注入，不写进配置。连接失败只降级为"该源工具不可用"，不影响对话。
> **依赖约束**：`fastmcp` 必须锁 `<3`（4.x 依赖 starlette>=1.0.1，与 FastAPI 的 starlette<0.51 冲突，会导致 data-service 起不来）。

## 容器化部署（P7）

```bash
cp .env.example .env         # 填 INGEST_TOKEN / WRITE_TOKEN、LLM_*、TAVILY_API_KEY
docker compose build         # 首次约 10~20 分钟（npm ci + pip 依赖树）
docker compose up -d
node scripts/smoke.mjs       # 冒烟 6 段 / 基础 7 条断言（库内已同步时 8 条）；详见脚本抬头

docker compose ps            # 双服务应均为 healthy
docker compose logs -f web
docker compose down          # 停止（保留数据卷）
```

**要点**

| 项 | 说明 |
|---|---|
| 暴露面 | 仅 web 绑定回环 `127.0.0.1:${WEB_PORT:-3000}`；data-service **不发布端口**，只在 compose 网络内可达 |
| 数据 | SQLite 存于命名卷 `prisma-data`（`docker compose down` 不会丢；`down -v` 才会） |
| 迁移 | web 容器入口自动 `prisma migrate deploy`（空卷首次启动即建库） |
| 时区 | TZ=Asia/Shanghai（APScheduler 盘前 08:30 / 盘后 16:30 不错时） |
| 密钥 | 一律经 `.env` 注入，不进镜像；`INGEST_TOKEN` / `WRITE_TOKEN` 未设置或为空时 compose 拒绝启动 |
| 镜像源 | docker.io 直连受限，默认走 `docker.m.daocloud.io` 前缀（可用 `NODE_IMAGE` / `PY_IMAGE` 覆盖） |
| 代理 | R12 海外源：需要代理时在 `.env` 里设 `HTTPS_PROXY=http://host.docker.internal:<port>`；**容器内代理只作用于海外源，国内源与容器间调用走显式直连**，不靠 `NO_PROXY` 兜底（当前代理值为空，海外源按直连尝试） |

**MCP HTTP（可选 profile）**

```bash
docker compose --profile mcp up -d     # 宿主机 127.0.0.1:8765 可访问（仅本机）
```

**数据库备份 / 恢复**（SQLite 在线备份 API，WAL 安全，无需停服）

```bash
docker compose exec -T data-service python -m scripts.backup_db            # 备份到 ./backups
docker compose exec -T data-service python -m scripts.backup_db --list     # 列出备份
docker compose stop web                                                    # 恢复前停应用
docker compose exec -T data-service python -m scripts.backup_db --restore /backup/dev-<时间戳>.db
docker compose start web
```

> 提示：data-service 须在**自己的终端**前台启动（WorkBuddy 等 Agent 工具的后台沙箱会改写代理环境变量并拦截境外连接，导致 R12 海外源失效——国内源不受影响）。

## 配置

复制 `web/.env.example` 为 `web/.env`；LLM/搜索 API key 按阶段启用（见 [docs/PLAN.md](docs/PLAN.md) 配置项）。

## 测试

**离线门禁（不需要起服务、零出网）**：

```bash
node scripts/gate.mjs            # 一条命令跑完：tsc --noEmit／vitest／ds 离线逐套／docs 闸
node scripts/gate.mjs --offline  # 同上，显式标注离线
```

抬头会写它对着哪一棵树与已跟踪 diff；回执落在 `data-service/runtime/gate1-*.out`。**③④ 要买上游额度，不在这一条里**（定档＝人工到场）。

**双服务启动后运行的验收脚本**：

```bash
cd web
npm test                        # vitest 单测（打分/分词/阶段划分/画像/事件/技能加载/MCP/网关）
node scripts/test-db.mjs        # 数据库结构断言
node scripts/test-p1.mjs        # P1 搜索验收
node scripts/test-p2.mjs        # P2 详情页验收（K线/缓存/R13 交叉验证/六区 SSR）
node scripts/test-p3.mjs        # P3 热点 dashboard 验收
node scripts/test-p4.mjs        # P4 统一 Agent 验收
node scripts/test-p5.mjs        # P5 深度研究验收
node scripts/test-p6.mjs        # P6 Skills + MCP 验收（需 web + data-service 在跑）
cd ../data-service
.venv/Scripts/python tests/test_p6_mcp.py        # MCP 工具暴露/降级；含真实报价请求，须授权后单独运行（非离线）
.venv/Scripts/python tests/test_p2_m8.py         # 多源降级与限速（离线）
```

注意：东财对短时高频请求限流（连接被重置），验收失败若为 502/空 K 线，先冷却几分钟再重试；测试脚本已内置节流与退避。

