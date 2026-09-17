from pathlib import Path
from threading import Thread

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.api.v1.rss import public_router as rss_public_router
from app.core.config import get_settings
from app.core.errcode import api_error_handler, validation_error_handler
from app.core.logging import setup_logging
from app.core.request_logging import RequestLoggingMiddleware

setup_logging()


def _warm_caches() -> None:
    """后台预热进程内懒加载缓存：标签向量（防止重启后首个用户对话承担冷启动
    卡顿）。失败记日志即可——首次请求时懒加载路径仍会兜底。"""
    try:
        from app.services.news import vocabulary

        vocabulary.match_tags("预热")
    except Exception:  # noqa: BLE001
        from loguru import logger

        logger.opt(exception=True).warning("startup warmup fail")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, docs_url="/docs")
    # 统一错误信封 {"code": 业务码, "detail": ...}（成功响应不带 code）
    app.add_exception_handler(StarletteHTTPException, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 请求日志：每个 /api 请求落一条 request_logs（入参/出参/耗时/user_id）
    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    # 根路径也暴露探针，compose healthcheck / 负载均衡无需带前缀
    app.include_router(health_router)
    # 公开 RSS 订阅端点（/feed/{token}.xml，无前缀、无鉴权）
    app.include_router(rss_public_router)

    # 播客产物本地暂存（终存 OSS；此挂载服务生成中调试与 OSS 上传失败的降级路径）
    media_root = Path(settings.media_dir).resolve()
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_root)), name="media")

    Thread(target=_warm_caches, daemon=True, name="warmup").start()
    return app


app = create_app()
