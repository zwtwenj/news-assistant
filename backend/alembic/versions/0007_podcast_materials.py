"""podcasts.materials（素材命中清单：这期引用了哪些新闻）

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "podcasts",
        sa.Column("materials", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("podcasts", "materials")
