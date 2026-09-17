"""request_logs 请求日志表（每次 API 请求一条：入参/出参/耗时/user_id）

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(256), nullable=False),
        sa.Column("query", sa.String(512)),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer()),
        sa.Column("ip", sa.String(64)),
        sa.Column("request_headers", JSONB()),
        sa.Column("request_body", sa.Text()),
        sa.Column("response_body", sa.Text()),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_request_logs_ts", "request_logs", ["ts"])
    op.create_index("ix_request_logs_path", "request_logs", ["path"])
    op.create_index("ix_request_logs_status", "request_logs", ["status"])
    op.create_index("ix_request_logs_user_id", "request_logs", ["user_id"])


def downgrade() -> None:
    op.drop_table("request_logs")
