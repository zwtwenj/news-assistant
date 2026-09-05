"""MiniMax 声音复刻管理脚本（上传 → 复刻 → 正式合成激活）。

复刻规则（详见 platform 文档）：
- 录音要求：mp3/m4a/wav，时长 10 秒~5 分钟，≤20MB，安静环境单一说话人
- voice_id 自定义：8-256 字符，字母开头，仅字母数字 -_，不以 -_ 结尾
- ⚠️ 7 天规则：复刻出的音色 7 天内未正式调 T2A 会被系统删除（复刻接口内
  试听不算激活），因此脚本最后一步固定用 t2a_v2 正式合成一句并落地 wav。
- 前提：MiniMax 账号已个人/企业实名认证，否则 2038 无复刻权限。

用法：
  uv run python scripts/clone_voice.py <音频路径> [--voice-id news-host-xxx]   # 复刻+激活
  uv run python scripts/clone_voice.py --list                                  # 查已复刻音色
"""

import argparse
import sys
from pathlib import Path

import httpx
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.services.podcast.tts import _host, synth_segment

UPLOAD_PATH = "/v1/files/upload"
CLONE_PATH = "/v1/voice_clone"
GET_VOICE_PATH = "/v1/get_voice"
TIMEOUT = 180
ALLOWED_EXT = {".mp3", ".m4a", ".wav"}
MAX_BYTES = 20 * 1024 * 1024

# 激活用的正式合成文本（也是音色效果验收样本）
ACTIVATE_TEXT = "大家好，欢迎收听本台新闻节目，我们一起来关注今天的重点资讯。"


def _headers_json() -> dict[str, str]:
    s = get_settings()
    return {
        "Authorization": f"Bearer {s.minimax_api_key}",
        "Content-Type": "application/json",
    }


def _check_base(resp: httpx.Response, step: str) -> dict:
    """统一校验 HTTP 状态 + base_resp 业务码，失败抛异常并打印文档错误码提示。"""
    if resp.status_code != 200:
        raise RuntimeError(f"{step} HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    base = data.get("base_resp", {})
    code = base.get("status_code")
    if code not in (0, None):
        hints = {
            2038: "账号未实名认证，无复刻权限",
            1004: "API Key 无效",
            1008: "账户余额不足",
            1043: "录音与预期文本相似度过低（text_validation 校验失败）",
            2013: "输入参数无效（检查音频时长 10s~5min / voice_id 命名规则）",
        }
        hint = hints.get(code, "")
        raise RuntimeError(f"{step} 业务失败 code={code} msg={base.get('status_msg')} {hint}")
    return data


def upload_audio(audio: Path) -> int:
    """上传录音（purpose=voice_clone），返回 file_id。"""
    if audio.suffix.lower() not in ALLOWED_EXT:
        raise ValueError(f"音频格式仅支持 {ALLOWED_EXT}，当前 {audio.suffix}")
    if audio.stat().st_size > MAX_BYTES:
        raise ValueError(f"文件超过 20MB：{audio.stat().st_size}")
    s = get_settings()
    with audio.open("rb") as f:
        resp = httpx.post(
            _host() + UPLOAD_PATH,
            headers={"Authorization": f"Bearer {s.minimax_api_key}"},
            data={"purpose": "voice_clone"},
            files={"file": (audio.name, f, "application/octet-stream")},
            timeout=TIMEOUT,
        )
    data = _check_base(resp, "上传")
    file_id = int(data["file"]["file_id"])
    logger.info("上传成功 file_id={} bytes={}", file_id, data["file"].get("bytes"))
    return file_id


def clone(file_id: int, voice_id: str) -> None:
    """创建复刻音色。不开试听（text/model），激活由正式 t2a_v2 合成完成。"""
    resp = httpx.post(
        _host() + CLONE_PATH,
        headers=_headers_json(),
        json={
            "file_id": file_id,
            "voice_id": voice_id,
            "need_noise_reduction": True,  # 录音底噪兜底
        },
        timeout=TIMEOUT,
    )
    _check_base(resp, "复刻")
    logger.info("复刻成功 voice_id={}", voice_id)


def activate(voice_id: str, out_dir: Path) -> Path:
    """正式调 t2a_v2 合成一句，完成 7 天规则要求的激活，并保存验收样本。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = synth_segment(ACTIVATE_TEXT, voice_id)  # 失败抛异常，含业务码
    path = out_dir / f"activate_{voice_id}.wav"
    path.write_bytes(wav)
    logger.info("激活合成成功 {} bytes → {}", len(wav), path)
    return path


def list_cloned() -> None:
    """列出账号下已复刻音色（需至少正式使用过一次才可见）。"""
    resp = httpx.post(
        _host() + GET_VOICE_PATH,
        headers=_headers_json(),
        json={"voice_type": "voice_cloning"},
        timeout=TIMEOUT,
    )
    data = _check_base(resp, "查询音色")
    voices = data.get("voice_cloning") or []
    if not voices:
        logger.info("无已复刻音色（注意：复刻后需正式使用一次才可查询到）")
        return
    for v in voices:
        logger.info("voice_id={} created={}", v.get("voice_id"), v.get("created_time"))


def main() -> None:
    ap = argparse.ArgumentParser(description="MiniMax 声音复刻")
    ap.add_argument("audio", nargs="?", help="录音文件路径（mp3/m4a/wav）")
    ap.add_argument(
        "--voice-id", default="news-host-clone01", help="自定义 voice_id（8-256 字符，字母开头）"
    )
    ap.add_argument("--list", action="store_true", help="仅列出已复刻音色")
    args = ap.parse_args()

    if args.list:
        list_cloned()
        return
    if not args.audio:
        ap.error("必须提供音频路径，或使用 --list")

    vid = args.voice_id
    if not (8 <= len(vid) <= 256 and vid[0].isalpha() and vid[-1] not in "-_"):
        ap.error("voice_id 需 8-256 字符、字母开头、不以 -_ 结尾")

    audio = Path(args.audio).resolve()
    file_id = upload_audio(audio)
    clone(file_id, vid)
    sample = activate(vid, Path("media/voice_samples"))
    logger.info("完成 ✅ 下一步：把 {{\"id\": \"{}\", ...}} 加入 voices.py 的 VOICES", vid)
    logger.info("激活样本（人工听验相似度）：{}", sample)


if __name__ == "__main__":
    main()
