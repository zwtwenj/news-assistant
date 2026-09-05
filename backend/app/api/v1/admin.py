"""后管 API：独立账号认证 + 主播配置 CRUD（plan-admin §2）。

- 登录限频：IP 维度 5 次/10 分钟（Redis，复用播客限频写法）
- 账号只能经 scripts/create_admin.py 创建，无注册端点
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ADMIN_COOKIE, DB, CurrentAdmin
from app.core.config import get_settings
from app.core.redis_client import redis_client
from app.models.admin_host import AdminHost
from app.models.admin_user import AdminUser
from app.schemas.admin import (
    AdminLoginIn,
    AdminUserOut,
    HostCreate,
    HostOut,
    HostUpdate,
)
from app.services.auth.jwt import create_access_token
from app.services.auth.password import verify_password

router = APIRouter(prefix="/admin", tags=["admin"])

LOGIN_LIMIT = 5
LOGIN_WINDOW = 600  # 秒


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_admin_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        ADMIN_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        max_age=max_age,
    )


# ---------- 认证 ----------


@router.post("/auth/login")
def admin_login(body: AdminLoginIn, db: DB, request: Request, response: Response) -> AdminUserOut:
    ip = _client_ip(request)
    key = f"quota:admin:login:{ip}"
    if redis_client.incr(key) > LOGIN_LIMIT:
        redis_client.decr(key)
        raise HTTPException(status_code=429, detail="尝试过于频繁，请 10 分钟后再试")
    redis_client.expire(key, LOGIN_WINDOW)

    admin = db.query(AdminUser).filter(AdminUser.username == body.username).first()
    # 统一模糊错误，避免用户名枚举
    ok = admin is not None and admin.status == "active"
    if not ok or not verify_password(body.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token, ttl = create_access_token(admin.id, scope="admin")
    _set_admin_cookie(response, token, ttl)
    admin.last_login_at = datetime.now(UTC)
    db.commit()
    return AdminUserOut.model_validate(admin)


@router.post("/auth/logout")
def admin_logout(response: Response) -> dict:
    response.delete_cookie(ADMIN_COOKIE)
    return {"status": "ok"}


@router.get("/auth/me")
def admin_me(admin: CurrentAdmin) -> AdminUserOut:
    return AdminUserOut.model_validate(admin)


# ---------- 主播配置 ----------


@router.get("/hosts")
def list_hosts(db: DB, _admin: CurrentAdmin) -> list[HostOut]:
    rows = db.query(AdminHost).order_by(AdminHost.sort_order, AdminHost.id).all()
    return [HostOut.model_validate(r) for r in rows]


@router.post("/hosts", status_code=201)
def create_host(body: HostCreate, db: DB, _admin: CurrentAdmin) -> HostOut:
    host = AdminHost(**body.model_dump())
    db.add(host)
    db.commit()
    db.refresh(host)
    return HostOut.model_validate(host)


def _get_host(db, host_id: int) -> AdminHost:
    host = db.get(AdminHost, host_id)
    if host is None:
        raise HTTPException(status_code=404, detail="主播不存在")
    return host


@router.put("/hosts/{host_id}")
def update_host(host_id: int, body: HostUpdate, db: DB, _admin: CurrentAdmin) -> HostOut:
    host = _get_host(db, host_id)
    for k, v in body.model_dump().items():
        setattr(host, k, v)
    db.commit()
    db.refresh(host)
    return HostOut.model_validate(host)


@router.delete("/hosts/{host_id}")
def delete_host(host_id: int, db: DB, _admin: CurrentAdmin) -> dict:
    # 播客快照式存储无 FK 引用，直接硬删
    host = _get_host(db, host_id)
    db.delete(host)
    db.commit()
    return {"status": "ok"}
