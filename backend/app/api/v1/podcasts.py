from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DB, CurrentUser
from app.core.redis_client import redis_client
from app.models.podcast import Podcast
from app.schemas.podcast import PodcastCreate, PodcastCreateOut, PodcastOut, VoiceOut
from app.services.podcast import voices as voices_svc
from app.tasks.podcast import dispatch_podcast_pipeline

router = APIRouter(prefix="/podcasts", tags=["podcasts"])

HOURLY_LIMIT = 3
DAILY_LIMIT = 10


@router.get("/voices")
def list_voices(_user: CurrentUser) -> list[VoiceOut]:
    return [VoiceOut(**v) for v in voices_svc.list_voices()]


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
    if not voices_svc.is_valid_voice(body.voice_a):
        raise HTTPException(status_code=422, detail="音色 A 无效")
    if body.voice_b and not voices_svc.is_valid_voice(body.voice_b):
        raise HTTPException(status_code=422, detail="音色 B 无效")

    p = Podcast(
        user_id=user.id,
        mode=body.mode,
        topic_prompt=body.topic_prompt,
        voice_a=body.voice_a,
        voice_b=body.voice_b,
        script_prompt=body.script_prompt,
        script_prompt_a=body.script_prompt_a,
        script_prompt_b=body.script_prompt_b,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    dispatch_podcast_pipeline(p.id)
    return PodcastCreateOut(id=p.id, status=p.status)


def _get_owned(db, user: CurrentUser, podcast_id: int) -> Podcast:
    p = db.get(Podcast, podcast_id)
    if p is None or p.deleted_at is not None:
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
        Podcast.user_id == user.id, Podcast.deleted_at.is_(None)
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


@router.delete("/{podcast_id}")
def delete_podcast(podcast_id: int, db: DB, user: CurrentUser) -> dict:
    p = _get_owned(db, user, podcast_id)
    p.deleted_at = datetime.now(UTC)
    db.commit()
    return {"status": "ok"}
