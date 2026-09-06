from typing import Annotated

from fastapi import Cookie, Depends, Header
from sqlalchemy.orm import Session

from app.core.errcode import ACCOUNT_UNUSABLE, TOKEN_EXPIRED, UNAUTHED, ApiError
from app.db.session import get_db
from app.models.user import User
from app.services.auth.jwt import decode_access_token

DB = Annotated[Session, Depends(get_db)]

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


def get_current_user(
    db: DB,
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """优先 httpOnly cookie；兼容 Authorization: Bearer（脚本/测试用）。"""
    token = access_token
    if token is None and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    if not token:
        raise ApiError(401, UNAUTHED, "未登录")
    payload = decode_access_token(token)
    # scope 校验：admin token（news-admin 独立项目）不能当用户用；存量无 scope 视为 user
    if payload is None or payload.get("scope", "user") != "user":
        raise ApiError(401, TOKEN_EXPIRED, "登录已过期，请重新登录")
    user = db.get(User, int(payload["sub"]))
    if user is None or user.status == "banned":
        raise ApiError(401, ACCOUNT_UNUSABLE, "账号不可用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
