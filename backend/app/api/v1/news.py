from fastapi import APIRouter, Query
from sqlalchemy import func, or_, text

from app.api.deps import DB, CurrentUser
from app.models.article import Article
from app.models.feed import Feed

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/stats")
def news_stats(db: DB) -> dict:
    """首页数据总览：总量/阶段状态/每日入库/分类分布/最后更新时间。公开接口（仅聚合数）。"""
    base = Article.deleted_at.is_(None)

    total = db.query(func.count(Article.id)).filter(base).scalar() or 0
    feeds = db.query(func.count(Feed.id)).filter(Feed.enabled.is_(True)).scalar() or 0

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

    def _fmt(dt) -> str | None:  # noqa: ANN001
        if dt is None:
            return None
        from zoneinfo import ZoneInfo

        if dt.tzinfo is None:  # PG 返回的 naive UTC
            from datetime import UTC

            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")

    return {
        "total": total,
        "feeds": feeds,
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


@router.get("/articles")
def list_articles(
    db: DB,
    _user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query("", max_length=100),
    tag: str = Query("", max_length=50),
) -> dict:
    """新闻列表：分页 + 关键词模糊搜索（标题/正文）+ 标签精确筛选，按发布时间倒序。"""
    q = db.query(Article).filter(Article.deleted_at.is_(None))
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(Article.title.ilike(like), Article.content.ilike(like)))
    if tag.strip():
        q = q.filter(Article.tags.contains([tag.strip()]))  # jsonb @> 精确包含
    total = q.count()
    rows = (
        q.order_by(Article.publish_time.desc().nulls_last(), Article.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    def _fmt(dt) -> str:  # noqa: ANN001
        from zoneinfo import ZoneInfo

        return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M") if dt else ""

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": a.id,
                "title": a.title,
                "source": a.source,
                "publish_time": _fmt(a.publish_time),
                "summary": a.summary or (a.content or "")[:100],
                "tags": a.tags or [],
                "url": a.url,
            }
            for a in rows
        ],
    }
