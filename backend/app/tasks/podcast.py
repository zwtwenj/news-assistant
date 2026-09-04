"""播客合成三阶段任务：脚本 → TTS → 拼接（plan-podcast §1）。

状态机：pending → scripting → synthesizing → composing → succeeded / failed
chain 串联（.si()），单 podcast 独立推进，失败 error 落库可单阶段重跑（幂等跳过已完成阶段）。
"""

from pathlib import Path

from celery import Task, chain
from loguru import logger

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.podcast import Podcast
from app.services.podcast import compose as compose_svc
from app.services.podcast import script as script_svc
from app.services.podcast import tts as tts_svc
from app.services.podcast.script import speaker_voice_map
from app.tasks import celery_app
from app.tasks.base import BaseTask

MAX_ATTEMPTS = 3


def _media_root() -> Path:
    return Path(get_settings().media_dir).resolve()


def _fail(db, p: Podcast, error: str) -> None:
    p.status = "failed"
    p.attempts += 1
    p.error = error[:500]
    db.commit()
    logger.warning("podcast {} fail: {}", p.id, error[:120])


@celery_app.task(base=BaseTask, bind=True, name="app.tasks.podcast.gen_script")
def gen_script(self, podcast_id: int) -> str:
    db = SessionLocal()
    try:
        p = db.get(Podcast, podcast_id)
        if p is None or p.status in ("succeeded", "synthesizing", "composing"):
            return f"skip(podcast={podcast_id})"
        p.status = "scripting"
        db.commit()
        try:
            result = script_svc.generate_script(
                p.mode, p.topic_prompt, p.script_prompt, p.script_prompt_a, p.script_prompt_b,
                target_minutes=p.target_minutes,
            )
        except script_svc.ScriptError as exc:
            _fail(db, p, str(exc))  # 业务性失败（如素材不足）不重试
            return f"failed(podcast={podcast_id})"
        except Exception as exc:  # noqa: BLE001
            _fail(db, p, f"脚本生成异常: {exc}")
            return f"failed(podcast={podcast_id})"
        p.script = result["segments"]
        p.materials = result["materials"]  # 本期引用的新闻清单（可追溯）
        p.error = None
        # TTS 关闭模式（调试脚本用）：脚本完成即成功，不做语音合成
        p.status = "succeeded" if not get_settings().podcast_tts_enabled else "synthesizing"
        db.commit()
        return f'script ok({len(result["segments"])}段, 素材{len(result["materials"])}条)'
    finally:
        db.close()


@celery_app.task(base=BaseTask, bind=True, name="app.tasks.podcast.synth_tts")
def synth_tts(self, podcast_id: int) -> str:
    db = SessionLocal()
    try:
        p = db.get(Podcast, podcast_id)
        if p is None or not p.script:
            return f"skip(podcast={podcast_id})"
        if p.status in ("composing", "succeeded"):
            return f"skip(podcast={podcast_id})"
        work_dir = _media_root() / "podcasts" / str(p.id)
        try:
            voice_map = speaker_voice_map(p.voice_a, p.voice_b)
            tts_svc.synth_all(p.script, voice_map, work_dir)
        except Exception as exc:  # noqa: BLE001
            _fail(db, p, f"TTS 合成失败: {exc}")
            return f"failed(podcast={podcast_id})"
        p.status = "composing"
        db.commit()
        return f"tts ok(podcast={podcast_id})"
    finally:
        db.close()


@celery_app.task(  # 编排外层，成功/失败全在任务内消化
    bind=True, name="app.tasks.podcast.compose_audio", base=Task,
)
def compose_audio(self, podcast_id: int) -> str:
    db = SessionLocal()
    try:
        p = db.get(Podcast, podcast_id)
        # 前序阶段已失败（chain 不因返回值中断）：跳过，保留真实失败原因
        if p is None or p.status in ("succeeded", "failed"):
            return f"skip(podcast={podcast_id})"
        work_dir = _media_root() / "podcasts" / str(p.id)
        seg_files = sorted(work_dir.glob("seg_*.wav"))
        if not seg_files:
            _fail(db, p, "分段音频缺失，需从 TTS 阶段重跑")
            return f"failed(podcast={podcast_id})"
        out_path = _media_root() / "podcasts" / f"{p.id}.mp3"
        try:
            info = compose_svc.compose_mp3(seg_files, out_path)
        except Exception as exc:  # noqa: BLE001
            _fail(db, p, f"拼接失败: {exc}")
            return f"failed(podcast={podcast_id})"
        p.audio_url = f"/media/podcasts/{p.id}.mp3"
        p.duration_sec = info["duration_sec"]
        p.size_bytes = info["size_bytes"]
        p.error = None
        p.status = "succeeded"
        db.commit()
        work_dir.rmdir()  # 目录已空（compose 内清理）
        return f"podcast {p.id} succeeded"
    finally:
        db.close()


def dispatch_podcast_pipeline(podcast_id: int) -> None:
    chain(
        gen_script.si(podcast_id),
        synth_tts.si(podcast_id),
        compose_audio.si(podcast_id),
    ).apply_async()
    logger.info("podcast pipeline dispatched id={}", podcast_id)
