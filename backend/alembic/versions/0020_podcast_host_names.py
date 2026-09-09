"""podcasts 加 host_names（创建时主播名字快照，脚本生成注入 prompt）

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # JSONB 数组：["主播A名"] 或 ["A名", "B名"]；存量行 NULL（生成时回退无人设名）
    op.add_column("podcasts", sa.Column("host_names", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("podcasts", "host_names")
