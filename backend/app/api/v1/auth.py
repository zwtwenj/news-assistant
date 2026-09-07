from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response

from app.api.deps import ACCESS_COOKIE, DB, REFRESH_COOKIE
from app.core.config import get_settings
from app.core.errcode import REFRESH_INVALID, VALIDATION, ApiError
from app.models.user import User
from app.schemas.auth import (
    CaptchaOut,
    DevLoginIn,
    GithubCallbackIn,
    GithubCallbackPair,
    GithubLoginOut,
    LoginIn,
    RefreshIn,
    SmsSendIn,
    TokenPair,
    UserOut,
)
from app.services.auth import github as github_svc
from app.services.auth import service as auth_svc
from app.services.auth.jwt import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    """开发环境经 Next rewrites 代理，取 X-Forwarded-For 首段。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_auth_cookies(response: Response, pair: TokenPair) -> None:
    settings = get_settings()
    secure = settings.cookie_secure  # 与 ENV 解耦：由是否 HTTPS 决定，而非环境名
    response.set_cookie(
        ACCESS_COOKIE,
        pair.access_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=pair.access_expires_in,
    )
    # refresh cookie 只在 auth 路径下携带，缩小暴露面（dev-login 无 refresh 不种）
    if pair.refresh_token:
        response.set_cookie(
            REFRESH_COOKIE,
            pair.refresh_token,
            httponly=True,
            samesite="lax",
            secure=secure,
            max_age=settings.jwt_refresh_ttl_days * 86400,
            path="/api/v1/auth",
        )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/captcha")
def get_captcha() -> CaptchaOut:
    captcha_id, data_url = auth_svc.captcha_svc.generate_captcha()
    return CaptchaOut(captcha_id=captcha_id, image_base64=data_url)


@router.post("/sms/send", status_code=204)
def send_sms(body: SmsSendIn, request: Request) -> None:
    auth_svc.send_sms_code(body.phone, body.captcha_id, body.captcha_code, _client_ip(request))


@router.post("/login")
def login(body: LoginIn, db: DB, response: Response) -> TokenPair:
    pair = auth_svc.login_with_code(db, body.phone, body.code)
    _set_auth_cookies(response, pair)
    return pair


@router.post("/dev-login", include_in_schema=False)
def dev_login(body: DevLoginIn, db: DB, response: Response) -> TokenPair:
    """本地开发测试登录：免短信，签发 30 天 access token（生产 env=prod 返回 404）。"""
    if get_settings().env == "prod":
        raise HTTPException(status_code=404, detail="Not Found")
    user = db.query(User).filter(User.phone == body.phone).first()
    if user is None:
        user = User(phone=body.phone, last_login_at=datetime.now(UTC))
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user.status == "banned":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    else:
        user.last_login_at = datetime.now(UTC)
        db.commit()
    access, ttl = create_access_token(user.id, ttl_minutes=30 * 24 * 60)  # 30 天
    pair = TokenPair(
        access_token=access,
        refresh_token="",
        access_expires_in=ttl,
        user=UserOut.model_validate(user),
    )
    _set_auth_cookies(response, pair)
    return pair


@router.get("/github/login", include_in_schema=False)
def github_login(next_path: str = "/") -> GithubLoginOut:
    """返回 GitHub 授权页 URL（state 存 Redis 携带 next；未配置凭据时给校验错误码）。"""
    if not github_svc.configured():
        raise ApiError(400, VALIDATION, "GitHub 登录未配置")
    if not next_path.startswith("/"):  # 防开放跳转
        next_path = "/"
    url, _ = github_svc.build_login_url(next_path)
    return GithubLoginOut(url=url)


@router.post("/github/callback", include_in_schema=False)
def github_callback(body: GithubCallbackIn, db: DB, response: Response) -> GithubCallbackPair:
    """GitHub 授权回调：校验 state → code 换 token → 拉用户 → 建号/登录 → 签发本站双 token。"""
    next_path = github_svc.consume_state(body.state)
    if next_path is None:
        raise HTTPException(status_code=401, detail="授权状态已过期，请重新登录")
    token = github_svc.exchange_token(body.code)
    gh_user = github_svc.get_github_user(token)
    user = auth_svc.login_with_github(db, int(gh_user["id"]), str(gh_user["login"]))
    pair = auth_svc._issue_tokens(db, user)
    _set_auth_cookies(response, pair)
    return GithubCallbackPair(**pair.model_dump(), next=next_path)


@router.post("/refresh")
def refresh(
    body: RefreshIn,
    db: DB,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenPair:
    raw = body.refresh_token or refresh_token
    if not raw:
        raise ApiError(401, REFRESH_INVALID, "缺少 refresh token")
    try:
        pair = auth_svc.rotate_refresh(db, raw)
    except HTTPException as exc:  # 失效/过期/重放攻击 → 统一标 40102（前端据此登出）
        raise ApiError(401, REFRESH_INVALID, str(exc.detail)) from exc
    _set_auth_cookies(response, pair)
    return pair


@router.post("/logout")
def logout(
    db: DB,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> dict:
    if refresh_token:
        auth_svc.revoke_refresh(db, refresh_token)
    _clear_auth_cookies(response)
    return {"status": "ok"}
