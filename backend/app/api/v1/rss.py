"""RSS 分发路由：

- /api/v1/rss/*：用户自己的 feed 配置与发布管理（需登录）
- /feed/{token}.xml：公开订阅端点（无鉴权，平台/阅读器抓取），由 main.py 单独挂载
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, UploadFile

from app.api.deps import DB, CurrentUser
from app.models.podcast import Podcast
from app.schemas.rss import RssConfigIn, RssFeedOut
from app.services import rss_feed as rss_feed_svc
from app.services.storage import oss as oss_svc

router = APIRouter(prefix="/rss", tags=["rss"])
public_router = APIRouter(tags=["feed"])

_COVER_MAX_BYTES = 5 * 1024 * 1024


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


@router.post("/podcasts/{podcast_id}/feed")
def publish_to_feed(podcast_id: int, body: dict, db: DB, user: CurrentUser) -> dict:
    """发布/撤下单集到自己的 RSS feed（声明式：内容即时反映在 feed XML 中，平台按 guid 同步）。"""
    p = db.get(Podcast, podcast_id)
    if p is None or p.deleted_at is not None or p.user_id != user.id:
        raise HTTPException(status_code=404, detail="播客不存在")
    published = bool(body.get("published"))
    if published:
        if p.status != "succeeded" or not p.audio_url:
            raise HTTPException(status_code=422, detail="仅生成成功的播客可发布")
        p.feed_published_at = datetime.now(UTC)
    else:
        p.feed_published_at = None
    db.commit()
    return {"status": "ok", "published": published}


@router.post("/podcasts/cover")
def upload_cover(user: CurrentUser, file: UploadFile) -> dict:
    """单集封面上传（jpg/png，≤5MB）→ OSS 公有读直链。"""
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=422, detail="仅支持 jpg/png")
    data = file.file.read()
    if len(data) > _COVER_MAX_BYTES:
        raise HTTPException(status_code=422, detail="图片不能超过 5MB")
    ext = "jpg" if file.content_type == "image/jpeg" else "png"
    key = f"news/covers/{user.id}/{int(datetime.now(UTC).timestamp())}.{ext}"
    url = oss_svc.upload_bytes(data, key, file.content_type)
    if not url:
        raise HTTPException(status_code=502, detail="封面上传失败，请重试")
    return {"url": url}


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
