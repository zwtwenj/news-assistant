"""新闻流水线：四阶段任务 + 每日编排（plan-news-pipeline）。

阶段状态机（models/article.py）：fetch(抓正文) → ai(打标) → embed(向量化)，
各自独立状态/attempts/error，单篇失败不阻断整批，重跑幂等（只扫 pending）。

Langfuse（plan §8）：阶段任务 @observe 建 trace（session=pipeline-{date}）；
每篇打标在 span 下进行，规则分全量 + judge 采样 20% 打 score。
"""

import random
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from celery import Task, chain
from langfuse import observe
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.redis_client import redis_client
from app.db.session import SessionLocal
from app.models.article import (
    FAILED,
    MAX_ATTEMPTS,
    PENDING,
    SKIPPED,
    SUCCEEDED,
    Article,
)
from app.models.feed import Feed
from app.services.alert import send_alert
from app.services.news import analyzer as analyzer_svc
from app.services.news import extractor as extractor_svc
from app.services.news import quality as quality_svc
from app.services.news import rss as rss_svc
from app.services.news import semantic_check as semantic_svc
from app.services.news import simhash as simhash_svc
from app.services.news import vector as vector_svc
from app.services.news import vocabulary as vocabulary_svc
from app.services.observability.langfuse_client import get_langfuse, init_langfuse
from app.services.observability.langfuse_client import score as lf_score
from app.tasks import celery_app
from app.tasks.base import BaseTask

init_langfuse()  # worker 进程加载本模块时初始化观测（未配置则 no-op）

SCRAPE_TIMEOUT = 20
SIMHASH_LOOKBACK = timedelta(days=7)
LLM_CONSECUTIVE_FAIL_LIMIT = 5  # 连续失败熔断：防 API 整体故障时空转烧钱


def _session_id() -> str:
    return f"pipeline-{datetime.now(UTC):%Y%m%d}"


def _record_scores(trace_id: str | None, scores: dict[str, float], *, comment: str = "") -> None:
    """分数挂到网关 generation 的 trace 上（no-op 安全）。"""
    if trace_id:
        for name, value in scores.items():
            lf_score(trace_id, name, value, comment=comment)


def _finish_trace(**meta) -> None:
    """任务结束前把统计汇总进当前根 span（no-op 安全）。"""
    lf = get_langfuse()
    if lf is None:
        return
    try:
        lf.update_current_span(metadata=meta)
    except Exception:
        logger.opt(exception=True).debug("update span fail（不影响业务）")


def _reset_compensable_failed(db: Session) -> int:
    """失败补偿：可补偿的 failed（attempts<3）重置为 pending，保留 attempts 计数。"""
    total = 0
    for status_col, attempts_col in (
        (Article.fetch_status, Article.fetch_attempts),
        (Article.ai_status, Article.ai_attempts),
        (Article.embed_status, Article.embed_attempts),
    ):
        result = db.execute(
            Article.__table__.update()
            .where(
                Article.deleted_at.is_(None),
                status_col == FAILED,
                attempts_col < MAX_ATTEMPTS,
            )
            .values({status_col.key: PENDING})
        )
        total += result.rowcount or 0
    db.commit()
    return total


# ---------- 阶段 1：RSS 发现与入库 ----------

