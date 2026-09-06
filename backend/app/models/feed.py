from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Feed(Base):
    """RSS 数据源。管理平台（M2）提供 CRUD，本期用种子脚本维护。"""

    __tablename__ = "feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 软删除：保住 FK 与新闻来源展示（news-admin 后管维护）
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
