"""C 端主播选择接口（读 admin_hosts，仅暴露可用的：启用 + 未删 + 预置/复刻成功）。"""

from fastapi import APIRouter

from app.api.deps import DB, CurrentUser
from app.models.admin_host import AdminHost
from app.schemas.host import HostOut
from app.services.storage import oss as oss_svc

router = APIRouter(prefix="/hosts", tags=["hosts"])


@router.get("")
def list_hosts(_user: CurrentUser, db: DB) -> list[HostOut]:
    rows = (
        db.query(AdminHost)
        .filter(
            AdminHost.deleted_at.is_(None),
            AdminHost.enabled.is_(True),
            AdminHost.clone_status.in_(("preset", "active")),
        )
        .order_by(AdminHost.sort_order, AdminHost.id)
        .all()
    )
    out = []
    for r in rows:
        item = HostOut.model_validate(r)
        if r.sample_path:  # 试听直链（复刻成功的主播才有）
            item.sample_url = oss_svc.public_url(r.sample_path)
        out.append(item)
    return out