@celery_app.task(base=BaseTask, bind=True, name="app.tasks.news.fetch_feeds")
@observe()
def fetch_feeds(self) -> str:
    db = SessionLocal()
    added = skipped = 0
    try:
        feeds = db.query(Feed).filter(Feed.enabled.is_(True), Feed.deleted_at.is_(None)).all()
        feed_stats = {}
        for feed in feeds:
            try:
                entries = rss_svc.fetch_feed(feed.url, source_name=feed.name)
            except Exception:
                logger.opt(exception=True).warning("rss fail feed={}", feed.url)
                feed_stats[feed.name] = "error"
                continue
            feed.last_fetched_at = datetime.now(UTC)
            seen: set[str] = set()
            for e in entries:
                if e["url"] in seen:
                    continue
                seen.add(e["url"])
                exists = db.query(Article.id).filter(Article.url == e["url"]).first()
                if exists:
                    skipped += 1
                    continue
                db.add(
                    Article(
                        feed_id=feed.id,
                        url=e["url"],
                        title=e["title"][:500],
                        source=(e["source"] or feed.name)[:200],
                        publish_time=e["publish_time"],
                        content=e["summary"][:5000],  # RSS summary 兜底，scrape 后覆盖
                        fetch_status=PENDING,
                    )
                )
                added += 1
            feed_stats[feed.name] = len(entries)
            db.commit()
        logger.info("fetch_feeds 完成：新增 {} 篇（已存在跳过 {}）", added, skipped)

        # 飞书统计告警：每次拉取结束汇报详情（新增/跳过/失效源清单）
        failed_feeds = [name for name, st in feed_stats.items() if st == "error"]
        ok_count = len(feed_stats) - len(failed_feeds)
        alert_lines = [
            f"新增 {added} 篇 ｜ 跳过(已存在) {skipped} 篇"
            f" ｜ 成功源 {ok_count} 个 ｜ 失效源 {len(failed_feeds)} 个",
        ]
        if failed_feeds:
            alert_lines.append(f"失效源：{'、'.join(failed_feeds)}（本次未拉取）")
        if added == 0:
            alert_lines.append("⚠ 今日新增 0 篇，请检查源可用性或手动触发补拉。")
        send_alert("RSS 拉取报告", "\n".join(alert_lines))

        _finish_trace(stage="fetch", added=added, url_duplicated=skipped, feeds=feed_stats)
        return f"新增 {added} 篇"
    finally:
        db.close()


# ---------- 阶段 2：正文抓取 + SimHash 去重 ----------

@celery_app.task(base=BaseTask, bind=True, name="app.tasks.news.scrape_articles")
@observe()
def scrape_articles(self) -> str:
    db = SessionLocal()
    ok = dup = fail = 0
    web = rss = 0
    try:
        articles = db.query(Article).filter(
            Article.deleted_at.is_(None),
            Article.fetch_status.in_([PENDING, FAILED]),
            Article.fetch_attempts < MAX_ATTEMPTS,
        ).all()

        # 近 7 天已入库的 simhash 集合（内存比对，量级：天级百篇 × 7 天，位运算微秒级）
        recent_hashes: list[int] = [
            simhash_svc.from_hex(h)
            for (h,) in db.execute(
                select(Article.content_hash).where(
                    Article.deleted_at.is_(None),
                    Article.content_hash.is_not(None),
                    Article.publish_time >= datetime.now(UTC) - SIMHASH_LOOKBACK,
                )
            )
        ]

        for a in articles:
            try:
                resp = httpx.get(
                    a.url,
                    headers={"User-Agent": random.choice(rss_svc.UA_POOL)},
                    timeout=SCRAPE_TIMEOUT,
                    follow_redirects=True,
                )
                resp.raise_for_status()
                content, method = extractor_svc.extract(resp.text, a.content)
                if method == "failed":
                    # 三级降级链全部失败（正文抽不到）：计失败，不入库垃圾文本
                    raise ValueError(f"正文抽取失败（三级降级均不可用，最长 {len(content)} 字）")
                # 质量门禁②（规则质检，微秒级）：确定性垃圾特征 → 隔离不入库
                verdict, q_reasons = quality_svc.check_content(a.title, content)
                if verdict == "bad":
                    raise ValueError(f"规则质检不合格: {'; '.join(q_reasons)}")
                h = simhash_svc.simhash(content)
                is_dup = any(simhash_svc.is_similar(h, rh) for rh in recent_hashes)
                a.content = content
                a.content_hash = simhash_svc.to_hex(h)
                a.content_quality = verdict  # good / suspect（suspect 交语义检测复核）
                if method in ("web", "p_tags"):
                    web += 1
                else:
                    rss += 1
                if is_dup:
                    a.fetch_status = SKIPPED
                    a.fetch_error = "内容与近7天已有文章重复（simhash）"
                    dup += 1
                else:
                    a.fetch_status = SUCCEEDED
                    a.fetch_error = None
                    recent_hashes.append(h)
                    ok += 1
            except Exception as exc:  # noqa: BLE001  单篇失败：计 attempts、不阻断
                a.fetch_attempts += 1
                a.fetch_status = FAILED
                a.fetch_error = f"{exc.__class__.__name__}: {exc}"[:500]
                fail += 1
                logger.warning("scrape fail id={} err={}", a.id, a.fetch_error)
            db.commit()
            time.sleep(random.uniform(0.5, 1.5))  # 对源友好
        logger.info("scrape 完成：成功 {} 重复 {} 失败 {}", ok, dup, fail)
        _finish_trace(
            stage="scrape", succeeded=ok, simhash_duplicated=dup, failed=fail,
            extract_web=web, extract_rss_fallback=rss,
        )
        return f"抓取成功{ok}/重复{dup}/失败{fail}"
    finally:
        db.close()


