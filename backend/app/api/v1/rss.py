"""RSS 分发路由：

- /api/v1/rss/*：用户自己的 feed 配置（需登录；发布/撤下与封面上传在 podcasts 路由）
- /feed/{token}.xml：公开订阅端点（无鉴权，平台/阅读器抓取），由 main.py 单独挂载
"""

from fastapi import APIRouter, Response

from app.api.deps import DB, CurrentUser
from app.models.podcast import Podcast
from app.schemas.rss import RssConfigIn, RssFeedOut
from app.services import rss_feed as rss_feed_svc

router = APIRouter(prefix="/rss", tags=["rss"])
public_router = APIRouter(tags=["feed"])


@router.get("/me")
def my_feed(db: DB, user: CurrentUser) -> RssFeedOut:
    """我的 feed 配置与订阅地址（首次访问自动开通默认配置）。"""
    feed = rss_feed_svc.ensure_user_feed(db, user)
    published = _published_count(db, user.id)
    return RssFeedOut(
        feed_url=rss_feed_svc.get_feed_url(feed),
        channel_title=feed.channel_title,
        channel_description=feed.channel_description,
        published_count=published,
    )


@router.put("/me")
def update_my_feed(body: RssConfigIn, db: DB, user: CurrentUser) -> RssFeedOut:
    feed = rss_feed_svc.ensure_user_feed(db, user)
    feed.channel_title = body.channel_title.strip()[:200]
    feed.channel_description = body.channel_description.strip()[:2000]
    db.commit()
    db.refresh(feed)
    return RssFeedOut(
        feed_url=rss_feed_svc.get_feed_url(feed),
        channel_title=feed.channel_title,
        channel_description=feed.channel_description,
        published_count=_published_count(db, user.id),
    )


def _published_count(db, user_id: int) -> int:
    return (
        db.query(Podcast)
        .filter(
            Podcast.user_id == user_id,
            Podcast.feed_published_at.is_not(None),
            Podcast.deleted_at.is_(None),
            Podcast.disabled_at.is_(None),
        )
        .count()
    )


@public_router.get("/feed/{token}.xml")
def feed_xml(token: str) -> Response:
    """公开 RSS 订阅端点（平台/阅读器抓取；token 混淆，不可枚举）。"""
    feed = rss_feed_svc.get_feed_by_token(token)
    if feed is None:
        return Response(status_code=404, content="feed not found")
    xml = rss_feed_svc.build_feed_xml(feed)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
