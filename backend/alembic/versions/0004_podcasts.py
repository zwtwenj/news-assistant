"""podcasts 表（播客合成）

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "podcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("script_prompt", sa.Text(), nullable=True),
        sa.Column("script_prompt_a", sa.Text(), nullable=True),
        sa.Column("script_prompt_b", sa.Text(), nullable=True),
        sa.Column("topic_prompt", sa.Text(), nullable=False),
        sa.Column("voice_a", sa.String(64), nullable=False),
        sa.Column("voice_b", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("script", postgresql.JSONB(), nullable=True),
        sa.Column("audio_url", sa.String(300), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_podcasts_user_id", "podcasts", ["user_id"])
    op.create_index(
        "ix_podcasts_user_active",
        "podcasts",
        ["user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_podcasts_user_active", table_name="podcasts")
    op.drop_index("ix_podcasts_user_id", table_name="podcasts")
    op.drop_table("podcasts")
