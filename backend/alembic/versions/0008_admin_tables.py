"""后管表：admin_users（管理员）+ admin_hosts（主播配置，种子自 voices.py）

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 主播种子：迁自 voices.py 的 5 个音色 + 默认人设（迁移后 C 端旧音色链路退役）
HOST_SEEDS = [
    ("闻远", "presenter_male", "male",
     "沉稳专业的新闻主播，语速适中，口吻客观权威，每条新闻结尾带一句简短点评",
     "沉稳播报男声", 1),
    ("婉清", "presenter_female", "female",
     "端庄大方的新闻女主播，条理清晰，语调平稳，善于串联多条资讯",
     "沉稳播报女声", 2),
    ("燕三", "male-qn-qingse", "male",
     "年轻活泼的资讯主播，语速偏快，语气轻松接地气，点评带点幽默",
     "少年男声", 3),
    ("秋怡", "female-shaonv", "female",
     "亲切自然的少女主播，语气温柔明快，适合轻松话题的资讯播报",
     "少年女声", 4),
    ("文杰", "news-host-wenjie01", "custom",
     "沉稳亲切的新闻主播，口吻自然，像朋友聊天一样讲新闻，结尾给一句走心点评",
     "复刻定制音色", 5),
]


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_admin_users_username", "admin_users", ["username"], unique=True)

    op.create_table(
        "admin_hosts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("voice_id", sa.String(128), nullable=False),
        sa.Column("gender", sa.String(20), nullable=False, server_default="custom"),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    hosts = sa.table(
        "admin_hosts",
        sa.column("name", sa.String),
        sa.column("voice_id", sa.String),
        sa.column("gender", sa.String),
        sa.column("persona", sa.Text),
        sa.column("description", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        hosts,
        [
            {
                "name": n, "voice_id": v, "gender": g,
                "persona": p, "description": d, "sort_order": s,
            }
            for n, v, g, p, d, s in HOST_SEEDS
        ],
    )


def downgrade() -> None:
    op.drop_table("admin_hosts")
    op.drop_index("ix_admin_users_username", table_name="admin_users")
    op.drop_table("admin_users")
