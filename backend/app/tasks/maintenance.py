"""轻量维护任务（default 队列），同时用作各队列 worker 的存活验证。"""

from loguru import logger

from app.tasks import celery_app
from app.tasks.base import BaseTask


@celery_app.task(base=BaseTask, bind=True, name="app.tasks.maintenance.ping")
def ping(self, queue: str = "default") -> str:
    """worker 存活探针。验证方式：
    celery -A app.tasks call app.tasks.maintenance.ping --args '["crawl"]' --queue crawl
    """
    return f"pong from {queue}"


@celery_app.task(name="app.tasks.maintenance.cleanup_request_logs")
def cleanup_request_logs() -> str:
    """清理 14 天前的请求日志：request_logs 高频写入，靠保留策略控表体积。"""
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        n = db.execute(
            text("DELETE FROM request_logs WHERE ts < now() - INTERVAL '14 days'")
        ).rowcount
        db.commit()
    logger.info("request_logs 清理：删除 {} 条", n)
    return f"deleted {n}"
