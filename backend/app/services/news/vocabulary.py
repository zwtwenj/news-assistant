"""动态标签词表（tag_words 表）：打标/检索 prompt 注入，LLM new_tags 使其自生长。

事实源 = tag_words 表（每日流水线从 articles.tags 聚合重建，幂等自愈）；
Redis JSON array 快照供高频读取（news 项目 db0；news-admin 直读 PG，见其 tagger）。

标签向量化：每个标签持有 text-embedding-v4 向量（存 tag_words.embedding），
播客检索时 query 向量与词表向量做内存余弦（300×1024 点积，微秒级），
按阈值切出相关标签域——替代不稳定的 LLM 挑标签。
"""

import json

import numpy as np
from loguru import logger
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.redis_client import redis_client
from app.db.session import SessionLocal
from app.models.tag_word import TagWord

REDIS_KEY = "news:tag_vocab"
MAX_WORDS = 300  # 词表上限：满后 new_tags 丢弃只复用（防 prompt 注入撑爆）

# 标签向量缓存 {word: list[float]}：进程内存（300×1024×4B ≈ 1.2MB），
# 持久化在 tag_words.embedding；词表生长时增量 embed，进程重启从 PG 加载
_vectors: dict[str, list[float]] = {}
_vectors_loaded = False


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
    """卫生过滤后把 LLM 新词写入词表（PG upsert + 刷 Redis），返回实际收录的词。

    收录的新词即时增量 embedding（低频事件，成本可忽略），保证向量缓存完整。
    """
    cleaned = _sanitize(new_words)
    if not cleaned:
        return []
    accepted: list[str] = []
    vectors: dict[str, list[float]] = {}
    try:
        with SessionLocal() as db:
            existing = set(db.execute(select(TagWord.word)).scalars())
            room = MAX_WORDS - len(existing)
            accepted = [w for w in cleaned if w not in existing][: max(0, room)]
            if accepted:
                vectors = _embed_words(accepted)  # 新词增量 embedding，向量随词落库
                for w in accepted:
                    db.add(TagWord(word=w, embedding=vectors.get(w)))
            db.commit()
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("tag vocabulary pg write fail")
        return []
    _vectors.update({w: v for w, v in vectors.items() if v})
    # 合并进词表缓存；缓存异常不阻塞——下次回源自愈
    try:
        cached = redis_client.get(REDIS_KEY)
        words = json.loads(cached) if cached else []
        _set_cache(words + [w for w in accepted if w not in words])
    except Exception:  # noqa: BLE001
        pass
    return accepted


def rebuild_vocabulary() -> int:
    """从 articles.tags 聚合补齐词表（幂等自愈），并集语义只增不删。返回全词表词数。

    文章中出现过的标签必须都在词表里（丢失即从这里恢复）；自生长/人工加入的词
    即使暂无文章使用也保留（合法检索维度，且 embedding 不因重建丢失）。
    """
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT DISTINCT jsonb_array_elements_text(tags) AS word "
                "FROM articles WHERE deleted_at IS NULL AND tags IS NOT NULL "
                "ORDER BY word"
            )
        ).scalars().all()
        words = [w for w in rows if _valid_word(w)]
        existing = set(db.execute(select(TagWord.word)).scalars())
        added = [w for w in words if w not in existing]
        for w in added:
            db.add(TagWord(word=w))
        db.commit()
        # 从 PG 重读全量（含刚补齐的词）刷缓存——不能读 Redis 旧缓存
        all_words = [w for (w,) in db.execute(select(TagWord.word).order_by(TagWord.id)).all()]
    _set_cache(all_words)
    if added:
        logger.info("tag vocabulary rebuilt: +{} → {} words", added, len(all_words))
    return len(all_words)


def match_tags(query: str, threshold: float | None = None) -> list[str]:
    """query 与词表标签的向量余弦匹配：返回相似度 ≥ 阈值（默认配置值）的标签。

    任何失败（embedding 不可用/词表空）返回 []——调用方标签路跳过，语义路兜底。
    """
    global _vectors_loaded
    if not query.strip():
        return []
    try:
        if not _vectors_loaded:
            _load_vectors()
        _ensure_vectors()
        if not _vectors:
            return []
        from app.services.news import vector as vector_svc

        q = np.array(vector_svc.embed_texts([query])[0])
        words = list(_vectors.keys())
        M = np.array([_vectors[w] for w in words])
        sims = (M / np.linalg.norm(M, axis=1, keepdims=True)) @ (
            q / np.linalg.norm(q)
        )
        th = threshold if threshold is not None else get_settings().tag_match_threshold
        matched = [words[i] for i in np.argsort(-sims) if sims[i] >= th]
        logger.info("标签向量匹配: query={} 阈值={} 命中 {}", query[:20], th, matched)
        return matched
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("tag vector match fail")
        return []


def _load_vectors() -> None:
    """进程启动/首次使用时从 PG 加载已有向量。"""
    global _vectors_loaded
    try:
        with SessionLocal() as db:
            rows = db.execute(
                select(TagWord.word, TagWord.embedding).where(TagWord.embedding.is_not(None))
            ).all()
        _vectors.update({w: v for w, v in rows if v})
        _vectors_loaded = True
        logger.info("tag vectors loaded: {}", len(_vectors))
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("tag vectors load fail")


def _ensure_vectors() -> None:
    """词表中尚无向量的标签批量补算（新 seed/迁移后冷启动一次）。"""
    words = [w for w in get_vocabulary() if w not in _vectors]
    if not words:
        return
    vectors = _embed_words(words)
    _vectors.update({w: v for w, v in vectors.items() if v})
    try:
        with SessionLocal() as db:
            for w, v in vectors.items():
                if v:
                    db.query(TagWord).filter(TagWord.word == w).update({"embedding": v})
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("tag vectors persist fail")
    logger.info("tag vectors ensured: +{}", len(vectors))


def _embed_words(words: list[str]) -> dict[str, list[float]]:
    """批量 embedding 词表（内部按 10 条一批）。失败返回 {}（词照收，向量懒补）。"""
    try:
        from app.services.news import vector as vector_svc

        vecs = vector_svc.embed_texts(words)
        return dict(zip(words, vecs, strict=True))
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("tag embedding fail")
        return {}


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
