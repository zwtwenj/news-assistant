# ---- 构建阶段：uv 安装依赖 ----
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# ---- 运行阶段 ----
FROM python:3.13-slim-bookworm
WORKDIR /app

# ffmpeg：celery-media 拼接播客音频；curl：容器 healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# 安全：非 root 运行
RUN useradd -m appuser
COPY --from=builder /app /app
# 播客本地暂存目录（main.py 启动即 mkdir，需可写）
RUN mkdir -p /app/media && chown -R appuser:appuser /app/media
USER appuser

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

# 容器内默认连 compose 网络内的服务名，本地开发不走此文件
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
