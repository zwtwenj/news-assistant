"""tag_words 加 embedding 列（标签向量化：query 与词表余弦匹配，替代 LLM 挑标签）

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tag_words", sa.Column("embedding", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("tag_words", "embedding")
