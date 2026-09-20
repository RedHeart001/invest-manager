# Invest Manager

个人投资理财助手。需求与设计见 [docs/PLAN.md](docs/PLAN.md)，执行进度见 [docs/PROGRESS.md](docs/PROGRESS.md)。

## 文档

| 文件 | 内容 |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | 需求与设计（单一来源）：R 需求、M1–M8 模块、实施阶段、配置项、验证方式、决策记录 |
| [docs/PROGRESS.md](docs/PROGRESS.md) | 执行进度账本：状态总览 + 倒序日志 + 阻塞与问题 |
| [docs/CONSTRAINTS.md](docs/CONSTRAINTS.md) | 改代码前必自查：C1–C34 约束、跨服务契约坑、数据源事实、部署约束 |
| [docs/CODE-REVIEW.md](docs/CODE-REVIEW.md) | 各轮代码审查发现了什么（只增不改）+ 轮次↔编号↔commit 对照表 |
| [docs/FIX-LEDGER.md](docs/FIX-LEDGER.md) | 每项修了没、怎么验的；未闭环看板置顶 |
| [docs/history/](docs/history/) | 归档：逐项做法、改动文件清单、一次性操作记录 |

## 结构

```
web/           Next.js（App Router + TS + Tailwind + Prisma/SQLite）
web/skills/    技能目录（Anthropic Agent Skills 格式：skills/<name>/SKILL.md）
web/mcp.json   第三方 MCP server 白名单（不自动安装）
data-service/  Python FastAPI（AkShare/OpenBB 数据适配层，无状态）
               app/mcp_server.py 把统一行情能力暴露为 MCP server
scripts/       容器冒烟脚本
```

## 本地启动

```bash
# 1) data-service（终端 1）
cd data-service
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
# 如需海外数据源（CoinGecko 加密行情，R12），先设置本地代理（按实际端口）：
set HTTPS_PROXY=http://127.0.0.1:7897             # cmd；PowerShell 用 $env:HTTPS_PROXY="http://127.0.0.1:7897"
.venv/Scripts/uvicorn app.main:app --port 8000

# 2) web（终端 2）
cd web
npm install
npx prisma migrate dev       # 首次运行建库
npm run dev                  # http://localhost:3000
```

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
cp .env.example .env         # 填 INGEST_TOKEN（openssl rand -hex 24）、LLM_*、TAVILY_API_KEY
docker compose build         # 首次约 10~20 分钟（npm ci + pip 依赖树）
docker compose up -d
node scripts/smoke.mjs       # 冒烟 5 项（BFF 四项 + 容器内 health）

docker compose ps            # 双服务应均为 healthy
docker compose logs -f web
docker compose down          # 停止（保留数据卷）
```

**要点**

| 项 | 说明 |
|---|---|
| 暴露面 | 仅 web（`${WEB_PORT:-3000}`）对外；data-service **不发布端口**，只在 compose 网络内可达 |
| 数据 | SQLite 存于命名卷 `prisma-data`（`docker compose down` 不会丢；`down -v` 才会） |
| 迁移 | web 容器入口自动 `prisma migrate deploy`（空卷首次启动即建库） |
| 时区 | TZ=Asia/Shanghai（APScheduler 盘前 08:30 / 盘后 16:30 不错时） |
| 密钥 | 一律经 `.env` 注入，不进镜像；`INGEST_TOKEN` 未设置时 compose 直接拒绝启动 |
| 镜像源 | docker.io 直连受限，默认走 `docker.m.daocloud.io` 前缀（可用 `NODE_IMAGE` / `PY_IMAGE` 覆盖） |
| 代理 | R12 海外源：`.env` 里设 `HTTPS_PROXY=http://host.docker.internal:<port>`；`NO_PROXY` 已含服务名 |

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

## 测试（双服务启动后运行）

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
.venv/Scripts/python tests/test_p6_mcp.py        # MCP server 工具暴露与降级（离线）
.venv/Scripts/python tests/test_p2_m8.py         # 多源降级与限速（离线）
```

注意：东财对短时高频请求限流（连接被重置），验收失败若为 502/空 K 线，先冷却几分钟再重试；测试脚本已内置节流与退避。

