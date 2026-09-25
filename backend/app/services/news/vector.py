"""向量化、混合检索与精排（2026-09 重构：dense+BM25 hybrid + 封闭类目路由）。

检索形态（bake-off 实验 1 万篇规模验证，见 eval/ 系列报告）：
- 具体型 query：hybrid_search —— dense（语义）+ sparse（BM25 字面）RRF 融合，
  干扰越密优势越大（hit@10 0.878 vs dense 单路 0.856，退化斜率最平缓）
- 综述型 query：search_by_category —— 封闭类目硬过滤 + 时间窗（不足自动放宽）
  + 类内 dense 排序；类目由 categories.py 的白名单分类器保证

集合 schema（news_articles_v2）：
- dense FLOAT_VECTOR(1024)          语义路（title+summary+content[:1500]）
- sparse SPARSE_FLOAT_VECTOR        BM25 Function 自动生成（body 中文分词），插入端只写 body
- category / aux_categories         封闭类目（主+副），INVERTED 索引
- event_id / is_rep                 事件层占位（=article_id / True），S3 聚类后启用
- 标签字段已退役：tags 不再入库（词表碎片化 + 标签路 61% miss 实验定论）
"""

import re
import time
from typing import Any

import httpx
from loguru import logger
from openai import OpenAI
from pymilvus import (
    AnnSearchRequest,
    DataType,
    Function,
    FunctionType,
    MilvusClient,
    WeightedRanker,
)

from app.core.config import get_settings
from app.services.observability.langfuse_client import get_langfuse

COLLECTION = "news_articles_v2"
EMBED_MODEL = "text-embedding-v4"
EMBED_BATCH = 10  # 百炼限速，沿用 demo 批量
EMBED_INPUT_MAX = 1500  # 拼接文本截断，控制 token 成本
OUTPUT_FIELDS = ["article_id", "title", "category", "publish_ts", "url"]

# 行级噪音过滤（与旧 script.py 同源）：BM25 的 body 输入源，脏行会污染词频
_NOISE_KEYWORDS = (
    "新闻频道", "点击收起", "扫一扫", "返回", "正在加载", "责任编辑", "编辑：",
    "分享到", "原标题", "最新推荐", "加载中", "首页", "客户端", "热线", "版权",
)


def clean_body(raw: str | None) -> str:
    """正文行级清洗：丢短行/邮箱行/来源日期行/导航页脚行。"""
    if not raw:
        return ""
    kept = []
    for line in raw.splitlines():
        s = line.strip()
        if len(s) < 6 or "@" in s:
            continue
        if re.search(r"\|\s*20\d\d年", s):
            continue
        if any(k in s for k in _NOISE_KEYWORDS):
            continue
        kept.append(s)
    return "\n".join(kept)


def _embed_client() -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=s.dashscope_base_url, api_key=s.dashscope_api_key, timeout=60)


def _milvus() -> MilvusClient:
    s = get_settings()
    return MilvusClient(uri=s.milvus_uri, token=s.milvus_token)


_ensured = False


def ensure_collection(client: MilvusClient | None = None) -> None:
    """幂等建集合（首台写入者创建；容器化部署后多 worker 并发安全由 IF NOT EXISTS 语义兜底）。"""
    global _ensured
    if _ensured:
        return
    client = client or _milvus()
    if client.has_collection(COLLECTION):
        _ensured = True
        return
    schema = client.create_schema()
    schema.add_field("article_id", DataType.INT64, is_primary=True)
    schema.add_field("event_id", DataType.INT64)  # S3 事件簇占位
    schema.add_field("title", DataType.VARCHAR, max_length=2048)
    schema.add_field("body", DataType.VARCHAR, max_length=8192,
                     enable_analyzer=True, analyzer_params={"type": "chinese"})
    schema.add_field("dense", DataType.FLOAT_VECTOR, dim=1024)
    schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)  # BM25 Function 生成
    schema.add_field("category", DataType.VARCHAR, max_length=32)
    schema.add_field("aux_categories", DataType.ARRAY,
                     element_type=DataType.VARCHAR, max_capacity=2, max_length=32)
    schema.add_field("publish_ts", DataType.INT64)
    schema.add_field("source", DataType.VARCHAR, max_length=200)
    schema.add_field("url", DataType.VARCHAR, max_length=1000)
    schema.add_field("is_rep", DataType.BOOL)  # S3 事件代表占位
    schema.add_function(Function(name="body_bm25", input_field_names=["body"],
                                 output_field_names=["sparse"], function_type=FunctionType.BM25))
    ip = client.prepare_index_params()
    ip.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="COSINE")
    ip.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
    ip.add_index(field_name="category", index_type="INVERTED")
    ip.add_index(field_name="event_id", index_type="INVERTED")
    client.create_collection(COLLECTION, schema=schema, index_params=ip)
    logger.info("milvus 集合 {} 已创建", COLLECTION)
    _ensured = True


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
    """rows: [{article_id, title, summary, content, category, aux_categories,
              publish_ts, url, source}]，返回成功条数。

    sparse 由 BM25 Function 从 body 自动生成；event_id/is_rep 为 S3 占位。
    """
    texts = [build_embed_text(r["title"], r.get("summary") or "", r["content"]) for r in rows]
    vectors = embed_texts(texts)
    client = _milvus()
    ensure_collection(client)
    data = [
        {
            "article_id": r["article_id"],
            "event_id": r["article_id"],  # S3 占位：聚类上线后重写为簇 ID
            "title": r["title"][:600],
            "body": clean_body(r["content"])[:2000],
            "dense": vectors[i],
            "category": (r.get("category") or "other")[:32],
            "aux_categories": [a[:32] for a in (r.get("aux_categories") or [])][:2],
            "publish_ts": int(r["publish_ts"]),
            "source": (r.get("source") or "")[:200],
            "url": (r.get("url") or "")[:1000],
            "is_rep": True,  # S3 占位
        }
        for i, r in enumerate(rows)
    ]
    res = client.upsert(collection_name=COLLECTION, data=data)
    count = getattr(res, "upsert_count", len(data))
    logger.info("milvus upsert {} rows", count)
    return count


