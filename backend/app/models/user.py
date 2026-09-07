from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # nullable：GitHub OAuth 登录用户无手机号（以 github_id 标识）
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    # nullable：支持纯验证码登录（M1 认证模块）
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # GitHub OAuth：github_id 全局唯一；github_login 为展示名（GitHub 用户名，可能改名）
    github_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    github_login: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    # last_login_at：后管用户管理展示
    # disabled_at = 停用/启用操作时间，早于它签发的 token 全部作废（再启用需重新登录）
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
