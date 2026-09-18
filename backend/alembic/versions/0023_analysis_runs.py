"""analysis_runs 接口按需分析任务表（后管按钮触发，结果 JSON 落库）

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("window_days", sa.Integer(), nullable=False),
        # running / done / failed
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("result", JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("elapsed_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"])


def downgrade() -> None:
    op.drop_table("analysis_runs")
