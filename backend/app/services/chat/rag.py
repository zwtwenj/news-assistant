"""聊天 RAG：多轮指代消解 + 复用播客检索链路（双路召回 → rerank → 回表）。

retrieve 与播客 _search_materials 同一套筛选方式（understand_topic 的标签
向量匹配 + 语义双路 + gte-rerank 精排），保证聊天与播客的内容口径一致。
"""

import json
import time
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.article import Article
from app.services.llm.gateway import gateway
from app.services.news import vector as vector_svc
from app.services.podcast.query_understanding import understand_topic

SEARCH_DAYS = 7
MIN_SCORE = 0.15  # 与播客检索一致
RAG_TOP_K = 5
MATERIAL_CHARS = 800

REWRITE_PROMPT = """以下是一段多轮对话的历史和用户的最新问题。
最新问题可能包含指代（它/这个/那里/上面提到的…）或省略了上下文。
请把它改写成一个**独立完整、可直接用于搜索**的问题：
- 保留原意，补全指代对象和缺失的上下文；
- 不要回答问题，只改写；
- 如果问题已经独立完整，原样返回。

对话历史：
{history}

最新问题：{query}

只输出 JSON：{{"rewritten": "<改写后的问题>"}}"""


def rewrite_query(history: list[dict], query: str) -> tuple[str, str | None]:
    """多轮指代消解：取最近 6 条历史改写成独立检索 query。

    返回 (rewritten_query, trace_id)——trace_id 来自网关 Langfuse 集成，
    供 👍/👎 用户评分挂载到对应 trace。失败回退 (原 query, None)。
    """
    meta: dict = {"chat_rewrite": True, "query": query[:50]}
    if not history:
        return query, meta.get("_trace_id")
    hist_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:200]}"
        for m in history[-6:]
    )
    try:
        resp = gateway.chat(
            "deepseek",
            messages=[{"role": "user", "content": REWRITE_PROMPT.format(
                history=hist_text, query=query)}],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0.0,
            langfuse_meta=meta,
        )
        content = resp.choices[0].message.content or "{}"
        rewritten = str(json.loads(content).get("rewritten", "")).strip()
        if rewritten:
            logger.info("query rewrite: {!r} -> {!r}", query[:40], rewritten[:60])
            return rewritten, meta.get("_trace_id")
    except Exception as exc:  # noqa: BLE001  失败回退原 query
        logger.opt(exception=True).warning("rewrite_query fail: {}", str(exc)[:60])
    return query, None


def retrieve(query: str, top_k: int = RAG_TOP_K) -> list[dict[str, Any]]:
    """播客同款检索：understand_topic → 双路召回（标签路+语义路）→ rerank → 回表。

    返回 [{title, url, tags, score, rerank_score, material}]；空 = 语料无相关内容。
    """
    intent = understand_topic(query)
    week_ago = int(time.time()) - SEARCH_DAYS * 86400
    recall_k = top_k * 3

    def _recall(tags_any: list[str] | None) -> list[dict[str, Any]]:
        hits = vector_svc.search(
            intent.query, top_k=recall_k, publish_after_ts=week_ago, tags_any=tags_any
        )
        return [h for h in hits if h["score"] >= MIN_SCORE]

    candidates: dict[int, dict[str, Any]] = {}
    if intent.tags:  # 标签路
        for h in _recall(intent.tags):
            candidates[h["article_id"]] = h
    for h in _recall(None):  # 语义路总执行
        candidates.setdefault(h["article_id"], h)
    if not candidates:
        return []

    reranked = vector_svc.rerank(intent.query, list(candidates.values()))
    reranked.sort(key=lambda h: (h.get("rerank_score") or 0), reverse=True)

    ids = [h["article_id"] for h in reranked[:top_k]]
    with SessionLocal() as db:
        rows = db.execute(select(Article).where(Article.id.in_(ids))).scalars().all()
    by_id = {a.id: a for a in rows}

    out: list[dict[str, Any]] = []
    for h in reranked[:top_k]:
        a = by_id.get(h["article_id"])
        if a is None:
            continue
        out.append(
            {
                "title": a.title,
                "url": a.url,
                "tags": a.tags or [],
                "score": round(h["score"], 3),
                "rerank_score": round(h.get("rerank_score") or 0, 3),
                "material": _excerpt(a),
            }
        )
    logger.info("chat retrieve: {} 命中 {}", query[:30], len(out))
    return out


def _excerpt(a: Article) -> str:
    """材料节选：正文清洗后前 800 字，兜底摘要。"""
    text = (a.content or "").strip()
    if len(text) < 50:
        text = a.summary or text
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= 6]
    return "\n".join(lines)[:MATERIAL_CHARS]


def build_rag_block(sources: list[dict[str, Any]]) -> str:
    """RAG 材料块（注入 system prompt）。"""
    if not sources:
        return ""
    blocks = []
    for i, s in enumerate(sources, 1):
        blocks.append(f"{i}. 【{s['title']}】\n{s['material']}")
    return "以下是检索到的相关新闻资料（回答时优先依据，并注明来源标题）：\n" + "\n\n".join(blocks)
