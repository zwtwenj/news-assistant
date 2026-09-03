"""轻量维护任务（default 队列），同时用作各队列 worker 的存活验证。"""

from app.tasks import celery_app
from app.tasks.base import BaseTask


@celery_app.task(base=BaseTask, bind=True, name="app.tasks.maintenance.ping")
def ping(self, queue: str = "default") -> str:
    """worker 存活探针。验证方式：
    celery -A app.tasks call app.tasks.maintenance.ping --args '["crawl"]' --queue crawl
    """
    return f"pong from {queue}"
