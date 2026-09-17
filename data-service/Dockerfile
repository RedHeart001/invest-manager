# 投资理财助手 data-service（FastAPI + AkShare，无状态）生产镜像
# 构建：docker compose build data-service
# 构建参数对策（2026-09-12 骨架验证沉淀）：
#   - python:3.12-slim（与 requirements-lock.txt 生成环境一致），无状态（不写盘、不建库）
#   - **docker.io 直连在当前网络被拦截（auth 502）→ 默认走国内镜像前缀**，
#     如需换源：docker build --build-arg PY_IMAGE=<your-mirror>/library/python:3.12-slim
#   - pip 走阿里源 + --timeout 120 --retries 10（大包默认 15s 超时会断）
#   - 容器内必须绑 0.0.0.0（宿主侧才能通过 compose 网络访问）
#   - **Python 版本必须与锁文件一致**：本地开发 venv 为 3.12，故镜像用 3.12
#     （实测教训：3.11 镜像装 numpy==2.5.3 失败——该版本要求 Python ≥3.12）
#   - 依赖锁版本（requirements-lock.txt，**在容器内生成**），不含 tradingagents/OpenBB SDK

ARG PY_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
FROM ${PY_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tzdata 供 APScheduler 用 Asia/Shanghai 计算盘前/盘后时刻；ca-certificates 供出站 HTTPS
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
 && echo "Asia/Shanghai" > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖层：使用锁文件（可复现构建）；pip 缓存挂载让重复构建走本地 wheel 缓存
COPY requirements.txt requirements-lock.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 120 --retries 10 -r requirements-lock.txt

COPY app ./app
# 备份脚本（P7：sqlite3 在线备份，经 compose exec 调用）
COPY scripts ./scripts

# CR4（2026-09-15 review）：长驻网络服务进程不以 root 运行。
# 设计要点（不破坏既有实测链路）：
# - 容器默认用户保持 root → `compose exec` 备份/恢复行为不变（C22 已实测）；
# - 仅把 uvicorn 用 setpriv 降到 uid 1000 运行——与 web 容器 node 用户（uid 1000）
#   同号，共享卷 prisma-data 的 dev.db 归属不受影响（若用其它 uid 会导致 web 写库失败）；
# - data-service 无状态（不写盘），uid 1000 只需读 /app，无额外 chown；
# - setpriv 属 util-linux（Debian Essential，slim 镜像自带）；万一缺失则回退 root 直跑，
#   并打印告警——保证镜像在任何基线下可启动，不因加固而引入启动风险。
RUN useradd -r -u 1000 -m app 2>/dev/null || true

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=10s --start-period=40s --retries=5 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5).status==200 else 1)"

# 0.0.0.0：容器内监听（宿主机不直接发布端口，仅经 compose 网络供 web 调用）。
# 服务进程降权到 uid 1000（见上）；setpriv 缺失时回退 root 直跑并告警。
CMD ["sh", "-c", "if command -v setpriv >/dev/null 2>&1; then exec setpriv --reuid 1000 --regid 1000 --clear-groups uvicorn app.main:app --host 0.0.0.0 --port 8000; else echo '[warn] setpriv 缺失，回退 root 运行' >&2; exec uvicorn app.main:app --host 0.0.0.0 --port 8000; fi"]
