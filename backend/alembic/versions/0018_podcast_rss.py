"""RSS 分发：podcasts 加 title/description/cover_url/feed_published_at；建 rss_feeds 表

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("podcasts", sa.Column("title", sa.String(200), nullable=True))
    op.add_column("podcasts", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("podcasts", sa.Column("cover_url", sa.String(500), nullable=True))
    # 非空 = 已进入用户 RSS 公开 feed（撤下即置空；平台侧延迟同步）
    op.add_column(
        "podcasts", sa.Column("feed_published_at", TIMESTAMP(timezone=True), nullable=True)
    )

    op.create_table(
        "rss_feeds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("feed_token", sa.String(64), nullable=False),
        sa.Column("channel_title", sa.String(200), nullable=False),
        sa.Column("channel_description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_rss_feeds_user", "rss_feeds", ["user_id"])
    op.create_unique_constraint("uq_rss_feeds_token", "rss_feeds", ["feed_token"])


def downgrade() -> None:
    op.drop_table("rss_feeds")
    op.drop_column("podcasts", "feed_published_at")
    op.drop_column("podcasts", "cover_url")
    op.drop_column("podcasts", "description")
    op.drop_column("podcasts", "title")
