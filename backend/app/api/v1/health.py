from fastapi import APIRouter
from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    """存活探针：进程活着即返回 200。"""
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict:
    """就绪探针：检查 PG 与 Redis 连通性，供 compose/负载均衡使用。"""
    checks: dict[str, str] = {}

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"fail: {exc.__class__.__name__}"

    try:
        redis = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        redis.ping()
        redis.close()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"fail: {exc.__class__.__name__}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
