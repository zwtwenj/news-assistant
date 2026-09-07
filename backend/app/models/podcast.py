from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 状态机：pending → scripting → synthesizing → composing → succeeded / failed
P_STATUSES = ("pending", "scripting", "synthesizing", "composing", "succeeded", "failed")


class Podcast(Base):
    __tablename__ = "podcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(10))  # single / dual

    # 两层提示词（plan-podcast §0）：脚本提示词=怎么写（双人 A/B 各一段），话题提示词=播什么
    script_prompt: Mapped[str | None] = mapped_column(Text)  # 单人模式
    script_prompt_a: Mapped[str | None] = mapped_column(Text)  # 双人 A 人设
    script_prompt_b: Mapped[str | None] = mapped_column(Text)  # 双人 B 人设
    topic_prompt: Mapped[str] = mapped_column(Text)  # 播什么（检索素材用）
    # 目标时长（分钟）：一等参数，反推素材条数与脚本长度（plan-podcast §5.1）
    target_minutes: Mapped[int] = mapped_column(Integer, default=4, server_default="4")

    voice_a: Mapped[str] = mapped_column(String(64))
    voice_b: Mapped[str | None] = mapped_column(String(64))  # 双人模式

    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)

    script: Mapped[list | None] = mapped_column(JSONB)  # [{speaker, text}]
    # 素材命中清单 [{article_id,title,tags,rerank_score}]：本期引用了哪些新闻（可追溯）
    materials: Mapped[list | None] = mapped_column(JSONB)
    # query 重写产物 {tags, rag_query, template{opening,ending}, via}：多节点拆分 JSON，后管可调试
    query_rewrite: Mapped[dict | None] = mapped_column(JSONB)
    audio_url: Mapped[str | None] = mapped_column(String(300))
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 后管禁用标记：非 NULL 时 C 端不可见（区别于软删 deleted_at，可恢复显示）
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


Index("ix_podcasts_user_active", Podcast.user_id,
      postgresql_where=Podcast.deleted_at.is_(None))
