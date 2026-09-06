"""admin_hosts 声音复刻列（clone 状态机 + OSS 路径 + 软删除）

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "admin_hosts",
        sa.Column("clone_status", sa.String(20), nullable=False, server_default="preset"),
    )
    op.add_column("admin_hosts", sa.Column("clone_error", sa.Text(), nullable=True))
    op.add_column("admin_hosts", sa.Column("audio_path", sa.String(300), nullable=True))
    op.add_column(
        "admin_hosts", sa.Column("temp_expires_at", sa.DateTime(timezone=True), nullable=True
    ))
    op.add_column("admin_hosts", sa.Column("sample_path", sa.String(300), nullable=True))
    op.add_column(
        "admin_hosts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("admin_hosts", "deleted_at")
    op.drop_column("admin_hosts", "sample_path")
    op.drop_column("admin_hosts", "temp_expires_at")
    op.drop_column("admin_hosts", "audio_path")
    op.drop_column("admin_hosts", "clone_error")
    op.drop_column("admin_hosts", "clone_status")
