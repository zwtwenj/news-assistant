"""重打新闻标签（动态词表实测/校准工具）：取最新 N 篇重新打标，统计词表生长。

用法：
    uv run python scripts/retag_articles.py --limit 50 [--no-vector]

- 只处理未软删且 ai_status=succeeded 的文章（打标失败的重试走每日流水线补偿）
- 新标签写入词表（add_new_tags，与流水线同一自生长链路）
- 已向量化文章重打后同步刷新 Milvus 的 tags/summary 字段（--no-vector 关闭）
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from loguru import logger
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal
from app.models.article import Article
from app.services.news import analyzer as analyzer_svc
from app.services.news import vocabulary as vocab_svc
from app.services.news import vector as vector_svc


def main(limit: int, refresh_vector: bool) -> None:
    before = set(vocab_svc.get_vocabulary())
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Article)
            .where(Article.deleted_at.is_(None), Article.ai_status == "succeeded")
            .order_by(Article.id.desc())
            .limit(limit)
        ).scalars().all()
        logger.info("待重打 {} 篇；词表当前 {} 词", len(rows), len(before))

        ok = fail = changed = 0
        grown_words: list[str] = []
        tag_counter: Counter = Counter()
        upsert_rows: list[dict] = []
        for i, a in enumerate(rows, 1):
            result = analyzer_svc.analyze(a.title, a.content or "")
            if result is None:
                fail += 1
                logger.warning("[{}/{}] 打标失败: {}", i, len(rows), a.title[:30])
                continue
            ok += 1
            old_tags = set(a.tags or [])
            a.tags = result["tags"]
            a.summary = result["summary"]
            if set(a.tags) != old_tags:
                changed += 1
                logger.info(
                    "[{}/{}] {}：{} → {}",
                    i, len(rows), a.title[:24],
                    sorted(old_tags), sorted(set(a.tags)),
                )
            grown = vocab_svc.add_new_tags(result.get("new_tags", []))
            grown_words.extend(grown)
            tag_counter.update(a.tags)
            if refresh_vector and a.embed_status == "succeeded":
                # tags/summary 变了要重刷向量库（embedding 重算，50 篇成本可忽略）
                upsert_rows.append(
                    {
                        "article_id": a.id,
                        "title": a.title,
                        "summary": a.summary or "",
                        "content": a.content or "",
                        "tags": a.tags or [],
                        "publish_ts": int(a.publish_time.timestamp()),
                        "url": a.url,
                    }
                )
            db.commit()
            time.sleep(0.3)  # LLM 节流

        if refresh_vector and upsert_rows:
            n = vector_svc.upsert_articles(upsert_rows)
            logger.info("Milvus 向量已刷新 {} 条", n)

        grew = sorted(set(grown_words))
        logger.info("=" * 60)
        logger.info("完成：成功 {} / 失败 {} / 标签变化 {} 篇", ok, fail, changed)
        logger.info("词表生长：{} → {} 词，新生长 {} 个：{}", len(before), len(vocab_svc.get_vocabulary()), len(grew), grew)
        logger.info("重打后标签分布 Top15：{}", tag_counter.most_common(15))
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重打新闻标签（动态词表实测）")
    parser.add_argument("--limit", type=int, default=50, help="取最新 N 篇")
    parser.add_argument("--no-vector", action="store_true", help="不刷新 Milvus 向量")
    args = parser.parse_args()
    main(args.limit, refresh_vector=not args.no_vector)
