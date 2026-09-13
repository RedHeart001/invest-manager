#!/bin/sh
# web 容器入口：先应用数据库迁移（幂等），再启动应用。
# 空卷首次启动会自动建库（含手工迁移在内的全部迁移），实测验证通过。
set -e

echo "[entrypoint] DATABASE_URL=${DATABASE_URL:-<unset>}"
echo "[entrypoint] 应用 Prisma 迁移（migrate deploy）..."
./node_modules/.bin/prisma migrate deploy

echo "[entrypoint] 启动应用：$*"
exec "$@"
