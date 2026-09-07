"""动态标签词表（tag_words 表）：打标/检索 prompt 注入，LLM new_tags 使其自生长。

事实源 = tag_words 表（每日流水线从 articles.tags 聚合重建，幂等自愈）；
Redis JSON array 快照供高频读取（news 项目 db0；news-admin 直读 PG，见其 tagger）。
"""

import json

from loguru import logger
from sqlalchemy import select, text

from app.core.redis_client import redis_client
from app.db.session import SessionLocal
from app.models.tag_word import TagWord

REDIS_KEY = "news:tag_vocab"
MAX_WORDS = 300  # 词表上限：满后 new_tags 丢弃只复用（防 prompt 注入撑爆）


def get_vocabulary() -> list[str]:
    """词表快照：Redis → miss 回源 PG → 回填。任何失败回退空列表（prompt 无词表仍可打标）。"""
    try:
        cached = redis_client.get(REDIS_KEY)
        if cached:
            return json.loads(cached)
    except Exception:  # noqa: BLE001
        logger.warning("tag vocabulary redis read fail, fallback to pg")
    try:
        with SessionLocal() as db:
            words = [w for (w,) in db.execute(select(TagWord.word).order_by(TagWord.id)).all()]
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("tag vocabulary pg read fail")
        return []
    _set_cache(words)
    return words


def add_new_tags(new_words: list[str]) -> list[str]:
    """卫生过滤后把 LLM 新词写入词表（PG upsert + 刷 Redis），返回实际收录的词。"""
    cleaned = _sanitize(new_words)
    if not cleaned:
        return []
    try:
        with SessionLocal() as db:
            existing = set(db.execute(select(TagWord.word)).scalars())
            room = MAX_WORDS - len(existing)
            accepted = [w for w in cleaned if w not in existing][: max(0, room)]
            for w in accepted:
                db.add(TagWord(word=w))
            db.commit()
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("tag vocabulary pg write fail")
        return []
    if accepted:
        # 合并进缓存（不重查库）；缓存异常不阻塞——下次 get_vocabulary 回源自愈
        try:
            cached = redis_client.get(REDIS_KEY)
            words = json.loads(cached) if cached else []
            _set_cache(words + [w for w in accepted if w not in words])
        except Exception:  # noqa: BLE001
            pass
    return accepted


def rebuild_vocabulary() -> int:
    """从 articles.tags 聚合重建词表（幂等自愈），覆盖表 + 刷 Redis。返回词数。"""
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT DISTINCT jsonb_array_elements_text(tags) AS word "
                "FROM articles WHERE deleted_at IS NULL AND tags IS NOT NULL "
                "ORDER BY word"
            )
        ).scalars().all()
        words = [w for w in rows if _valid_word(w)]
        db.query(TagWord).delete()
        for w in words:
            db.add(TagWord(word=w))
        db.commit()
    _set_cache(words)
    logger.info("tag vocabulary rebuilt: {} words", len(words))
    return len(words)


def _sanitize(words: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for w in words if isinstance(words, list) else []:
        w = str(w).strip()
        if 2 <= len(w) <= 8 and w not in seen and not any(ch.isspace() for ch in w):
            seen.add(w)
            out.append(w)
    return out[:3]  # 单篇最多长出 3 个新词


def _valid_word(w: str) -> bool:
    return bool(w) and len(w) <= 64


def _set_cache(words: list[str]) -> None:
    try:
        redis_client.set(REDIS_KEY, json.dumps(words, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        logger.warning("tag vocabulary redis write fail")
