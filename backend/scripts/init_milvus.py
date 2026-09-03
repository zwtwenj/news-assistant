"""Milvus news_articles collection 初始化（幂等）。

- 不存在 → 创建 + 建索引
- 存在且结构正确 → 跳过（仅补缺失的向量索引）
- 存在但结构不符（如 publish_ts 建成了 varchar）→ **drop 后重建**（仅当行数为 0，防误删数据）

注意：火山 Milvus Serverless 只支持 AUTOINDEX（服务端托管索引参数），不指定 HNSW。
用法：uv run python scripts/init_milvus.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

from app.core.config import get_settings

COLLECTION = "news_articles"
DIM = 1024  # 百炼 text-embedding-v4

# 期望结构：publish_ts 必须 int64（时间范围过滤），tags 为 Array<varchar>
EXPECTED = {
    "article_id": DataType.INT64,
    "vector": DataType.FLOAT_VECTOR,
    "title": DataType.VARCHAR,
    "publish_ts": DataType.INT64,
    "tags": DataType.ARRAY,
    "url": DataType.VARCHAR,
}


def build_schema() -> CollectionSchema:
    return CollectionSchema(
        fields=[
            FieldSchema("article_id", DataType.INT64, is_primary=True),
            FieldSchema("vector", DataType.FLOAT_VECTOR, dim=DIM),
            FieldSchema("title", DataType.VARCHAR, max_length=512),
            FieldSchema("publish_ts", DataType.INT64),  # Unix 秒，范围过滤用
            FieldSchema(
                "tags", DataType.ARRAY, element_type=DataType.VARCHAR,
                max_capacity=10, max_length=64,
            ),
            FieldSchema("url", DataType.VARCHAR, max_length=1000),
        ],
        description="新闻向量（PG articles 为事实源，可重建）",
    )


def ensure_index(client: MilvusClient) -> None:
    """向量索引：已有则跳过，缺失则建 AUTOINDEX/COSINE（Serverless 托管）。"""
    if client.list_indexes(COLLECTION):
        logger.info("索引已存在: {}", client.list_indexes(COLLECTION))
        return
    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_index(collection_name=COLLECTION, index_params=index_params)
    logger.info("向量索引创建完成（AUTOINDEX/COSINE）")


def main() -> None:
    s = get_settings()
    client = MilvusClient(uri=s.milvus_uri, token=s.milvus_token)

    if client.has_collection(COLLECTION):
        desc = client.describe_collection(COLLECTION)
        actual = {f["name"]: DataType(f["type"]) for f in desc["fields"]}
        mismatch = {k: (v, actual.get(k)) for k, v in EXPECTED.items() if actual.get(k) != v}
        if not mismatch:
            logger.info("collection {} 结构正确", COLLECTION)
            ensure_index(client)
            return
        rows = client.get_collection_stats(COLLECTION)["row_count"]
        if rows > 0:
            logger.error(
                "collection {} 结构不符 {} 且有 {} 行数据， refusing 自动重建，请人工处理",
                COLLECTION, mismatch, rows,
            )
            sys.exit(1)
        logger.warning("结构不符 {}（空表），drop 重建", mismatch)
        client.drop_collection(COLLECTION)

    client.create_collection(collection_name=COLLECTION, schema=build_schema())
    ensure_index(client)
    # 校验建完的结构
    desc = client.describe_collection(COLLECTION)
    actual = {f["name"]: DataType(f["type"]) for f in desc["fields"]}
    assert actual == EXPECTED, f"重建后结构仍不符: {actual}"
    logger.info("collection {} 创建完成（{} 字段）", COLLECTION, len(actual))


if __name__ == "__main__":
    main()
