"""articles_v3 模型（并行迁移新表，表结构由 news 仓库 alembic 0026 管理）。

与 Article 的关系：Article/老接口/老管道完全不动；新系统（v3 列表接口与
后续切换的管道）读写本表。列集合 = articles + category/aux_categories 原生。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PENDING = "pending"
SUCCEEDED = "succeeded"
FAILED = "failed"
SKIPPED = "skipped"
MAX_ATTEMPTS = 3


class ArticleV3(Base):
    __tablename__ = "articles_v3"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feed_id: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(200))
    publish_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 入库时先放 RSS summary 兜底，scrape 成功后覆盖为正文
    content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str | None] = mapped_column(String(16), index=True)  # simhash hex

    summary: Mapped[str | None] = mapped_column(Text)  # LLM 摘要
    tags: Mapped[list | None] = mapped_column(JSONB)  # 展示/统计用（检索已退役）
    # 封闭类目（检索路由层）：主类 18 选 1（白名单校验）+ 副类 ≤2
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    aux_categories: Mapped[list | None] = mapped_column(JSONB)

    # 入库质量门禁：null=未检 / good / suspect / bad（bad 不向量化）
    content_quality: Mapped[str | None] = mapped_column(String(10))

    # 三阶段状态机：fetch=抓正文, ai=打标, embed=向量化
    fetch_status: Mapped[str] = mapped_column(String(20), default=PENDING, server_default=PENDING)
    fetch_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    fetch_error: Mapped[str | None] = mapped_column(Text)
    ai_status: Mapped[str] = mapped_column(String(20), default=PENDING, server_default=PENDING)
    ai_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    ai_error: Mapped[str | None] = mapped_column(Text)
    embed_status: Mapped[str] = mapped_column(String(20), default=PENDING, server_default=PENDING)
    embed_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    embed_error: Mapped[str | None] = mapped_column(Text)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
