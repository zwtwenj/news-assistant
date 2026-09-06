import re

from pydantic import BaseModel, field_validator

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


class CaptchaOut(BaseModel):
    captcha_id: str
    image_base64: str  # data:image/png;base64,... 直接给 <img src>


class SmsSendIn(BaseModel):
    phone: str
    captcha_id: str
    captcha_code: str

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        if not PHONE_RE.match(v):
            raise ValueError("手机号格式不正确")
        return v


class LoginIn(BaseModel):
    phone: str
    code: str  # 短信验证码（6位）

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        if not PHONE_RE.match(v):
            raise ValueError("手机号格式不正确")
        return v

    @field_validator("code")
    @classmethod
    def check_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4,8}", v):
            raise ValueError("验证码格式不正确")
        return v


class RefreshIn(BaseModel):
    # body 传 refresh_token 为空也行：优先读 httpOnly cookie
    refresh_token: str | None = None


class DevLoginIn(BaseModel):
    """本地开发测试登录（跳过短信）；生产环境端点 404。"""

    phone: str

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        if not PHONE_RE.match(v):
            raise ValueError("手机号格式不正确")
        return v


class UserOut(BaseModel):
    id: int
    phone: str
    status: str
    created_at: str

    model_config = {"from_attributes": True}

    @field_validator("created_at", mode="before")
    @classmethod
    def fmt_created_at(cls, v) -> str:  # noqa: ANN001
        return v.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v, "strftime") else str(v)


class TokenPair(BaseModel):
    """login/refresh 的统一响应（token 同时通过 set-cookie 下发）。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_expires_in: int  # 秒
    user: UserOut
