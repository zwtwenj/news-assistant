"""动态标签词表测试：add_new_tags 卫生过滤/上限、rebuild 聚合自愈。自建自清。"""

from datetime import UTC, datetime

import pytest

from app.db.session import SessionLocal
from app.models.article import Article
from app.models.tag_word import TagWord
from app.services.news import vocabulary as vocab_svc


@pytest.fixture
def clean_words():
    """记录测试产生的词并在结束后清除（不动 seed 词）。"""
    before = set(vocab_svc.get_vocabulary())
    yield
    db = SessionLocal()
    db.query(TagWord).filter(~TagWord.word.in_(before)).delete(synchronize_session=False)
    db.commit()
    db.close()
    try:

        from app.core.redis_client import redis_client

        redis_client.delete("news:tag_vocab")
    except Exception:  # noqa: BLE001
        pass


def test_add_new_tags_sanitize(clean_words):
    inputs = ["卫生测试甲", "  卫生测试甲  ", "x", "这是一个超过八个字的超长标签", "卫生测试乙 "]
    accepted = vocab_svc.add_new_tags(inputs)
    # "卫生测试甲"去重收录、"卫生测试乙"strip后5字合法；单字符/超长的被滤掉
    assert sorted(accepted) == ["卫生测试乙", "卫生测试甲"]
    vocab = vocab_svc.get_vocabulary()
    assert "卫生测试甲" in vocab and "卫生测试乙" in vocab


def test_add_new_tags_no_duplicate(clean_words):
    assert vocab_svc.add_new_tags(["测试新增词A"]) == ["测试新增词A"]
    assert vocab_svc.add_new_tags(["测试新增词A"]) == []  # 已在词表，不重复收录


def test_rebuild_from_articles(clean_words):
    """articles.tags 是事实源：造一篇带新标签的文章 → rebuild 后词表包含它。"""
    db = SessionLocal()
    a = Article(
        feed_id=None, url=f"vocab-test-{datetime.now(UTC).timestamp()}", title="词表重建测试",
        source="测试", publish_time=datetime.now(UTC), content="x",
        tags=["自愈测试词"], fetch_status="succeeded", ai_status="succeeded",
        embed_status="pending",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    db.close()

    try:
        vocab_svc.rebuild_vocabulary()
        assert "自愈测试词" in vocab_svc.get_vocabulary()

        # 并集语义不删词，测试词手动清除
        db = SessionLocal()
        db.delete(a)
        db.commit()
        vocab_svc.rebuild_vocabulary()
        db.query(TagWord).filter(TagWord.word == "自愈测试词").delete()
        db.commit()
        db.close()
        try:
            from app.core.redis_client import redis_client

            redis_client.delete("news:tag_vocab")
        except Exception:  # noqa: BLE001
            pass
        assert "自愈测试词" not in vocab_svc.get_vocabulary()
    except Exception:
        # 断言失败也要清掉测试文章（避免残留成"处理中"脏数据）
        db = SessionLocal()
        db.query(Article).filter(Article.id == a.id).delete()
        db.commit()
        db.close()
        raise
