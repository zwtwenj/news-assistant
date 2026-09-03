"""RSS 数据源种子脚本（幂等，ON CONFLICT DO NOTHING）。

用法：
  uv run python scripts/seed_feeds.py                # 写入内置默认源
  uv run python scripts/seed_feeds.py URL 名称 [URL 名称 ...]   # 追加自定义源
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import SessionLocal
from app.models.feed import Feed

# 默认源（后续由管理平台 CRUD 维护，M2）
DEFAULT_FEEDS = [
    ("https://hub.slarker.me/cctv/ent", "央视网-娱乐"),
]


def seed(feeds: list[tuple[str, str]]) -> None:
    db = SessionLocal()
    try:
        for url, name in feeds:
            stmt = (
                pg_insert(Feed)
                .values(url=url, name=name)
                .on_conflict_do_nothing(index_elements=["url"])
            )
            db.execute(stmt)
        db.commit()
        total = db.query(Feed).count()
        logger.info("种子完成：当前共 {} 个数据源", total)
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1:]:
        pairs: list[tuple[str, str]] = []
        args = sys.argv[1:]
        if len(args) % 2 != 0:
            print("自定义源需要成对传入：URL 名称")
            sys.exit(1)
        for i in range(0, len(args), 2):
            pairs.append((args[i], args[i + 1]))
        seed(pairs)
    else:
        seed(DEFAULT_FEEDS)


if __name__ == "__main__":
    main()