# ---------- 阶段 3：LLM 打标与摘要 ----------

@celery_app.task(base=BaseTask, bind=True, name="app.tasks.news.analyze_articles")
@observe()
def analyze_articles(self) -> str:
    db = SessionLocal()
    ok = fail = judged = skipped = 0
    try:
        articles = db.query(Article).filter(
            Article.deleted_at.is_(None),
            Article.fetch_status == SUCCEEDED,
            Article.ai_status.in_([PENDING, FAILED]),
            Article.ai_attempts < MAX_ATTEMPTS,
        ).all()
        consecutive_fail = 0
        for a in articles:
            # 质量门禁③（语义检测，glm-4-flash 前置独立调用）：
            # 规则测不出的"字通顺但非正文"在此拦截；bad 短路不进打标（省输出 token）
            semantic = semantic_svc.check_semantic(a.title, a.content)
            if semantic == "bad":
                a.content_quality = "bad"
                a.ai_status = SKIPPED
                a.ai_error = "语义检测：非完整可读的新闻正文"
                skipped += 1
                db.commit()
                continue
            meta: dict[str, Any] = {
                "article_id": a.id,
                "pipeline": _session_id(),
                "title": a.title,
                "source": a.source,
            }
            result = analyzer_svc.analyze(a.title, a.content, langfuse_meta=meta)
            trace_id = meta.get("_trace_id")
            if result is not None:
                a.summary = result["summary"]
                a.tags = result["tags"]
                a.ai_status = SUCCEEDED
                a.ai_error = None
                ok += 1
                consecutive_fail = 0
                # 新标签写入词表（自生长：Redis 即时可见，下一篇打标即复用）
                new_words = vocabulary_svc.add_new_tags(result.get("new_tags", []))
                if new_words:
                    logger.info("tag vocabulary grown: {}", new_words)
                # 规则分（全量、零成本）+ judge（采样，glm-4-flash）
                scores: dict[str, float] = {"schema_compliance": 1.0}
                scores.update(analyzer_svc.rule_scores(result["summary"], a.content))
                if analyzer_svc.should_judge():
                    verdict = analyzer_svc.judge(
                        a.title, a.content, result["summary"], result["tags"]
                    )
                    if verdict:
                        judged += 1
                        scores["faithfulness"] = float(verdict["faithfulness"])
                        scores["tag_accuracy"] = float(verdict["tag_accuracy"])
                _record_scores(trace_id, scores)
            else:
                a.ai_attempts += 1
                a.ai_status = FAILED
                a.ai_error = "LLM 打标失败（输出非法或网关不可用）"
                fail += 1
                consecutive_fail += 1
                _record_scores(trace_id, {"schema_compliance": 0.0})
            db.commit()
            if consecutive_fail >= LLM_CONSECUTIVE_FAIL_LIMIT:
                logger.error("连续 {} 篇打标失败，疑似 LLM 服务故障，熔断退出", consecutive_fail)
                break
            time.sleep(random.uniform(0.2, 0.5))  # LLM 节流
        logger.info(
            "analyze 完成：成功 {} 失败 {} 语义拦截 {} judge采样 {}", ok, fail, skipped, judged
        )
        _finish_trace(
            stage="analyze", succeeded=ok, failed=fail,
            semantic_blocked=skipped, judged=judged,
        )
        return f"打标成功{ok}/失败{fail}/语义拦截{skipped}"
    finally:
        db.close()


