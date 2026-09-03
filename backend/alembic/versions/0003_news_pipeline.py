"""新闻流水线：feeds + articles 表

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feeds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_feeds_url", "feeds", ["url"], unique=True)

    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feed_id", sa.Integer(), sa.ForeignKey("feeds.id"), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("publish_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(16), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("fetch_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("fetch_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetch_error", sa.Text(), nullable=True),
        sa.Column("ai_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("ai_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_error", sa.Text(), nullable=True),
        sa.Column("embed_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("embed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embed_error", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_articles_feed_id", "articles", ["feed_id"])
    op.create_index("ix_articles_url", "articles", ["url"], unique=True)
    op.create_index("ix_articles_publish_time", "articles", ["publish_time"])
    op.create_index("ix_articles_content_hash", "articles", ["content_hash"])
    # 部分索引：流水线每阶段只扫 pending（沿用 demo 状态机，扫描高效）
    op.create_index(
        "ix_articles_fetch_pending", "articles", ["fetch_status"],
        postgresql_where=sa.text("deleted_at IS NULL AND fetch_status = 'pending'"),
    )
    op.create_index(
        "ix_articles_ai_pending", "articles", ["ai_status"],
        postgresql_where=sa.text("deleted_at IS NULL AND ai_status = 'pending'"),
    )
    op.create_index(
        "ix_articles_embed_pending", "articles", ["embed_status"],
        postgresql_where=sa.text("deleted_at IS NULL AND embed_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_articles_embed_pending", table_name="articles")
    op.drop_index("ix_articles_ai_pending", table_name="articles")
    op.drop_index("ix_articles_fetch_pending", table_name="articles")
    op.drop_index("ix_articles_content_hash", table_name="articles")
    op.drop_index("ix_articles_publish_time", table_name="articles")
    op.drop_index("ix_articles_url", table_name="articles")
    op.drop_index("ix_articles_feed_id", table_name="articles")
    op.drop_table("articles")
    op.drop_index("ix_feeds_url", table_name="feeds")
    op.drop_table("feeds")
