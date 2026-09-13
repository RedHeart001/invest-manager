# 投资理财助手 web（Next.js + Prisma/SQLite）生产镜像
# 构建：docker compose build web
# 构建参数对策（2026-09-12 骨架验证沉淀）：
#   - 基础镜像 node:22-bookworm-slim（体积与 Prisma 兼容性均验证通过）
#   - **docker.io 直连在当前网络被拦截（auth 502）→ 默认走国内镜像前缀**，
#     如需换源：docker build --build-arg NODE_IMAGE=<your-mirror>/library/node:22-bookworm-slim
#   - npm 走 npmmirror，且必须给长超时（14 分钟下载曾被 ECONNRESET 打断）
#   - Prisma 引擎在 slim 镜像需 openssl（默认缺失会告警）

ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-bookworm-slim
FROM ${NODE_IMAGE} AS base
# 注意：base 阶段**不能**设 NODE_ENV=production —— 否则 npm ci 会跳过
# devDependencies，而 @tailwindcss/postcss（构建必需）与 prisma CLI（运行时
# migrate deploy 必需）都在 devDependencies 里。NODE_ENV 只在 runner 阶段设置。
ENV TZ=Asia/Shanghai \
    NEXT_TELEMETRY_DISABLED=1
# Prisma 引擎依赖 openssl；ca-certificates 供出站 HTTPS
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# ---------- 依赖层（单独一层，源码改动不触发重装） ----------
FROM base AS deps
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --registry=https://registry.npmmirror.com \
           --fetch-retry-maxtimeout=120000 --fetch-timeout=600000

# ---------- 构建层：prisma generate + next build ----------
FROM deps AS build
COPY . .
RUN npx prisma generate && npm run build && rm -rf .next/cache

# ---------- 运行层 ----------
FROM base AS runner
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
# 复制构建产物后裁掉 devDependencies（L2：prisma 已移入 dependencies，
# migrate deploy 所需的 prisma CLI 保留，体积 1.62GB → 约 0.9GB）
COPY --from=build /app/node_modules ./node_modules
RUN npm prune --omit=dev
COPY --from=build /app/.next ./.next
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.ts ./next.config.ts
COPY --from=build /app/prisma ./prisma
# P6 产物：技能目录与 MCP 白名单必须随镜像分发
COPY --from=build /app/skills ./skills
COPY --from=build /app/mcp.json ./mcp.json
COPY --from=build /app/scripts ./scripts

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# 防御性处理：若检出时被写成 CRLF，去掉 \r 以免 exec 失败（.gitattributes 已锁 LF）
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
 && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
 && mkdir -p /app/data && chown -R node:node /app/data

# 以非 root 运行（SQLite 数据目录已授权）
USER node

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=10s --start-period=40s --retries=5 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["npm", "start"]
