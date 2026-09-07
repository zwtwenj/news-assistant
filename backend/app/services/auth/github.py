"""GitHub OAuth 授权码流程：state 防护 + code 换 token + 拉取用户。"""

import secrets
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.core.redis_client import redis_client

_STATE_TTL = 300  # 授权页停留上限 5 分钟
_STATE_KEY = "oauth:gh:state:{}"

_AUTHORIZE = "https://github.com/login/oauth/authorize"
_TOKEN = "https://github.com/login/oauth/access_token"
_USER = "https://api.github.com/user"


def configured() -> bool:
    from app.core.config import get_settings

    s = get_settings()
    return bool(s.github_client_id and s.github_client_secret and s.github_redirect_uri)


def build_login_url(next_path: str | None) -> tuple[str, str]:
    """生成授权 URL（state 一次性存 Redis，value 携带 next）。返回 (url, state)。"""
    from app.core.config import get_settings

    s = get_settings()
    state = secrets.token_urlsafe(24)
    redis_client.setex(_STATE_KEY.format(state), _STATE_TTL, next_path or "/")
    url = (
        f"{_AUTHORIZE}?client_id={s.github_client_id}"
        f"&redirect_uri={quote(s.github_redirect_uri, safe='')}"
        f"&scope=read:user&state={state}&allow_signup=false"
    )
    return url, state


def consume_state(state: str) -> str | None:
    """校验并消费 state（一次性），返回其携带的 next 路径；非法返回 None。"""
    val = redis_client.get(_STATE_KEY.format(state))
    if val is None:
        return None
    redis_client.delete(_STATE_KEY.format(state))
    return str(val)


def exchange_token(code: str) -> str:
    """授权码换 GitHub access_token。失败抛 401。"""
    from app.core.config import get_settings

    s = get_settings()
    resp = httpx.post(
        _TOKEN,
        headers={"Accept": "application/json"},
        data={
            "client_id": s.github_client_id,
            "client_secret": s.github_client_secret,
            "code": code,
            "redirect_uri": s.github_redirect_uri,
        },
        timeout=15,
    )
    data = resp.json()
    token = data.get("access_token")
    if resp.status_code != 200 or not token:
        desc = data.get("error_description", "未知错误")
        raise HTTPException(status_code=401, detail=f"GitHub 授权失败: {desc}")
    return token


def get_github_user(access_token: str) -> dict:
    """拉取 GitHub 用户（需 id 与 login）。失败抛 401。"""
    resp = httpx.get(
        _USER,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="获取 GitHub 用户信息失败")
    data = resp.json()
    if not data.get("id") or not data.get("login"):
        raise HTTPException(status_code=401, detail="GitHub 用户信息不完整")
    return data
