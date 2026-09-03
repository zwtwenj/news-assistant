"""ffmpeg 拼接：分段 wav + 段间静音 → 单条 mp3。"""

import subprocess
from pathlib import Path

from loguru import logger

from app.core.config import get_settings

SILENCE_SECONDS = 0.4  # 段间停顿（demo 实测值）
MP3_BITRATE = "128k"


def _ffmpeg_bin() -> str:
    """解析 ffmpeg 可执行文件：显式配置 > imageio-ffmpeg 自带二进制 > PATH。"""
    configured = get_settings().ffmpeg_path
    if configured and configured != "ffmpeg":
        return configured
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001  未安装该包时退回 PATH
        return "ffmpeg"


def _run(args: list[str]) -> str:
    proc = subprocess.run(  # noqa: S603
        [_ffmpeg_bin(), *args], capture_output=True, text=True, timeout=600
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {proc.stderr[-400:]}")
    return proc.stdout


def compose_mp3(seg_files: list[Path], out_path: Path) -> dict:
    """拼接分段（含静音间隔）输出 mp3，返回 {duration_sec, size_bytes}。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_path.parent / "concat.txt"
    lines = []
    for i, seg in enumerate(seg_files):
        if i > 0:  # 段间静音：用 anullsrc 生成等规格静音段
            silence = out_path.parent / f"silence_{i:03d}.wav"
            _run(
                [
                    "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=32000:cl=mono",
                    "-t", str(SILENCE_SECONDS), "-c:a", "pcm_s16le", str(silence),
                ]
            )
            lines.append(f"file '{silence.as_posix()}'")
        lines.append(f"file '{seg.as_posix()}'")
    list_file.write_text("\n".join(lines), encoding="utf-8")

    _run(
        [
            "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-codec:a", "libmp3lame", "-b:a", MP3_BITRATE, str(out_path),
        ]
    )
    # ffprobe 取时长
    duration = _probe_duration(out_path)
    size = out_path.stat().st_size
    # 清理临时文件（分段 + 静音 + concat 列表）
    for f in out_dir_cleanables(out_path.parent):
        f.unlink(missing_ok=True)
    logger.info("compose ok {} duration={}s size={}", out_path.name, duration, size)
    return {"duration_sec": duration, "size_bytes": size}


def _probe_duration(path: Path) -> int:
    proc = subprocess.run(  # noqa: S603
        [_ffmpeg_bin(), "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    # ffmpeg 无 -i 输出时长在 stderr 的 time= 结尾处
    import re

    times = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not times:
        return 0
    h, m, s = times[-1]
    return int(round(int(h) * 3600 + int(m) * 60 + float(s)))


def out_dir_cleanables(directory: Path) -> list[Path]:
    return [p for p in directory.glob("seg_*.wav")] + [
        p for p in directory.glob("silence_*.wav")
    ] + [directory / "concat.txt"]
