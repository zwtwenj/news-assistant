"""articles.feed_id 放宽为 nullable（后管手动添加新闻：无采集源，来源用手填 source 文本展示）

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("articles", "feed_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # 反向收紧前需保证无 NULL 行
    op.execute("DELETE FROM articles WHERE feed_id IS NULL")
    op.alter_column("articles", "feed_id", existing_type=sa.Integer(), nullable=False)
