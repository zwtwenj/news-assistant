"""podcasts.quality_review：质量评审产物（终态路由：合格自动 TTS，不合格待用户决断）

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "podcasts",
        sa.Column("quality_review", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("podcasts", "quality_review")
