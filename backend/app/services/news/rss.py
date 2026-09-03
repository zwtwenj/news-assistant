"""RSS 拉取与解析：24 小时窗口过滤（plan：只采集近 24h，同 demo 逻辑）。"""

import random
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import feedparser
import httpx
from loguru import logger

WINDOW = timedelta(hours=24)
TIMEOUT = 20
UA_POOL = [  # UA 轮换，沿用 demo 做法
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/17.4",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _parse_time(entry: dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(time.mktime(parsed), tz=UTC)
    return None


def fetch_feed(url: str, source_name: str = "") -> list[dict[str, Any]]:
    """拉取并解析 RSS，返回窗口内条目。

    跳过：无链接 / 无标题 / 无发布时间或解析失败 / 24h 之外的条目。
    异常：网络/解析错误向上抛（由调用方记日志、不阻断其他源）。
    """
    headers = {"User-Agent": random.choice(UA_POOL)}
    resp = httpx.get(url, headers=headers, timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    if feed.bozo and not feed.entries:
        raise ValueError(f"RSS 解析失败: {feed.bozo_exception}")

    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for entry in feed.entries:
        link = entry.get("link", "").strip()
        title = (entry.get("title") or "").strip()
        publish_time = _parse_time(entry)
        if not link or not title:
            continue
        if publish_time is None:
            continue  # 无时间的条目跳过（无法判断新旧，避免旧文重复入库）
        if publish_time < now - WINDOW:
            continue
        out.append(
            {
                "url": link,
                "title": title,
                "summary": (entry.get("summary") or "").strip(),
                "publish_time": publish_time,
                "source": source_name or (feed.feed.get("title") or "")[:200],
            }
        )
    logger.info("rss {} 条目 {}（窗口内）", url, len(out))
    return out
