"""数据总览聚合 + Redis 写透缓存。

写入方只有每日管道：链尾 mark_pipeline_done 刷新缓存；读方 cache-aside，
未命中现算并回填。任何 Redis 故障都降级为直接查库，缓存不挡主流程。
"""

import json

from loguru import logger
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.redis_client import redis_client
from app.db.session import SessionLocal
from app.models.article import Article
from app.models.feed import Feed

STATS_KEY = "news:stats"
STATS_TTL = 25 * 3600  # 兜底：正常由每日管道刷新，错过刷新最多旧一天


def _fmt(dt) -> str | None:  # noqa: ANN001
    if dt is None:
        return None
    from datetime import UTC
    from zoneinfo import ZoneInfo

    if dt.tzinfo is None:  # PG 返回的 naive UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def compute_news_stats(db: Session) -> dict:
    """聚合查询本体：总量/阶段状态/每日入库/分类分布/per-feed 源明细。"""
    base = Article.deleted_at.is_(None)

    total = db.query(func.count(Article.id)).filter(base).scalar() or 0
    feeds = (
        db.query(func.count(Feed.id))
        .filter(Feed.enabled.is_(True), Feed.deleted_at.is_(None))
        .scalar()
        or 0
    )

    status_rows = (
        db.query(Article.fetch_status, func.count(Article.id))
        .filter(base)
        .group_by(Article.fetch_status)
        .all()
    )
    fetch_stats = {s: c for s, c in status_rows}

    last_updated = db.query(func.max(Article.updated_at)).filter(base).scalar()
    last_fetched = db.query(func.max(Feed.last_fetched_at)).scalar()

    # 最近 14 天每日入库量（按上海时区分日，含空日期补零，前端画图方便）
    by_day_rows = db.execute(
        text(
            "SELECT d::date AS day, COUNT(a.id) AS count "
            "FROM generate_series("
            "  (now() AT TIME ZONE 'Asia/Shanghai')::date - INTERVAL '13 days',"
            "  (now() AT TIME ZONE 'Asia/Shanghai')::date, '1 day') AS d "
            "LEFT JOIN articles a "
            "  ON (a.created_at AT TIME ZONE 'Asia/Shanghai')::date = d::date "
            "  AND a.deleted_at IS NULL "
            "GROUP BY d ORDER BY d"
        )
    ).all()

    # 分类分布（tags jsonb 展开计数，只统计打标成功的）
    by_category_rows = db.execute(
        text(
            "SELECT tag, COUNT(*) AS count FROM articles, "
            "jsonb_array_elements_text(tags) AS tag "
            "WHERE deleted_at IS NULL AND ai_status = 'succeeded' "
            "GROUP BY tag ORDER BY count DESC LIMIT 12"
        )
    ).all()

    # per-feed 统计：数据总览的源明细表（名称/启用/最后抓取/本批入库/累计/代表性来源值）
    by_feed_rows = db.execute(
        text(
            """
            SELECT f.id, f.name, f.enabled, f.last_fetched_at,
                   COUNT(a.id) AS total,
                   COUNT(a.id) FILTER (WHERE
                     (a.created_at AT TIME ZONE 'Asia/Shanghai')::date
                     = (now() AT TIME ZONE 'Asia/Shanghai')::date) AS today,
                   MAX(a.source) AS sample_source
            FROM feeds f
            LEFT JOIN articles a ON a.feed_id = f.id AND a.deleted_at IS NULL
            WHERE f.deleted_at IS NULL AND f.enabled
            GROUP BY f.id, f.name, f.enabled, f.last_fetched_at
            ORDER BY total DESC
            """
        )
    ).all()

    return {
        "total": total,
        "feeds": feeds,
        "by_feed": [
            {
                "id": r.id,
                "name": r.name,
                "enabled": r.enabled,
                "last_fetched_at": _fmt(r.last_fetched_at),
                "today": r.today,
                "total": r.total,
                # 代表性来源值：跳转新闻列表按 source 精确筛选用
                "sample_source": r.sample_source,
            }
            for r in by_feed_rows
        ],
        "fetch": {
            "succeeded": fetch_stats.get("succeeded", 0),
            "skipped": fetch_stats.get("skipped", 0),
            "pending": fetch_stats.get("pending", 0),
            "failed": fetch_stats.get("failed", 0),
        },
        "last_updated_at": _fmt(last_updated),
        "last_fetched_at": _fmt(last_fetched),
        "by_day": [{"date": str(r.day), "count": r.count} for r in by_day_rows],
        "by_category": [{"tag": r.tag, "count": r.count} for r in by_category_rows],
    }


def get_news_stats() -> dict:
    """数据总览读取入口：Redis → miss 回源 PG → 回填。"""
    try:
        cached = redis_client.get(STATS_KEY)
        if cached:
            return json.loads(cached)
    except Exception:  # noqa: BLE001
        logger.warning("stats 缓存读取失败，回源现算")
    with SessionLocal() as db:
        payload = compute_news_stats(db)
    try:
        redis_client.setex(STATS_KEY, STATS_TTL, json.dumps(payload, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass
    return payload


def refresh_cache() -> None:
    """管道完成后调用：现算一次写入 Redis。失败只告警，不影响链尾标记。"""
    try:
        with SessionLocal() as db:
            payload = compute_news_stats(db)
        redis_client.setex(STATS_KEY, STATS_TTL, json.dumps(payload, ensure_ascii=False))
        logger.info("stats 缓存已刷新（total={}）", payload["total"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("stats 缓存刷新失败: {}", str(exc)[:120])
