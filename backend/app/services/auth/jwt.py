"""JWT 签发与校验（PyJWT）。access token 无状态不落库；refresh token 见 service.py。"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings

_ALGO = "HS256"


def create_access_token(user_id: int) -> tuple[str, int]:
    """返回 (token, 有效期秒数)。"""
    settings = get_settings()
    ttl = settings.jwt_access_ttl_minutes * 60
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGO), ttl


def decode_access_token(token: str) -> dict[str, Any] | None:
    """校验签名与过期；token 非法/过期/type 不对均返回 None（调用方统一按 401 处理）。"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    return payload
