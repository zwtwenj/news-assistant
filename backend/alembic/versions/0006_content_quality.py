"""articles.content_quality（入库质量门禁字段）

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # null=未检（兼容存量），good/suspect/bad 由质检写入；embed 门禁按 != 'bad' 放行
    op.add_column(
        "articles",
        sa.Column("content_quality", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("articles", "content_quality")
