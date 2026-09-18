"""request_logs 接口分析列：route 模板/db 耗时/request_id/客户端分段耗时

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # route：FastAPI 路由模板（/news/articles/{id}），接口分析的聚合单元
    op.add_column("request_logs", sa.Column("route", sa.String(256)))
    # db_time_ms：本请求内全部 SQL 耗时（SQLAlchemy 游标事件累加）
    op.add_column("request_logs", sa.Column("db_time_ms", sa.Integer()))
    # request_id：本次请求的关联 ID，响应头 X-Request-Id 回传，客户端分段上报靠它关联
    op.add_column("request_logs", sa.Column("request_id", sa.String(32)))
    op.create_index("ix_request_logs_request_id", "request_logs", ["request_id"])
    # c_*：客户端上报的请求分段耗时（Resource Timing），可空、上报后回填
    op.add_column("request_logs", sa.Column("c_dns_ms", sa.Integer()))
    op.add_column("request_logs", sa.Column("c_tcp_ms", sa.Integer()))
    op.add_column("request_logs", sa.Column("c_tls_ms", sa.Integer()))
    op.add_column("request_logs", sa.Column("c_ttfb_ms", sa.Integer()))
    op.add_column("request_logs", sa.Column("c_download_ms", sa.Integer()))
    op.add_column("request_logs", sa.Column("c_total_ms", sa.Integer()))


def downgrade() -> None:
    op.drop_index("ix_request_logs_request_id", table_name="request_logs")
    for col in (
        "c_total_ms", "c_download_ms", "c_ttfb_ms", "c_tls_ms",
        "c_tcp_ms", "c_dns_ms", "request_id", "db_time_ms", "route",
    ):
        op.drop_column("request_logs", col)
