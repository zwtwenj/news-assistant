"""动态标签词表（表结构由 news 仓库 alembic 管理）。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TagWord(Base):
    __tablename__ = "tag_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(64), unique=True)
    # 标签向量（text-embedding-v4, 1024 维 JSON 数组）：query 与词表余弦匹配用
    embedding: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
