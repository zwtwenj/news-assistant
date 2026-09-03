from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "news_assistant",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.maintenance", "app.tasks.news", "app.tasks.podcast"],
)

celery_app.conf.update(
    # 可靠性约定（plan §5）：晚确认 + 预取 1，长任务崩溃后可被重新投递
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    # 全局硬超时 30min；media 任务（ffmpeg/TTS）可按任务单独覆盖
    task_time_limit=3600,
    # 队列按资源画像划分（plan §5）：crawl / llm / media / default
    task_default_queue="default",
    task_routes={
        # 新闻流水线（按资源画像精确路由）
        "app.tasks.news.fetch_feeds": {"queue": "crawl"},
        "app.tasks.news.scrape_articles": {"queue": "crawl"},
        "app.tasks.news.analyze_articles": {"queue": "llm"},
        "app.tasks.news.embed_articles": {"queue": "llm"},
        "app.tasks.news.run_daily_pipeline": {"queue": "default"},
        # 播客合成
        "app.tasks.podcast.gen_script": {"queue": "llm"},
        "app.tasks.podcast.synth_tts": {"queue": "media"},
        "app.tasks.podcast.compose_audio": {"queue": "media"},
        # 通用通配（后续模块沿用）
        "app.tasks.crawl.*": {"queue": "crawl"},
        "app.tasks.llm.*": {"queue": "llm"},
        "app.tasks.media.*": {"queue": "media"},
    },
    # 每日定时：凌晨 2 点新闻流水线（plan-news-pipeline §3.2）
    beat_schedule={
        "daily-news-pipeline": {
            "task": "app.tasks.news.run_daily_pipeline",
            "schedule": crontab(hour=2, minute=0),
        },
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
)
