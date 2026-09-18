"""合格新闻时间序部分索引：新闻列表/ticker 的 Seq Scan+Sort → 索引直取

WHERE 条件与 C 端 quality=ok 口径完全一致（fetch_status=succeeded 且未删
且未被质检判 bad），排序键与 ORDER BY publish_time DESC NULLS LAST, id DESC
完全一致——查询可按索引顺序直接取 Top N，零排序。

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # CONCURRENTLY 不锁写；alembic 事务性 DDL 下需显式 autocommit 块
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_articles_visible_time
            ON articles (publish_time DESC NULLS LAST, id DESC)
            WHERE deleted_at IS NULL AND fetch_status = 'succeeded'
              AND (content_quality IS NULL OR content_quality <> 'bad')
            """
        )


def downgrade() -> None:
    op.drop_index("ix_articles_visible_time", table_name="articles")
