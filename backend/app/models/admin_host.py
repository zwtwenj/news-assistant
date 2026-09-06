"""主播配置（后管维护，C 端播客生成页选择）。

persona 即脚本提示词：单人模式作 script_prompt，双人模式作 A/B 人设；
播客创建时快照到 podcasts 现有列，主播后续编辑不影响历史。
clone_status 为声音复刻状态机（news-admin 后管维护）：preset 预置 /
cloning 复刻中 / clone_failed / activating 转永久中 / activate_failed /
active 永久——C 端只暴露 preset 与 active。
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
    clone_status: Mapped[str] = mapped_column(
        String(20), default="preset", server_default="preset"
    )
    clone_error: Mapped[str | None] = mapped_column(Text)
    audio_path: Mapped[str | None] = mapped_column(String(300))  # 复刻录音 OSS key
    temp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_path: Mapped[str | None] = mapped_column(String(300))  # 试听音频 OSS key
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 软删除
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
