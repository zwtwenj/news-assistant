"""新浪滚动新闻回填客户端（后管手动触发，非定时源）。

接口：feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=..&num=50&page=N
实测（2026-09-28）：存档深度 ~5 天（翻页到空即到头，hora 时间游标无效）；
活栏目 2509 国内 / 2516 科技 / 2517 财经（国际/体育栏在滚动源已停更）；
日量三栏合计 ~1400 条，内容偏财经（分类对照预检 other 率 2%，白名单够用）。
产出条目结构与 rss_svc.fetch_feed 同款，调用方（fetch_sina_roll 任务）零适配。
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger

API = "https://feed.mix.sina.com.cn/api/roll/get"
# 实测（2026-09-30 全 lid 扫描）：活栏目且流互不相同的为 2509 综合 / 2512 彩票 /
# 2513 娱乐 / 2515 健康——2516~2518 与 2509 同流（跨栏去重零增量），
# 2510/2514 停更、2511 时间戳脏数据；内容分类由 analyze 阶段白名单裁定
LID_NAMES = {2509: "综合", 2512: "彩票", 2513: "娱乐", 2515: "健康"}
PAGE_SIZE = 50
MAX_PAGES = 120  # 存档深度兜底（实测 ~55 页到头，留余量）
THROTTLE = 0.3  # 对源友好
TIMEOUT = 20
SOURCE_NAME = "新浪新闻"


def fetch_roll(days: int = 5, lids: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """拉取近 days 天的滚动条目（跨栏目 url 去重），翻页到时间线外/空页即止。

    无 ctime 的条目跳过（与 RSS 源"无发布时间不入库"口径一致）。
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lid, name in (lids or LID_NAMES).items():
        pages = 0
        for page in range(1, MAX_PAGES + 1):
            resp = httpx.get(
                API,
                params={"pageid": 153, "lid": lid, "k": "",
                        "num": PAGE_SIZE, "page": page},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            arts = resp.json().get("result", {}).get("data", []) or []
            if not arts:
                break
            stop = False
            for a in arts:
                try:
                    ct = int(a.get("ctime") or 0)
                except (TypeError, ValueError):
                    continue
                url = (a.get("url") or "").strip()
                title = (a.get("title") or "").strip()
                if not url or not title or url in seen:
                    continue
                published = datetime.fromtimestamp(ct, tz=UTC) if ct else None
                if published is None or published < cutoff:
                    stop = True  # 已越过时间线，本栏翻页结束
                    continue
                seen.add(url)
                out.append({
                    "url": url,
                    "title": title,
                    "summary": (a.get("introduce") or "").strip(),
                    "publish_time": published,
                    "source": SOURCE_NAME,
                })
            pages += 1
            if stop:
                break
            time.sleep(THROTTLE)
        logger.info("sina roll 栏目 {}({}) 翻 {} 页，累计 {} 条", name, lid, pages, len(out))
    return out
