"""HTTP 请求日志（request_logs）：每次 API 请求一条，admin 可查询。

写入方：core/request_logging.py 的 ASGI 中间件（响应完成后异步收尾落库）。
记录内容：方法/路径/查询串/状态码/耗时/user_id/IP/请求头/入参/出参/错误摘要。

脱敏与限额：
- 请求头走白名单（authorization/cookie 等凭证头不落库）
- 请求体截断 4KB，password/code/token 等键值替换为 ***
- 出参仅记录 application/json 且 <16KB 的响应（SSE 流式只记状态与耗时）
保留策略：beat 每日清理 14 天前的记录（app.tasks.news.cleanup_request_logs）。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(256), index=True)
    query: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[int] = mapped_column(Integer, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    # JWT 无状态解码 payload.sub 即 user_id，不查库零开销；匿名请求为 NULL
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    # headers 白名单落库（content-type/user-agent/origin/referer 等）
    request_headers: Mapped[dict | None] = mapped_column(JSONB)
    # 入参/出参截断存储；敏感键值已脱敏；SSE 流式响应不记出参
    request_body: Mapped[str | None] = mapped_column(Text)
    response_body: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