# ---------- 阶段 4：向量化入库 ----------

@celery_app.task(base=BaseTask, bind=True, name="app.tasks.news.embed_articles")
@observe()
def embed_articles(self) -> str:
    db = SessionLocal()
    ok = fail = 0
    try:
        articles = db.query(Article).filter(
            Article.deleted_at.is_(None),
            Article.ai_status == SUCCEEDED,
            Article.embed_status.in_([PENDING, FAILED]),
            Article.embed_attempts < MAX_ATTEMPTS,
            # 质量门禁④：bad 内容永不向量化（null=未检视为放行，兼容存量）
            or_(Article.content_quality.is_(None), Article.content_quality != "bad"),
        ).all()
        batch: list[Article] = []
        for a in articles:
            batch.append(a)
            if len(batch) < vector_svc.EMBED_BATCH:
                continue
            ok += _upsert_batch(db, batch)
            batch = []
        if batch:
            ok += _upsert_batch(db, batch)
        fail = len(articles) - ok
        logger.info("embed 完成：成功 {} 失败 {}", ok, fail)
        _finish_trace(stage="embed", succeeded=ok, failed=fail)
        return f"向量化成功{ok}/失败{fail}"
    finally:
        db.close()


def _upsert_batch(db: Session, batch: list[Article]) -> int:
    rows = [
        {
            "article_id": a.id,
            "title": a.title,
            "summary": a.summary or "",
            "content": a.content,
            "tags": a.tags or [],
            "publish_ts": a.publish_time.timestamp(),
            "url": a.url,
        }
        for a in batch
    ]
    try:
        vector_svc.upsert_articles(rows)
        for a in batch:
            a.embed_status = SUCCEEDED
            a.embed_error = None
        db.commit()
        return len(batch)
    except Exception as exc:  # noqa: BLE001
        logger.opt(exception=True).warning("embed batch fail ids={}", [a.id for a in batch])
        db.rollback()
        for a in batch:
            a.embed_attempts += 1
            a.embed_status = FAILED
            a.embed_error = f"{exc.__class__.__name__}: {exc}"[:500]
        db.commit()
        return 0


# ---------- 向量对账（质量门禁第④层，每日 pipeline 末尾） ----------

@celery_app.task(  # 对账失败不影响主链结果，人工可随时重跑
    bind=True, name="app.tasks.news.reconcile_vectors", base=Task,
)
def reconcile_vectors(self) -> str:
    """比对 PG 可用集合与 Milvus 集合，自动删除孤儿向量（bad/判重/软删的残留）。"""
    from pymilvus import MilvusClient

    from app.core.config import get_settings

    db = SessionLocal()
    try:
        pg_ok = {
            row.id
            for row in db.execute(
                select(Article.id).where(
                    Article.deleted_at.is_(None),
                    Article.embed_status == SUCCEEDED,
                    or_(
                        Article.content_quality.is_(None),
                        Article.content_quality != "bad",
                    ),
                )
            )
        }
    finally:
        db.close()
    s = get_settings()
    client = MilvusClient(uri=s.milvus_uri, token=s.milvus_token)
    mv_ids = {
        r["article_id"]
        for r in client.query(
            collection_name=vector_svc.COLLECTION,
            filter="article_id >= 0",
            output_fields=["article_id"],
            limit=1000,
        )
    }
    orphans = sorted(mv_ids - pg_ok)
    if orphans:
        client.delete(
            collection_name=vector_svc.COLLECTION, filter=f"article_id in {orphans}"
        )
        logger.warning("向量对账：删除孤儿 {} 条: {}", len(orphans), orphans[:20])
    else:
        logger.info("向量对账：一致（{} 条）", len(mv_ids))
    return f"对账完成，清理孤儿 {len(orphans)} 条"


