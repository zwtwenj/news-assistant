"""客户端接口耗时上报（接口分析标准的客户端侧）。

C 端 fetch 封装用 Resource Timing 分段采集 /api/* 请求耗时，sendBeacon
攒批 POST 到这里，按 request_id 回填 request_logs 的 c_* 列。公开接口：
匿名请求也有日志行；限频防滥用，回填只写 NULL 列防覆盖。
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.redis_client import redis_client
from app.db.session import SessionLocal
from app.models.request_log import RequestLog

router = APIRouter(prefix="/metrics", tags=["metrics"])

_BATCH_MAX = 20
# 单 IP 上报限频：5 条/批攒批下 120 批/分钟已远超正常流量
_RATE_LIMIT = 120
_RATE_WINDOW = 60


class ClientTimingItem(BaseModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{8,32}$", max_length=32)
    dns_ms: int | None = Field(None, ge=0, le=600_000)
    tcp_ms: int | None = Field(None, ge=0, le=600_000)
    tls_ms: int | None = Field(None, ge=0, le=600_000)
    ttfb_ms: int | None = Field(None, ge=0, le=600_000)
    download_ms: int | None = Field(None, ge=0, le=600_000)
    total_ms: int | None = Field(None, ge=0, le=600_000)


class ClientTimingBatch(BaseModel):
    items: list[ClientTimingItem] = Field(min_length=1, max_length=_BATCH_MAX)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


@router.post("/client-timing")
def report_client_timing(batch: ClientTimingBatch, request: Request) -> dict:
    ip = _client_ip(request)
    rate_key = f"metrics:ct:{ip}"
    try:
        if redis_client.incr(rate_key) > _RATE_LIMIT:
            redis_client.expire(rate_key, _RATE_WINDOW)
            return {"updated": 0, "rate_limited": True}
        redis_client.expire(rate_key, _RATE_WINDOW)
    except Exception:  # noqa: BLE001  Redis 故障不挡上报
        pass

    updated = 0
    with SessionLocal() as db:
        for item in batch.items:
            row = (
                db.query(RequestLog)
                .filter(
                    RequestLog.request_id == item.request_id,
                    RequestLog.c_ttfb_ms.is_(None),  # 只回填空列，防重复上报覆盖
                )
                .first()
            )
            if row is None:
                continue
            row.c_dns_ms = item.dns_ms
            row.c_tcp_ms = item.tcp_ms
            row.c_tls_ms = item.tls_ms
            row.c_ttfb_ms = item.ttfb_ms
            row.c_download_ms = item.download_ms
            row.c_total_ms = item.total_ms
            updated += 1
        db.commit()
    return {"updated": updated}
