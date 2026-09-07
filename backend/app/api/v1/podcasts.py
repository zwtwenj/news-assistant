from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DB, CurrentUser
from app.core.redis_client import redis_client
from app.models.admin_host import AdminHost
from app.models.podcast import Podcast
from app.schemas.podcast import PodcastCreate, PodcastCreateOut, PodcastOut, PodcastUpdateIn
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


@router.delete("/{podcast_id}")
def delete_podcast(podcast_id: int, db: DB, user: CurrentUser) -> dict:
    p = _get_owned(db, user, podcast_id)
    p.deleted_at = datetime.now(UTC)
    db.commit()
    return {"status": "ok"}
