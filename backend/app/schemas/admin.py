"""后管 schemas：管理员认证 + 主播配置。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

PERSONA_MAX = 2000  # 与 C 端 script_prompt 上限一致


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class AdminUserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    username: str
    display_name: str | None
    last_login_at: datetime | None


class HostBase(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    voice_id: str = Field(min_length=1, max_length=128)
    gender: str = Field(default="custom", pattern="^(male|female|custom)$")
    persona: str
    description: str | None = Field(default=None, max_length=200)
    enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=9999)

    @field_validator("persona")
    @classmethod
    def check_persona(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= PERSONA_MAX):
            raise ValueError(f"人设提示词长度需在 1~{PERSONA_MAX} 字之间")
        return v


class HostCreate(HostBase):
    pass


class HostUpdate(HostBase):
    pass  # 全量更新（前端编辑弹层提交完整字段）


class HostOut(HostBase):
    model_config = {"from_attributes": True}

    id: int
    created_at: datetime
    updated_at: datetime
