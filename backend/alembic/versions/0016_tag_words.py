"""动态标签词表（自生长）：打标 prompt 注入词表，LLM 可补充 new_tags 使词表自生长。

词表事实源 = tag_words 表（每日流水线从 articles.tags 聚合重建，幂等自愈）；
Redis 存 JSON array 快照供打标/检索高频读取。

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_CATEGORIES = ["娱乐", "体育", "科技", "财经", "社会", "国际",
                   "军事", "教育", "健康", "汽车", "游戏", "其他"]


def upgrade() -> None:
    op.create_table(
        "tag_words",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("word", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_tag_words_word", "tag_words", ["word"])
    # seed：旧分类 + 存量文章 DISTINCT tags（兼容不重打，存量标签自动进词表）
    for w in SEED_CATEGORIES:
        stmt = sa.text("INSERT INTO tag_words (word) VALUES (:w) ON CONFLICT DO NOTHING")
        op.execute(stmt.bindparams(w=w))
    op.execute(
        """
        INSERT INTO tag_words (word)
        SELECT DISTINCT jsonb_array_elements_text(tags)
        FROM articles
        WHERE deleted_at IS NULL AND tags IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("tag_words")
