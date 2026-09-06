"""C 端主播（读 admin_hosts）。"""

from pydantic import BaseModel


class HostOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    gender: str
    description: str | None
    sample_url: str | None = None  # 试听直链（复刻成功的主播才有）
