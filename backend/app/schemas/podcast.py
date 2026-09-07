
from pydantic import BaseModel, Field, field_validator, model_validator

TOPIC_MAX = 500
PROMPT_MAX = 2000


class VoiceOut(BaseModel):
    id: str  # MiniMax voice_id
    name: str  # 展示名，如"燕三（少年男声）"
    gender: str


class PodcastCreate(BaseModel):
    mode: str  # single / dual
    topic_prompt: str
    target_minutes: int = Field(4, ge=1, le=10)  # 目标时长（分钟）：素材上限与脚本长度由它驱动
    host_a: int  # 主播（admin_hosts.id）：后端解析音色 + 人设，快照落库
    host_b: int | None = None

    @field_validator("topic_prompt")
    @classmethod
    def check_topic(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= TOPIC_MAX):
            raise ValueError(f"话题提示词长度需在 1~{TOPIC_MAX} 字之间")
        return v

    @model_validator(mode="after")
    def check_mode_fields(self) -> "PodcastCreate":
        if self.mode not in ("single", "dual"):
            raise ValueError("mode 只能为 single 或 dual")
        if self.mode == "dual":
            if not self.host_b:
                raise ValueError("双人模式需要选择 B 的主播")
            if self.host_b == self.host_a:
                raise ValueError("双人模式两位主播不能相同")
        return self


class PodcastOut(BaseModel):
    id: int
    mode: str
    status: str
    topic_prompt: str
    title: str | None = None  # RSS 分发展示标题（NULL 回退 topic_prompt）
    description: str | None = None
    cover_url: str | None = None
    feed_published_at: str | None = None
    target_minutes: int
    voice_a: str
    voice_b: str | None
    error: str | None
    script: list | None
    audio_url: str | None
    duration_sec: int | None
    created_at: str

    model_config = {"from_attributes": True}

    @field_validator("created_at", "feed_published_at", mode="before")
    @classmethod
    def fmt_created_at(cls, v) -> str | None:  # noqa: ANN001
        if v is None:
            return None
        from zoneinfo import ZoneInfo

        if hasattr(v, "astimezone"):
            return v.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
        return str(v) or ""


class PodcastCreateOut(BaseModel):
    id: int
    status: str


class PodcastUpdateIn(BaseModel):
    """编辑播客展示信息：全部可选，传了才更新。"""

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    cover_url: str | None = Field(default=None, max_length=500)
