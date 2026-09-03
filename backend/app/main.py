from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, docs_url="/docs")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    # 根路径也暴露探针，compose healthcheck / 负载均衡无需带前缀
    app.include_router(health_router)

    # 播客产物本地存储（生产切 OSS 后可移除）
    media_root = Path(settings.media_dir).resolve()
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_root)), name="media")
    return app


app = create_app()
