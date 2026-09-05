"""主播配置（后管维护，C 端播客生成页选择）。

persona 即脚本提示词：单人模式作 script_prompt，双人模式作 A/B 人设；
播客创建时快照到 podcasts 现有列，主播后续编辑不影响历史。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminHost(Base):
    __tablename__ = "admin_hosts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    voice_id: Mapped[str] = mapped_column(String(128))  # MiniMax voice_id，透传 t2a_v2
    gender: Mapped[str] = mapped_column(String(20), default="custom", server_default="custom")
    persona: Mapped[str] = mapped_column(Text)  # 人设/脚本提示词（≤2000 字）
    description: Mapped[str | None] = mapped_column(String(200))  # C 端选择卡简介
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
