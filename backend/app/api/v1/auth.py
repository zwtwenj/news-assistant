from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response

from app.api.deps import ACCESS_COOKIE, DB, REFRESH_COOKIE
from app.core.config import get_settings
from app.schemas.auth import CaptchaOut, LoginIn, RefreshIn, SmsSendIn, TokenPair
from app.services.auth import service as auth_svc

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
    # refresh cookie 只在 auth 路径下携带，缩小暴露面
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


@router.post("/refresh")
def refresh(
    body: RefreshIn,
    db: DB,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenPair:
    raw = body.refresh_token or refresh_token
    if not raw:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="缺少 refresh token")
    pair = auth_svc.rotate_refresh(db, raw)
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
