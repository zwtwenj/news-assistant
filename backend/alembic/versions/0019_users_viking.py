"""users 加 viking_user_id（聊天助手的 Viking 记忆库 per-user 画像标识）

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("viking_user_id", sa.String(64), nullable=True))
    # 存量用户回填 news_u_{id}
    op.execute(
        "UPDATE users SET viking_user_id = 'news_u_' || id::text"
        " WHERE viking_user_id IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "viking_user_id")
