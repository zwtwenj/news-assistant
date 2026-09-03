"""内置主播音色映射（M4 定制音色的基础版）。

voice_id 为 MiniMax 预置音色（demo 实测可用池），展示名自定义。
"""

from typing import Any

# id 即 MiniMax voice_id，直接透传给 t2a_v2
VOICES: list[dict[str, Any]] = [
    {"id": "male-qn-qingse", "name": "燕三（少年男声）", "gender": "male"},
    {"id": "female-shaonv", "name": "秋怡（少年女声）", "gender": "female"},
    {"id": "presenter_male", "name": "闻远（沉稳播报男声）", "gender": "male"},
    {"id": "presenter_female", "name": "婉清（沉稳播报女声）", "gender": "female"},
]


def list_voices() -> list[dict[str, Any]]:
    return VOICES.copy()


def is_valid_voice(voice_id: str) -> bool:
    return any(v["id"] == voice_id for v in VOICES)


def voice_name(voice_id: str) -> str:
    for v in VOICES:
        if v["id"] == voice_id:
            return v["name"]
    return voice_id
