from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, or_, text

from app.api.deps import DB, CurrentUser
from app.models.article import Article
from app.services.news.stats import get_news_stats

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/tags")
def list_tags(db: DB, _user: CurrentUser, limit: int = Query(200, ge=1, le=500)) -> dict:
    """使用中的标签列表（含文章计数，按计数倒序）：C 端可搜索下拉筛选的数据源。"""
    rows = db.execute(
        text(
            "SELECT tag, COUNT(*) AS count FROM articles, "
            "jsonb_array_elements_text(tags) AS tag "
            "WHERE deleted_at IS NULL "
            "GROUP BY tag ORDER BY count DESC, tag LIMIT :limit"
        ),
        {"limit": limit},
    ).all()
    return {"items": [{"tag": r.tag, "count": r.count} for r in rows]}


@router.get("/stats")
def news_stats() -> dict:
    """首页数据总览：总量/阶段状态/每日入库/分类分布/最后更新时间。公开接口（仅聚合数）。

    读 Redis 缓存（每日管道链尾刷新），未命中现算回填——数据总览每次进页不再重复跑聚合查询。
    """
    return get_news_stats()


@router.get("/articles/{article_id}")
def get_article(article_id: int, db: DB, _user: CurrentUser) -> dict:
    """单篇详情：返回全文正文（列表接口的摘要是 100 字截断，阅读面板需要全文）。"""
    a = db.get(Article, article_id)
    if a is None or a.deleted_at:
        raise HTTPException(status_code=404, detail="文章不存在")
    from datetime import UTC
    from zoneinfo import ZoneInfo

    publish = ""
    if a.publish_time:
        pt = a.publish_time if a.publish_time.tzinfo else a.publish_time.replace(tzinfo=UTC)
        publish = pt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    return {
        "id": a.id,
        "title": a.title,
        "source": a.source,
        "publish_time": publish,
        "summary": a.summary or "",
        "content": a.content or "",
        "tags": a.tags or [],
        "url": a.url,
    }


@router.get("/ticker")
def news_ticker(db: DB, limit: int = Query(6, ge=1, le=10)) -> dict:
    """登录页「实时热点」跑马灯：最新入库的 N 条新闻标题。公开接口（标题级公开信息）。

    只取质检合格（与列表 quality=ok 同口径）的新闻，登录页不展示被拦截的内容。
    """
    rows = (
        db.query(Article.title)
        .filter(
            Article.deleted_at.is_(None),
            Article.fetch_status == "succeeded",
            or_(Article.content_quality.is_(None), Article.content_quality != "bad"),
        )
        .order_by(Article.publish_time.desc().nulls_last(), Article.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [r.title for r in rows]}


@router.get("/articles")
def list_articles(
    db: DB,
    _user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query("", max_length=100),
    tag: str = Query("", max_length=50),
    source: str = Query("", max_length=200),
    quality: str = Query("ok", pattern="^(ok|bad)$"),  # ok=合格新闻 / bad=质检拦截区
) -> dict:
    """新闻列表：分页 + 关键词模糊搜索（标题/正文）+ 标签精确筛选，按发布时间倒序。

    quality=ok（默认）：只显示合格新闻（抓取成功 且 未被质检判 bad）；
    quality=bad：质检拦截区——规则质检或语义检测未通过的，带失败原因。
    """
    q = db.query(Article).filter(Article.deleted_at.is_(None))
    ok_condition = (
        Article.fetch_status == "succeeded",
        or_(Article.content_quality.is_(None), Article.content_quality != "bad"),
    )
    if quality == "ok":
        q = q.filter(*ok_condition)
    else:
        bad_condition = or_(
            Article.content_quality == "bad",
            Article.fetch_status.in_(["failed", "skipped"]),
        )
        q = q.filter(~and_(*ok_condition), bad_condition)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(Article.title.ilike(like), Article.content.ilike(like)))
    if tag.strip():
        q = q.filter(Article.tags.contains([tag.strip()]))  # jsonb @> 精确包含
    if source.strip():
        q = q.filter(Article.source == source.strip())  # 数据总览源明细表跳转用
    total = q.count()
    # 列表只取展示所需列：摘要在 SQL 侧 coalesce+left 截断，
    # 不传输整列正文（跨境带宽下 20 篇全文 ~24KB 是数秒级开销）
    rows = (
        q.with_entities(
            Article.id,
            Article.title,
            Article.source,
            Article.publish_time,
            func.coalesce(Article.summary, func.left(Article.content, 100), ""),
            Article.tags,
            Article.url,
            Article.content_quality,
            Article.fetch_error,
            Article.ai_error,
        )
        .order_by(Article.publish_time.desc().nulls_last(), Article.id.desc())
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
                "id": id_,
                "title": title,
                "source": source,
                "publish_time": _fmt(publish_time),
                "summary": summary,
                "tags": tags or [],
                "url": url,
                "content_quality": content_quality,
                # 失败原因：规则质检在 fetch_error，语义检测在 ai_error，判重在 fetch_error；
                # 存量回填的 bad（未走过门禁）给固定说明
                "fail_reason": fetch_error or ai_error or (
                    "存量质检回填（未记录具体原因）" if content_quality == "bad" else None
                ),
            }
            for (
                id_,
                title,
                source,
                publish_time,
                summary,
                tags,
                url,
                content_quality,
                fetch_error,
                ai_error,
            ) in rows
        ],
    }
