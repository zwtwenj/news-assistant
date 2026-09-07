"""users 加 github_id/github_login（GitHub OAuth 登录）；phone 放宽 nullable（GitHub 用户无手机号）

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("github_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("github_login", sa.String(100), nullable=True))
    op.create_unique_constraint("uq_users_github_id", "users", ["github_id"])
    op.alter_column("users", "phone", existing_type=sa.String(20), nullable=True)


def downgrade() -> None:
    # 回滚前需保证无 NULL/无 GitHub 用户
    op.execute("DELETE FROM users WHERE phone IS NULL")
    op.alter_column("users", "phone", existing_type=sa.String(20), nullable=False)
    op.drop_constraint("uq_users_github_id", "users", type_="unique")
    op.drop_column("users", "github_login")
    op.drop_column("users", "github_id")
