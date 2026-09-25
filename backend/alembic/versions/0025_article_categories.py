"""articles 加封闭类目列（category 主类 + aux_categories 副类）——检索路由层

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("category", sa.String(32)))
    op.add_column("articles", sa.Column("aux_categories", JSONB()))
    op.create_index("ix_articles_category", "articles", ["category"])


def downgrade() -> None:
    op.drop_index("ix_articles_category", table_name="articles")
    op.drop_column("articles", "aux_categories")
    op.drop_column("articles", "category")
