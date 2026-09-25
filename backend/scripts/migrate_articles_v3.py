"""articles → articles_v3 幂等数据迁移（并行迁移第一步）。

全量拷贝（含软删行与各状态行，保持 id 不变），分类值随行携带；
对已存在的 id 跳过（幂等，可重复跑补增量）。序列推进到 max(id)。

用法：cd backend && PYTHONPATH=. ./.venv/Scripts/python.exe scripts/migrate_articles_v3.py
"""

import time

from sqlalchemy import text

from app.db.session import SessionLocal

COLS = (
    "id, feed_id, url, title, source, publish_time, content, content_hash, "
    "summary, tags, category, aux_categories, fetch_status, fetch_attempts, "
    "fetch_error, ai_status, ai_attempts, ai_error, embed_status, "
    "embed_attempts, embed_error, deleted_at, created_at, updated_at, "
    "content_quality"
)


def main() -> None:
    t0 = time.time()
    with SessionLocal() as db:
        src = db.execute(text("SELECT COUNT(*) FROM articles")).scalar()
        dst = db.execute(text("SELECT COUNT(*) FROM articles_v3")).scalar()
        print(f"源表 articles={src} 行，目标 articles_v3={dst} 行")
        # 幂等：只补新 id（ON CONFLICT 跳过）
        result = db.execute(text(f"""
            INSERT INTO articles_v3 ({COLS})
            SELECT {COLS} FROM articles a
            WHERE NOT EXISTS (SELECT 1 FROM articles_v3 v WHERE v.id = a.id)
        """))
        moved = result.rowcount
        # 序列推进（新管道写入 id 续接）
        db.execute(text(
            "SELECT setval(pg_get_serial_sequence('articles_v3', 'id'), "
            "(SELECT COALESCE(MAX(id), 1) FROM articles_v3))"))
        db.commit()
        dst2 = db.execute(text("SELECT COUNT(*) FROM articles_v3")).scalar()
        cat = db.execute(text(
            "SELECT COUNT(*) FROM articles_v3 "
            "WHERE deleted_at IS NULL AND fetch_status='succeeded' AND category IS NOT NULL"
        )).scalar()
    print(f"本次新增 {moved} 行，目标表现在 {dst2} 行，分类覆盖(合格口径) {cat} 行，"
          f"耗时 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
