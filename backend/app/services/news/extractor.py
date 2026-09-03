"""正文抽取：trafilatura 抽取 + 字数双判，RSS summary 兜底（升级自 demo 的纯字数对比）。"""

import html as html_lib
import re

import trafilatura

MIN_CONTENT_LEN = 200  # 抽取正文低于此长度视为失败，走兜底


def _clean_rss_summary(summary: str) -> str:
    """RSS summary 常带 HTML 标签：剥掉标签 + 反转义。"""
    text = re.sub(r"<[^>]+>", " ", summary)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract(html: str, fallback_summary: str) -> tuple[str, str]:
    """返回 (正文, 方式)。方式：web=页面抽取 / rss=摘要兜底。

    双判逻辑：
    1. trafilatura 抽取正文；
    2. 抽取结果 >= 200 字 → 用页面正文；
    3. 否则与清洗后的 RSS summary 比字数，取更长者（导航栏多的页面骗不过字数下限）。
    """
    extracted = ""
    try:
        extracted = (trafilatura.extract(html, include_comments=False) or "").strip()
    except Exception:  # noqa: BLE001  抽取器对畸形页面可能抛错，走兜底
        extracted = ""

    fallback = _clean_rss_summary(fallback_summary)
    if len(extracted) >= MIN_CONTENT_LEN:
        return extracted, "web"
    if len(fallback) > len(extracted):
        return fallback, "rss"
    return extracted, "web"  # 两边都短：保留抽取结果（后续 simhash/打标自然处理）
