"""podcasts 加 query_rewrite（重写 JSON：tags/rag_query/template，后管详情可调试）
与 disabled_at（后管禁用标记，NULL=显示，非 NULL C 端不可见）

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("podcasts", sa.Column("query_rewrite", JSONB(), nullable=True))
    op.add_column("podcasts", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("podcasts", "disabled_at")
    op.drop_column("podcasts", "query_rewrite")
