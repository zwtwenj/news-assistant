#!/usr/bin/env bash
# 服务器端部署：load 镜像 → 迁移 → 拉起 → 验证。
# 前置：/opt/news-assistant 下有 news-images.tar、docker-compose.yml、nginx.conf、.env
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERROR: 缺少 .env（参照 .env.example 配置）" >&2
  exit 1
fi

echo "==> 加载镜像"
docker load -i news-images.tar

echo "==> 数据库迁移"
docker compose run --rm --no-deps web alembic upgrade head

echo "==> 拉起服务"
docker compose up -d

echo "==> 等待健康检查"
for i in $(seq 1 20); do
  if curl -fsS http://localhost:8080/healthz >/dev/null 2>&1; then
    echo "OK: http://localhost:8080/healthz"
    docker compose ps
    exit 0
  fi
  sleep 3
done
echo "WARN: healthz 未就绪，查看日志定位：" >&2
docker compose ps >&2
exit 1
