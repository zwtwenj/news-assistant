"""存量回填：全量文章分类 + 灌入 news_articles_v2（hybrid 重构的存量迁移）。

对 ai_status=succeeded 且质检合格的文章：
1. category 为空的跑 classify_article（glm-4-flash，白名单校验）
2. 重建 embed_status=pending 让 embed_articles 任务自然重灌（复用现有管道幂等）
   —— 但 embed 任务只在管道触发时跑，本脚本直接分批调 vector_svc.upsert_articles

用法：cd backend && PYTHONPATH=. ./.venv/Scripts/python.exe scripts/backfill_categories.py
"""

import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.article import Article
from app.services.news import categories as categories_svc
from app.services.news import vector as vector_svc

BATCH = 20
WORKERS = 4


def main() -> None:
    with SessionLocal() as db:
        articles = db.execute(
            select(Article).where(
                Article.deleted_at.is_(None),
                Article.fetch_status == "succeeded",
                Article.ai_status == "succeeded",
            )
        ).scalars().all()
    print(f"待回填 {len(articles)} 篇（分类 + v2 向量库）")

    # ① 分类（无 category 的）
    todo = [a for a in articles if not a.category]
    print(f"其中 {len(todo)} 篇需要 LLM 分类...")
    t0 = time.time()
    done = 0

    def _cls(a: Article) -> tuple[int, dict]:
        return a.id, categories_svc.classify_article(a.title, a.content)

    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for aid, cat in pool.map(_cls, todo):
            results[aid] = cat
            done += 1
            if done % 100 == 0:
                print(f"  分类 {done}/{len(todo)}（{done/(time.time()-t0):.1f} 篇/s）")

    with SessionLocal() as db:
        for a in db.execute(select(Article).where(Article.id.in_(list(results)))).scalars():
            cat = results[a.id]
            a.category = cat["category"]
            a.aux_categories = cat["aux_categories"] or None
        db.commit()
    print(f"分类完成并落库，耗时 {time.time()-t0:.0f}s")

    # ② 向量重灌（v2 集合：dense+BM25+类目）
    t1 = time.time()
    ok = 0
    for i in range(0, len(articles), BATCH):
        chunk = articles[i : i + BATCH]
        rows = [
            {
                "article_id": a.id, "title": a.title, "summary": a.summary or "",
                "content": a.content, "category": a.category or "other",
                "aux_categories": a.aux_categories or [],
                "publish_ts": a.publish_time.timestamp(), "url": a.url, "source": a.source,
            }
            for a in chunk
        ]
        try:
            vector_svc.upsert_articles(rows)
            ok += len(chunk)
        except Exception as exc:  # noqa: BLE001
            print(f"  批次失败 ids={[a.id for a in chunk][:3]}...: {str(exc)[:60]}")
        if (i // BATCH) % 10 == 0:
            print(f"  向量 {ok}/{len(articles)}")
    print(f"回填完成：{ok}/{len(articles)} 篇入 {vector_svc.COLLECTION}，"
          f"耗时 {time.time()-t1:.0f}s")

    with SessionLocal() as db:
        db.execute(
            Article.__table__.update()
            .where(Article.embed_status == "succeeded")
            .values(embed_status="succeeded")
        )
        db.commit()


if __name__ == "__main__":
    main()
