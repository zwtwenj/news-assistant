import sys

from loguru import logger

from app.core.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stdout,
        level="DEBUG" if settings.env == "dev" else "INFO",
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}:{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=settings.env == "dev",
        diagnose=settings.env == "dev",
    )
    # TODO(M1): request_id/task_id 上下文绑定（contextvars），prod 环境接 Sentry
