"""articles_v3：并行迁移新表（strangler fig）——复刻 articles 全列全索引 + category 原生

策略：老表 articles 与老接口完全不动；新系统写入/读取 articles_v3。
数据搬迁由 scripts/migrate_articles_v3.py 幂等执行（含已回填的分类值）。

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "articles_v3",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("feed_id", sa.Integer()),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("publish_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(16)),
        sa.Column("summary", sa.Text()),
        sa.Column("tags", JSONB()),
        sa.Column("category", sa.String(32)),
        sa.Column("aux_categories", JSONB()),
        sa.Column("fetch_status", sa.String(20), nullable=False),
        sa.Column("fetch_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetch_error", sa.Text()),
        sa.Column("ai_status", sa.String(20), nullable=False),
        sa.Column("ai_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_error", sa.Text()),
        sa.Column("embed_status", sa.String(20), nullable=False),
        sa.Column("embed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embed_error", sa.Text()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("content_quality", sa.String(10)),
    )
    # 复刻 articles 的关键索引（列表查询/去重/worker 状态扫全部走原形状）
    op.create_index("ix_v3_url", "articles_v3", ["url"], unique=True)
    op.create_index("ix_v3_feed_id", "articles_v3", ["feed_id"])
    op.create_index("ix_v3_content_hash", "articles_v3", ["content_hash"])
    op.create_index("ix_v3_publish_time", "articles_v3", ["publish_time"])
    op.create_index("ix_v3_category", "articles_v3", ["category"])
    op.create_index("ix_v3_visible_time", "articles_v3",
                    [sa.text("publish_time DESC NULLS LAST"), sa.text("id DESC")],
                    postgresql_where=sa.text(
                        "deleted_at IS NULL AND fetch_status = 'succeeded' "
                        "AND (content_quality IS NULL OR content_quality <> 'bad')"))
    for status_col, status_val in (("fetch_status", "pending"), ("ai_status", "pending"),
                                   ("embed_status", "pending")):
        op.create_index(
            f"ix_v3_{status_col[:5]}_pending", "articles_v3", [status_col],
            postgresql_where=sa.text(f"deleted_at IS NULL AND {status_col} = '{status_val}'"))


def downgrade() -> None:
    op.drop_table("articles_v3")
