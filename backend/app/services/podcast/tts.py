"""MiniMax TTS 分段合成（参数沿用 demo 实测：speech-02-turbo / t2a_v2 / hex wav）。"""

from pathlib import Path

import httpx
from loguru import logger

from app.core.config import get_settings

TTS_PATH = "/v1/t2a_v2"
MODEL = "speech-02-turbo"
MAX_TEXT_CHARS = 8000  # t2a_v2 单次上限内留余量（demo 经验）
TIMEOUT = 300


def _host() -> str:
    return get_settings().minimax_base_url.rstrip("/").removesuffix("/v1")


def synth_segment(text: str, voice_id: str) -> bytes:
    """单段合成，返回 WAV 字节。失败抛异常（任务层计 attempts）。"""
    s = get_settings()
    resp = httpx.post(
        _host() + TTS_PATH,
        headers={
            "Authorization": f"Bearer {s.minimax_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "text": text[:MAX_TEXT_CHARS],
            "stream": False,
            "voice_setting": {"voice_id": voice_id, "speed": 1, "vol": 1, "pitch": 0},
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "wav",
                "channel": 1,
            },
        },
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"t2a HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    base = data.get("base_resp", {})
    if base.get("status_code") not in (0, None):
        raise RuntimeError(f"t2a 业务失败: {base.get('status_msg')}")
    audio_hex = (data.get("data") or {}).get("audio", "")
    if not audio_hex:
        raise RuntimeError("响应无音频数据")
    wav = bytes.fromhex(audio_hex)
    if len(wav) < 200:
        raise RuntimeError(f"音频过短({len(wav)}B)")
    return wav


def synth_all(segments: list[dict], voice_map: dict[str, str], out_dir: Path) -> list[Path]:
    """逐段合成到 out_dir/seg_XXX.wav，返回文件列表（顺序）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for i, seg in enumerate(segments, 1):
        voice = voice_map.get(seg.get("speaker", "single"), voice_map["single"])
        wav = synth_segment(seg["text"], voice)
        path = out_dir / f"seg_{i:03d}.wav"
        path.write_bytes(wav)
        files.append(path)
        logger.info("tts seg {}/{} ok voice={} bytes={}", i, len(segments), voice, len(wav))
    return files
