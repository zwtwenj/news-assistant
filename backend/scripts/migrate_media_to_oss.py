"""存量播客音频迁移 OSS（本地 mp3 → 上传 → 回填 audio_url → 清理本地）。

- 幂等：audio_url 已是 https 的跳过；OSS 已有同名对象跳过上传
- 安全：默认 dry-run 只打印计划，--apply 才实际执行
- 每条独立提交：单条失败不中断整批

用法：
  uv run python scripts/migrate_media_to_oss.py           # dry-run
  uv run python scripts/migrate_media_to_oss.py --apply   # 执行迁移
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.podcast import Podcast
from app.services.storage import oss as oss_svc


def main() -> None:
    ap = argparse.ArgumentParser(description="存量播客音频迁移 OSS")
    ap.add_argument("--apply", action="store_true", help="实际执行（默认 dry-run）")
    args = ap.parse_args()

    if not oss_svc.enabled():
        logger.error("OSS 未配置（OSS_ACCESS_KEY_ID/OSS_SECRET 为空），退出")
        sys.exit(1)

    settings = get_settings()
    podcasts_dir = Path(settings.media_dir).resolve() / "podcasts"
    db = SessionLocal()
    migrated = skipped = failed = 0
    try:
        for mp3 in sorted(podcasts_dir.glob("*.mp3")):
            pid = int(mp3.stem)
            p = db.get(Podcast, pid)
            if p is None:
                logger.warning("跳过 {}：库中无记录", mp3.name)
                skipped += 1
                continue
            if p.audio_url and p.audio_url.startswith("https://"):
                logger.info("跳过 podcast {}：已是 OSS 地址", pid)
                skipped += 1
                continue
            key = f"{settings.oss_prefix}/{pid}.mp3"
            mode = "APPLY" if args.apply else "DRY"
            if not args.apply:
                logger.info("[{}] podcast {} -> {} ({}B)", mode, pid, key, mp3.stat().st_size)
                migrated += 1
                continue
            # 幂等：OSS 已有对象则只回填 URL 不重复上传
            url = (
                oss_svc.public_url(key)
                if oss_svc.object_exists(key)
                else oss_svc.upload_file(mp3, key)
            )
            if url is None:
                logger.error("podcast {} 上传失败，保留本地", pid)
                failed += 1
                continue
            p.audio_url = url
            db.commit()
            mp3.unlink(missing_ok=True)
            seg_dir = podcasts_dir / str(pid)
            if seg_dir.is_dir():
                for f in seg_dir.iterdir():
                    f.unlink(missing_ok=True)
                seg_dir.rmdir()
            migrated += 1
            logger.info("podcast {} 迁移完成 -> {}", pid, url)
    finally:
        db.close()
    mode = "apply" if args.apply else "dry-run"
    logger.info("结束：迁移 {} 跳过 {} 失败 {}（mode={}）", migrated, skipped, failed, mode)


if __name__ == "__main__":
    main()
