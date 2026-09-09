from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, UploadFile

from app.api.deps import DB, CurrentUser
from app.core.redis_client import redis_client
from app.models.admin_host import AdminHost
from app.models.podcast import Podcast
from app.schemas.podcast import PodcastCreate, PodcastCreateOut, PodcastOut, PodcastUpdateIn
from app.services.storage import oss as oss_svc
from app.tasks.podcast import dispatch_podcast_pipeline

router = APIRouter(prefix="/podcasts", tags=["podcasts"])

HOURLY_LIMIT = 3
DAILY_LIMIT = 10


def _get_usable_host(db, host_id: int) -> AdminHost:
    """可用主播：未删 + 启用 + 预置/复刻成功（与 GET /hosts 暴露口径一致）。"""
    host = db.get(AdminHost, host_id)
    if (
        host is None
        or host.deleted_at is not None
        or not host.enabled
        or host.clone_status not in ("preset", "active")
    ):
        raise HTTPException(status_code=422, detail="主播无效或不可用")
    return host


def _check_quota(user_id: int) -> None:
    now = datetime.now(UTC)
    hour_key = f"quota:podcast:h:{user_id}:{now:%Y%m%d%H}"
    day_key = f"quota:podcast:d:{user_id}:{now:%Y%m%d}"
    if redis_client.incr(hour_key) > HOURLY_LIMIT:
        redis_client.decr(hour_key)
        raise HTTPException(status_code=429, detail=f"每小时最多生成 {HOURLY_LIMIT} 次，请稍后再试")
    redis_client.expire(hour_key, 3600)
    if redis_client.incr(day_key) > DAILY_LIMIT:
        redis_client.decr(day_key)
        raise HTTPException(status_code=429, detail=f"每天最多生成 {DAILY_LIMIT} 次，请明天再来")
    redis_client.expire(day_key, 86400)


@router.post("", status_code=201)
def create_podcast(body: PodcastCreate, db: DB, user: CurrentUser) -> PodcastCreateOut:
    _check_quota(user.id)
    # 主播解析 → 音色/人设快照落库（主播后续编辑不影响本期播客语义）
    host_a = _get_usable_host(db, body.host_a)
    host_b = _get_usable_host(db, body.host_b) if body.host_b else None

    # query 重写前置到创建：标题/检索意图/模板在入库时就绪——
    # 播客一出现就有标题，生成任务只消费这些参数（title/rag_query/template）
    from app.services.podcast.query_understanding import understand_topic

    intent = understand_topic(body.topic_prompt)

    p = Podcast(
        user_id=user.id,
        mode=body.mode,
        topic_prompt=body.topic_prompt,
        target_minutes=body.target_minutes,
        voice_a=host_a.voice_id,
        voice_b=host_b.voice_id if host_b else None,
        script_prompt=host_a.persona if body.mode == "single" else None,
        script_prompt_a=host_a.persona if body.mode == "dual" else None,
        script_prompt_b=host_b.persona if body.mode == "dual" else None,
        # 主播名字快照（脚本生成时引用名字而非代号）
        host_names=[h.name for h in (host_a, host_b) if h],
        # query 重写产物随创建落库（后续生成任务直接读取，不重复调用）
        title=intent.title,
        query_rewrite=intent.to_dict(),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    dispatch_podcast_pipeline(p.id)
    return PodcastCreateOut(id=p.id, status=p.status)


def _get_owned(db, user: CurrentUser, podcast_id: int) -> Podcast:
    p = db.get(Podcast, podcast_id)
    # disabled_at 非空 = 后管已禁用，C 端视为不存在（管理员下线可恢复）
    if p is None or p.deleted_at is not None or p.disabled_at is not None:
        raise HTTPException(status_code=404, detail="播客不存在")
    if p.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    return p


@router.get("")
def list_podcasts(
    db: DB,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
) -> dict:
    q = db.query(Podcast).filter(
        Podcast.user_id == user.id,
        Podcast.deleted_at.is_(None),
        Podcast.disabled_at.is_(None),  # 后管禁用的不下发
    )
    total = q.count()
    rows = (
        q.order_by(Podcast.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            PodcastOut.model_validate(
                {**r.__dict__, "script": None}  # 列表不带脚本正文
            ).model_dump(exclude={"script"})
            for r in rows
        ],
    }


@router.get("/{podcast_id}")
def get_podcast(podcast_id: int, db: DB, user: CurrentUser) -> PodcastOut:
    p = _get_owned(db, user, podcast_id)
    return PodcastOut.model_validate(p)


@router.patch("/{podcast_id}")
def update_podcast(
    podcast_id: int, body: PodcastUpdateIn, db: DB, user: CurrentUser
) -> PodcastOut:
    """编辑播客展示信息（标题/简介/封面）。已发布进 RSS 的会随 feed 同步更新（guid 不变）。"""
    p = _get_owned(db, user, podcast_id)
    if body.title is not None:
        p.title = body.title.strip()[:200] or None
    if body.description is not None:
        p.description = body.description.strip()[:2000] or None
    if body.cover_url is not None:
        p.cover_url = body.cover_url.strip()[:500] or None
    db.commit()
    db.refresh(p)
    return PodcastOut.model_validate(p)


@router.post("/{podcast_id}/feed")
def publish_to_feed(
    podcast_id: int, body: dict, db: DB, user: CurrentUser
) -> dict:
    """发布/撤下单集到自己的 RSS feed（声明式同步，平台按 guid 幂等更新）。"""
    p = _get_owned(db, user, podcast_id)
    published = bool(body.get("published"))
    if published:
        if p.status != "succeeded" or not p.audio_url:
            raise HTTPException(status_code=422, detail="仅生成成功的播客可发布")
        p.feed_published_at = datetime.now(UTC)
    else:
        p.feed_published_at = None
    db.commit()
    return {"status": "ok", "published": published}


@router.post("/cover")
def upload_cover(user: CurrentUser, file: UploadFile) -> dict:
    """单集封面上传（jpg/png，≤5MB）→ OSS 公有读直链。"""
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=422, detail="仅支持 jpg/png")
    data = file.file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="图片不能超过 5MB")
    ext = "jpg" if file.content_type == "image/jpeg" else "png"
    key = f"news/covers/{user.id}/{int(datetime.now(UTC).timestamp())}.{ext}"
    url = oss_svc.upload_bytes(data, key, file.content_type)
    if not url:
        raise HTTPException(status_code=502, detail="封面上传失败，请重试")
    return {"url": url}


@router.delete("/{podcast_id}")
def delete_podcast(podcast_id: int, db: DB, user: CurrentUser) -> dict:
    p = _get_owned(db, user, podcast_id)
    p.deleted_at = datetime.now(UTC)
    db.commit()
    return {"status": "ok"}
