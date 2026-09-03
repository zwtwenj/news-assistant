
from pydantic import BaseModel, field_validator, model_validator

TOPIC_MAX = 500
PROMPT_MAX = 2000


class VoiceOut(BaseModel):
    id: str  # MiniMax voice_id
    name: str  # 展示名，如"燕三（少年男声）"
    gender: str


class PodcastCreate(BaseModel):
    mode: str  # single / dual
    topic_prompt: str
    voice_a: str
    voice_b: str | None = None
    script_prompt: str | None = None
    script_prompt_a: str | None = None
    script_prompt_b: str | None = None

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
        if self.mode == "single":
            if not (self.script_prompt and self.script_prompt.strip()):
                raise ValueError("单人模式需要脚本提示词（风格设定）")
        else:
            if not (self.script_prompt_a and self.script_prompt_a.strip()):
                raise ValueError("双人模式需要 A 的脚本提示词（人设）")
            if not (self.script_prompt_b and self.script_prompt_b.strip()):
                raise ValueError("双人模式需要 B 的脚本提示词（人设）")
            if not self.voice_b:
                raise ValueError("双人模式需要选择 B 的音色")
            if self.voice_b == self.voice_a:
                raise ValueError("双人模式两个音色不能相同")
        for f in ("script_prompt", "script_prompt_a", "script_prompt_b"):
            v = getattr(self, f)
            if v and len(v) > PROMPT_MAX:
                raise ValueError(f"{f} 超过 {PROMPT_MAX} 字上限")
            if v is not None:
                setattr(self, f, v.strip())
        return self


class PodcastOut(BaseModel):
    id: int
    mode: str
    status: str
    topic_prompt: str
    voice_a: str
    voice_b: str | None
    error: str | None
    script: list | None
    audio_url: str | None
    duration_sec: int | None
    created_at: str

    model_config = {"from_attributes": True}

    @field_validator("created_at", mode="before")
    @classmethod
    def fmt_created_at(cls, v) -> str:  # noqa: ANN001
        from zoneinfo import ZoneInfo

        if hasattr(v, "astimezone"):
            return v.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
        return str(v)


class PodcastCreateOut(BaseModel):
    id: int
    status: str