def hybrid_search(
    query: str,
    top_k: int = 20,
    *,
    publish_after_ts: int | None = None,
    threshold: float = 0.0,
    extra_queries: list[str] | None = None,
) -> list[dict[str, Any]]:
    """具体型检索：dense（语义）+ sparse（BM25）双路 RRF 融合。

    extra_queries：可选的附加 query（如 HyDE 假设文档）——每条 query 各跑
    双路后按 article_id 取最高 RRF 分合并（多视角融合，实验：miss 6→2）。
    """
    client = _milvus()
    expr = f"publish_ts >= {int(publish_after_ts)}" if publish_after_ts is not None else None
    queries = [query] + (extra_queries or [])

    best: dict[int, dict[str, Any]] = {}
    for q in queries:
        vec = embed_texts([q])[0]
        reqs = [
            AnnSearchRequest(data=[vec], anns_field="dense",
                             param={"metric_type": "COSINE"}, limit=top_k),
            AnnSearchRequest(data=[q], anns_field="sparse",
                             param={"metric_type": "BM25"}, limit=top_k),
        ]
        # 加权融合（dense 主导排序，sparse 保留抗干扰票）——双规模实测：
        # 1.1k 语料 MRR 0.725≈dense 基准 0.724（RRF 等权跌到 0.682）；
        # 1 万干扰下 MRR 0.730 / NDCG 0.756 全面优于 dense 0.694 / 0.724
        results = client.hybrid_search(
            COLLECTION, reqs, ranker=WeightedRanker(0.8, 0.2), limit=top_k,
            filter=expr, output_fields=OUTPUT_FIELDS,
        )[0]
        for hit in results:
            aid = hit["entity"]["article_id"]
            score = hit["distance"]
            if aid not in best or score > best[aid]["score"]:
                best[aid] = {
                    "article_id": aid,
                    "title": hit["entity"]["title"],
                    "category": hit["entity"]["category"],
                    "publish_ts": hit["entity"]["publish_ts"],
                    "url": hit["entity"]["url"],
                    "score": score,
                }
    merged = sorted(best.values(), key=lambda h: h["score"], reverse=True)
    return [h for h in merged if h["score"] >= threshold]


def search_by_category(
    category: str,
    query: str,
    top_k: int = 10,
    *,
    days: int = 7,
    widen_days: tuple[int, ...] = (7, 14, 30),
) -> list[dict[str, Any]]:
    """综述型检索：类目硬过滤（主类 or 副类）+ 时间窗 + 类内 dense 排序。

    窗口自动放宽：7 天不足 top_k 依次放宽到 14/30 天（稀疏类目供给保障，
    实验发现：气象灾害类在 7 天窗内常只有 2~3 篇）。
    """
    client = _milvus()
    vec = embed_texts([query])[0]
    base = f'category == "{category}" or array_contains(aux_categories, "{category}")'
    for d in widen_days:
        since = int(time.time()) - d * 86400
        results = client.search(
            COLLECTION, data=[vec], anns_field="dense",
            search_params={"metric_type": "COSINE"},
            filter=f"{base} and publish_ts >= {since}",
            limit=top_k, output_fields=OUTPUT_FIELDS,
        )[0]
        if len(results) >= top_k or d == widen_days[-1]:
            logger.info("类目检索 {} 窗口{}天 命中{}", category, d, len(results))
            return [
                {
                    "article_id": hit["entity"]["article_id"],
                    "title": hit["entity"]["title"],
                    "category": hit["entity"]["category"],
                    "publish_ts": hit["entity"]["publish_ts"],
                    "url": hit["entity"]["url"],
                    "score": hit["distance"],
                }
                for hit in results
            ]
    return []  # 不可达（循环末档必 return）


# ---------- 精排（不变） ----------

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
