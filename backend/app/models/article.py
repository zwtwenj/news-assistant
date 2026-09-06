from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 各阶段状态（文章级状态机，沿用 demo 设计）
PENDING, SUCCEEDED, FAILED, SKIPPED = "pending", "succeeded", "failed", "skipped"
MAX_ATTEMPTS = 3


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    # nullable：后管手动添加的新闻无采集源（来源用手填 source 文本，仅展示）
    feed_id: Mapped[int | None] = mapped_column(ForeignKey("feeds.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(200))  # 归属（合规保留来源）
    publish_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # 入库时先放 RSS summary 兜底，scrape 成功后覆盖为正文
    content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str | None] = mapped_column(String(16), index=True)  # simhash hex

    summary: Mapped[str | None] = mapped_column(Text)  # LLM 摘要
    tags: Mapped[list | None] = mapped_column(JSONB)

    # 入库质量门禁：null=未检 / good / suspect / bad（bad 不向量化，plan 质量四层防御）
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
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


Index("ix_articles_fetch_pending", Article.fetch_status,
      postgresql_where=(Article.deleted_at.is_(None) & (Article.fetch_status == PENDING)))
Index("ix_articles_ai_pending", Article.ai_status,
      postgresql_where=(Article.deleted_at.is_(None) & (Article.ai_status == PENDING)))
Index("ix_articles_embed_pending", Article.embed_status,
      postgresql_where=(Article.deleted_at.is_(None) & (Article.embed_status == PENDING)))
