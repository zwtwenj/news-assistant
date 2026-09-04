"""向量化与精排：百炼 embedding → Milvus upsert/search；gte-rerank-v2 精排。"""

import time
from typing import Any

import httpx
from loguru import logger
from openai import OpenAI
from pymilvus import MilvusClient

from app.core.config import get_settings
from app.services.observability.langfuse_client import get_langfuse

COLLECTION = "news_articles"
EMBED_MODEL = "text-embedding-v4"
EMBED_BATCH = 10  # 百炼限速，沿用 demo 批量
EMBED_INPUT_MAX = 1500  # 拼接文本截断，控制 token 成本


def _embed_client() -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=s.dashscope_base_url, api_key=s.dashscope_api_key, timeout=60)


def _milvus() -> MilvusClient:
    s = get_settings()
    return MilvusClient(uri=s.milvus_uri, token=s.milvus_token)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量 embedding（内部按 10 条一批）。异常向上抛，由任务层计 attempts。"""
    lf = get_langfuse()
    client = _embed_client()
    out: list[list[float]] = []
    total_tokens = 0
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        gen = None
        if lf is not None:
            try:
                gen = lf.start_observation(
                    name="embedding/dashscope",
                    as_type="generation",
                    input=[t[:200] for t in batch],  # 记录截断，避免大 payload
                    model=EMBED_MODEL,
                )
            except Exception:
                gen = None
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
            out.extend(item.embedding for item in resp.data)
            usage = getattr(resp, "usage", None)
            tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            total_tokens += tokens
            if gen is not None:
                try:
                    gen.update(
                        output=f"{len(batch)} embeddings",
                        usage_details={"input": tokens, "output": 0, "total": tokens},
                    )
                    gen.end()
                except Exception:
                    pass
        except Exception as exc:
            if gen is not None:
                try:
                    gen.end(level="ERROR", status_message=str(exc)[:500])
                except Exception:
                    pass
            raise
    if total_tokens:
        logger.info("embedding tokens={}", total_tokens)
    return out


def build_embed_text(title: str, summary: str, content: str) -> str:
    return f"{title}\n{summary}\n{content[:EMBED_INPUT_MAX]}".strip()


def upsert_articles(rows: list[dict[str, Any]]) -> int:
    """rows: [{article_id, title, summary, content, tags, publish_ts, url}]，返回成功条数。"""
    texts = [build_embed_text(r["title"], r["summary"], r["content"]) for r in rows]
    vectors = embed_texts(texts)
    client = _milvus()
    data = [
        {
            "article_id": r["article_id"],
            "vector": vectors[i],
            "title": r["title"][:512],
            "publish_ts": int(r["publish_ts"]),
            "tags": [t[:64] for t in (r.get("tags") or [])][:10],
            "url": r["url"][:1000],
        }
        for i, r in enumerate(rows)
    ]
    res = client.upsert(collection_name=COLLECTION, data=data)
    count = getattr(res, "upsert_count", len(data))
    logger.info("milvus upsert {} rows", count)
    return count


def search(
    query: str,
    top_k: int = 20,
    *,
    publish_after_ts: int | None = None,
    tags_any: list[str] | None = None,
    threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """语义检索（M2 播客 / M3 RAG 共用）：可选时间范围与标签过滤。"""
    filters = []
    if publish_after_ts is not None:
        filters.append(f"publish_ts >= {int(publish_after_ts)}")
    if tags_any:
        tag_list = ", ".join(f'"{t}"' for t in tags_any)
        filters.append(f"array_contains_any(tags, [{tag_list}])")
    expr = " AND ".join(filters) or None

    vec = embed_texts([query])[0]
    client = _milvus()
    results = client.search(
        collection_name=COLLECTION,
        data=[vec],
        limit=top_k,
        filter=expr,
        output_fields=["article_id", "title", "tags", "publish_ts", "url"],
        search_params={"metric_type": "COSINE"},
    )[0]
    return [
        {
            "article_id": hit["entity"]["article_id"],
            "title": hit["entity"]["title"],
            "tags": hit["entity"]["tags"],
            "publish_ts": hit["entity"]["publish_ts"],
            "url": hit["entity"]["url"],
            "score": hit["distance"],
        }
        for hit in results
        if hit["distance"] >= threshold
    ]


RERANK_MODEL = "gte-rerank-v2"
RERANK_PATH = "/api/v1/services/rerank/text-rerank/text-rerank"  # DashScope 原生端点（demo 验证过）


def rerank(query: str, docs: list[dict[str, Any]], doc_text: str = "title") -> list[dict[str, Any]]:
    """gte-rerank-v2 精排：docs 内每项按 doc_text 字段（默认标题）与 query 算相关性。

    为每个 doc 附加 rerank_score 并按其降序返回；调用失败时原序返回（rerank_score=None），
    不阻断检索主流程。调用方应传入 Langfuse 埋点所需的上下文。
    """
    if not docs:
        return docs
    s = get_settings()
    try:
        started = time.perf_counter()
        resp = httpx.post(
            s.dashscope_base_url.rstrip("/").removesuffix("/compatible-mode/v1") + RERANK_PATH,
            headers={"Authorization": f"Bearer {s.dashscope_api_key}"},
            json={
                "model": RERANK_MODEL,
                "input": {
                    "query": query,
                    "documents": [str(d.get(doc_text) or "")[:200] for d in docs],
                },
                "parameters": {"return_documents": False, "top_n": len(docs)},
            },
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json()["output"]["results"]  # [{index, relevance_score}]
        by_index = {r["index"]: r["relevance_score"] for r in results}
        for i, d in enumerate(docs):
            d["rerank_score"] = by_index.get(i)
        docs.sort(key=lambda d: d["rerank_score"] or 0, reverse=True)
        logger.info("rerank ok docs={} latency={:.2f}s", len(docs), time.perf_counter() - started)
    except Exception:
        logger.opt(exception=True).warning("rerank fail, keep original order")
        for d in docs:
            d.setdefault("rerank_score", None)
    return docs
