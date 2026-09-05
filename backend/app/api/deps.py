from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.admin_user import AdminUser
from app.models.user import User
from app.services.auth.jwt import decode_access_token

DB = Annotated[Session, Depends(get_db)]

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
ADMIN_COOKIE = "admin_token"


def _extract_token(
    access_token: str | None, authorization: str | None
) -> str | None:
    """优先 httpOnly cookie；兼容 Authorization: Bearer（脚本/测试用）。"""
    token = access_token
    if token is None and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    return token or None


def get_current_user(
    db: DB,
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _extract_token(access_token, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_access_token(token)
    # scope 双向隔离：admin token 不能当用户用（存量无 scope 视为 user）
    if payload is None or payload.get("scope", "user") != "user":
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.get(User, int(payload["sub"]))
    if user is None or user.status == "banned":
        raise HTTPException(status_code=401, detail="账号不可用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_admin(
    db: DB,
    admin_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> AdminUser:
    """后管鉴权：独立 admin_token cookie（或 Bearer），JWT scope 必须为 admin。"""
    token = _extract_token(admin_token, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_access_token(token)
    if payload is None or payload.get("scope") != "admin":
        raise HTTPException(status_code=401, detail="未登录或凭证类型错误")
    admin = db.get(AdminUser, int(payload["sub"]))
    if admin is None or admin.status != "active":
        raise HTTPException(status_code=401, detail="账号不可用")
    return admin


CurrentAdmin = Annotated[AdminUser, Depends(get_current_admin)]
