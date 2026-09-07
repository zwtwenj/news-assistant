"""per-user RSS feed：配置管理 + RSS 2.0 / iTunes 规范 XML 生成。

feed URL 公开可访问（token 混淆，不可枚举）；内容 = 该用户 feed_published_at
非空、未禁用、未软删的播客。guid 用 podcast id（永久稳定，平台按 guid 幂等同步）。
"""

import secrets
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.podcast import Podcast
from app.models.rss_feed import RssFeed
from app.models.user import User


def ensure_user_feed(db, user: User) -> RssFeed:
    """取/建用户 feed 配置。默认频道名用用户标识（手机号尾4/GitHub名）。"""
    feed = db.query(RssFeed).filter(RssFeed.user_id == user.id).first()
    if feed is not None:
        return feed
    label = user.github_login or f"用户{user.phone[-4:] if user.phone else user.id}"
    feed = RssFeed(
        user_id=user.id,
        feed_token=secrets.token_urlsafe(24),
        channel_title=f"{label}的新闻播客",
        channel_description=("由新闻助手 AI 生成的个性化新闻播报节目，"
                             "基于近 7 天新闻素材自动撰写与合成。"),
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


def get_feed_by_token(token: str) -> RssFeed | None:
    db = SessionLocal()
    try:
        return db.query(RssFeed).filter(RssFeed.feed_token == token).first()
    finally:
        db.close()


def get_feed_url(feed: RssFeed) -> str:
    return f"{get_settings().rss_public_base.rstrip('/')}/feed/{feed.feed_token}.xml"


def _display_title(p: Podcast) -> str:
    return p.title or p.topic_prompt


def _itunes_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _rfc822(dt: datetime) -> str:
    from email.utils import format_datetime

    return format_datetime(dt)


def build_feed_xml(feed: RssFeed) -> str:
    """生成 RSS 2.0 + iTunes 规范 XML。用户标识取自 user（GitHub 名/手机尾号）。"""
    s = get_settings()
    db = SessionLocal()
    try:
        user = db.get(User, feed.user_id)
        author = (user.github_login if user and user.github_login else None) or (
            f"用户{user.phone[-4:]}" if user and user.phone else f"用户{feed.user_id}"
        )
        episodes = (
            db.execute(
                select(Podcast)
                .where(
                    Podcast.user_id == feed.user_id,
                    Podcast.deleted_at.is_(None),
                    Podcast.disabled_at.is_(None),
                    Podcast.feed_published_at.is_not(None),
                    Podcast.status == "succeeded",
                    Podcast.audio_url.is_not(None),
                )
                .order_by(Podcast.feed_published_at.desc())
                .limit(300)
            )
            .scalars()
            .all()
        )
    finally:
        db.close()

    cover = s.rss_default_cover
    feed_url = get_feed_url(feed)
    last_build = max(
        (ep.feed_published_at for ep in episodes), default=feed.updated_at or datetime.now(UTC)
    )

    items = []
    for ep in episodes:
        pub = ep.feed_published_at or ep.created_at
        ep_cover = ep.cover_url or cover
        desc = escape(ep.description or ep.topic_prompt)
        items.append(f"""    <item>
      <title>{escape(_display_title(ep))}</title>
      <guid isPermaLink="false">podcast-{ep.id}</guid>
      <pubDate>{_rfc822(pub)}</pubDate>
      <description>{desc}</description>
      <itunes:summary>{desc}</itunes:summary>
      <itunes:duration>{_itunes_duration(ep.duration_sec or 0)}</itunes:duration>
      <itunes:image href="{escape(ep_cover)}" />
      <enclosure url="{escape(ep.audio_url)}" length="{ep.size_bytes or 0}" type="audio/mpeg" />
    </item>""")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(feed.channel_title)}</title>
    <link>{escape(s.rss_public_base)}</link>
    <description>{escape(feed.channel_description)}</description>
    <language>zh-cn</language>
    <lastBuildDate>{_rfc822(last_build)}</lastBuildDate>
    <atom:link href="{escape(feed_url)}" rel="self" type="application/rss+xml" />
    <itunes:author>{escape(author)}</itunes:author>
    <itunes:summary>{escape(feed.channel_description)}</itunes:summary>
    <itunes:type>episodic</itunes:type>
    <itunes:image href="{escape(cover)}" />
    <itunes:explicit>false</itunes:explicit>
    <itunes:owner>
      <itunes:name>{escape(author)}</itunes:name>
      <itunes:email>{escape(s.rss_owner_email)}</itunes:email>
    </itunes:owner>
    <itunes:category text="News" />
{chr(10).join(items)}
  </channel>
</rss>
"""
