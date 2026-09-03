"""认证编排：防刷链 → 发码 → 核验 → 注册/登录 → 双 token 签发与轮换。

防刷规则（plan-auth §2.2，全在调阿里云之前）：
  图形验证码 → 同号 60s 冷却 → 同号日限 10 → IP 限频（20/h、100/d）
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redis_client import redis_client
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import TokenPair, UserOut
from app.services.auth import captcha as captcha_svc
from app.services.auth.jwt import create_access_token
from app.services.sms import get_sms_provider

PHONE_DAILY_LIMIT = 10
IP_HOURLY_LIMIT = 20
IP_DAILY_LIMIT = 100


# ---------- 发送验证码 ----------

def send_sms_code(phone: str, captcha_id: str, captcha_code: str, ip: str) -> None:
    if not captcha_svc.check_captcha(captcha_id, captcha_code):
        raise HTTPException(status_code=401, detail="图形验证码错误或已过期")

    # 同号 60s 冷却：SET NX EX，设置失败即冷却中
    if not redis_client.set(f"sms:cd:{phone}", "1", ex=60, nx=True):
        raise HTTPException(status_code=429, detail="发送太频繁，请60秒后再试")

    # 同号日限
    day_key = f"sms:day:{phone}:{datetime.now(UTC):%Y%m%d}"
    if redis_client.incr(day_key) > PHONE_DAILY_LIMIT:
        redis_client.decr(day_key)
        raise HTTPException(status_code=429, detail="今日发送次数已达上限")
    redis_client.expire(day_key, 86400)

    # IP 限频
    hour_key = f"sms:ip:{ip}:{datetime.now(UTC):%Y%m%d%H}"
    day_ip_key = f"sms:ipd:{ip}:{datetime.now(UTC):%Y%m%d}"
    if (
        redis_client.incr(hour_key) > IP_HOURLY_LIMIT
        or redis_client.incr(day_ip_key) > IP_DAILY_LIMIT
    ):
        raise HTTPException(status_code=429, detail="操作太频繁，请稍后再试")
    redis_client.expire(hour_key, 3600)
    redis_client.expire(day_ip_key, 86400)

    if not get_sms_provider().send_code(phone):
        raise HTTPException(status_code=502, detail="短信发送失败，请稍后重试")


# ---------- 登录/自动注册 ----------

def login_with_code(db: Session, phone: str, code: str) -> TokenPair:
    if not get_sms_provider().verify_code(phone, code):
        raise HTTPException(status_code=401, detail="验证码错误或已过期")

    user = db.query(User).filter(User.phone == phone).first()
    if user is None:
        user = User(phone=phone)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user.status == "banned":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return _issue_tokens(db, user)


# ---------- refresh token：签发 / 轮换 / 吊销 ----------

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _issue_tokens(db: Session, user: User) -> TokenPair:
    settings = get_settings()
    access, ttl = create_access_token(user.id)
    raw_refresh = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash_token(raw_refresh),
            expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    db.commit()
    return TokenPair(
        access_token=access,
        refresh_token=raw_refresh,
        access_expires_in=ttl,
        user=UserOut.model_validate(user),
    )


def rotate_refresh(db: Session, raw_refresh: str) -> TokenPair:
    """轮换：旧的 revoke、发新的。已 revoked 的 token 被重放 → 吊销该用户全部会话。"""
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash_token(raw_refresh)).first()
    if rt is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    if rt.revoked_at is not None:
        db.query(RefreshToken).filter(
            RefreshToken.user_id == rt.user_id, RefreshToken.revoked_at.is_(None)
        ).update({"revoked_at": datetime.now(UTC)})
        db.commit()
        raise HTTPException(status_code=401, detail="检测到异常使用，已吊销全部会话")
    if rt.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    rt.revoked_at = datetime.now(UTC)
    user = db.get(User, rt.user_id)
    if user is None or user.status == "banned":
        raise HTTPException(status_code=403, detail="账号不可用")
    return _issue_tokens(db, user)


def revoke_refresh(db: Session, raw_refresh: str) -> None:
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash_token(raw_refresh)).first()
    if rt is not None and rt.revoked_at is None:
        rt.revoked_at = datetime.now(UTC)
        db.commit()
