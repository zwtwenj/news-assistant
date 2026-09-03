"""podcasts.target_minutes（目标时长，脚本生成的一等参数）

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("podcasts", sa.Column("target_minutes", sa.Integer(), nullable=False,
                                        server_default="4"))


def downgrade() -> None:
    op.drop_column("podcasts", "target_minutes")