# ---------- 每日编排 ----------

PIPELINE_RUNNING_TTL = 3 * 3600  # 并发闸：覆盖最长时长；链中断后自动过期，当日可补跑
PIPELINE_DONE_TTL = 172800  # 成功标记：48h，覆盖次日补跑窗口


@celery_app.task(  # 不用 BaseTask：编排任务失败重试会重复 dispatch，防重入锁兜底 + 人工介入
    bind=True, name="app.tasks.news.run_daily_pipeline", base=Task,
)
@observe()
def run_daily_pipeline(self) -> str:
    # 北京日期，须与 beat 调度时区一致（UTC 计日会把 02:00 调度误判为前一天已执行）
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    done_key = f"pipeline:done:{today}"
    running_key = f"pipeline:running:{today}"
    # 双 key：done=成功标记（一天只成功跑一次）；running=并发闸（短 TTL）。
    # 链中断（worker 崩溃/被杀）时链尾 mark_pipeline_done 不会执行 → done 不落 →
    # running 过期后当日可补跑；阶段业务性失败（如 LLM 挂）链仍走完 → done 落 →
    # 次日 _reset_compensable_failed 自动补偿重试。
    if redis_client.get(done_key):
        logger.info("pipeline 今日已成功（done={}），跳过", done_key)
        return "今日已成功，跳过"
    if not redis_client.set(running_key, "1", nx=True, ex=PIPELINE_RUNNING_TTL):
        logger.info("pipeline 正在执行中（running={}），跳过", running_key)
        return "执行中，跳过"

    db = SessionLocal()
    try:
        compensated = _reset_compensable_failed(db)
    finally:
        db.close()
    if compensated:
        logger.info("失败补偿：重置 {} 个阶段状态为 pending", compensated)

    # .si()：不可变签名——chain 保序但不透传上游返回值（各阶段独立查库，无数据依赖）
    chain(
        fetch_feeds.si(),
        scrape_articles.si(),
        analyze_articles.si(),
        embed_articles.si(),
        reconcile_vectors.si(),  # 每日对账：清 Milvus 孤儿向量（bad/删除/判重的残留）
        sync_tag_vocabulary.si(),  # 词表从 articles.tags 聚合重建（幂等自愈，Redis 快照刷新）
        mark_pipeline_done.si(today),  # 链尾成功标记：链被打断则不落 done，当日可补跑
    ).apply_async()
    logger.info("daily pipeline 已触发（补偿 {} 项）", compensated)
    _finish_trace(stage="orchestrate", compensated=compensated)
    return f"pipeline 已触发（补偿 {compensated} 项）"


# ---------- 标签词表同步（动态词表自愈，pipeline 尾部） ----------

@celery_app.task(name="app.tasks.news.sync_tag_vocabulary", base=Task)
def sync_tag_vocabulary() -> str:
    """词表从 articles.tags 聚合重建（幂等）：覆盖 tag_words 表 + 刷新 Redis 快照。

    articles.tags 是事实源——Redis 快照丢失/LLM 新词漏写表，都能从这里自愈。
    失败不阻断主链（词表旧一版无害）。
    """
    from app.services.news import vocabulary as vocabulary_svc

    try:
        n = vocabulary_svc.rebuild_vocabulary()
        return f"词表重建完成（{n} 词）"
    except Exception as exc:  # noqa: BLE001
        logger.warning("tag vocabulary sync fail: {}", str(exc)[:120])
        return "词表同步失败（不影响主链）"


@celery_app.task(name="app.tasks.news.mark_pipeline_done")
def mark_pipeline_done(day: str) -> str:
    """链尾标记：整条流水线走完（各阶段已消化自身失败）才算当日完成。"""
    redis_client.set(f"pipeline:done:{day}", "1", ex=PIPELINE_DONE_TTL)
    logger.info("pipeline 当日全部阶段完成（done={}）", day)
    return "done"
