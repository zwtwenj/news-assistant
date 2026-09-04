"""正文抽取：三级降级链（trafilatura → <p> 标签聚合 → RSS summary）+ 垃圾检测。

实测（2026-09-05）：央视焦点访谈类页面 trafilatura 只能抽出导航文本（283 字），
正文在 HTML 的 <p> 标签里完整存在——p 聚合可救回。垃圾检测用于识别
"抽出来的是页面导航而非正文"的情况，触发降级。
"""

import html as html_lib
import re

import trafilatura

MIN_CONTENT_LEN = 200  # 低于此长度视为不可用
# 导航/页脚关键词：短文本中共现多个 = 抽到的是页面壳而非正文
NAV_KEYWORDS = ("扫一扫", "责任编辑", "正在加载", "点击收起", "新闻频道", "返回顶部", "分享到微信")


def _is_garbage(text: str) -> bool:
    """垃圾检测：太短，或导航关键词共现 ≥2 个。"""
    if len(text) < MIN_CONTENT_LEN:
        return True
    return sum(1 for k in NAV_KEYWORDS if k in text) >= 2


def _clean_rss_summary(summary: str) -> str:
    """RSS summary 常带 HTML 标签：剥掉标签 + 反转义。"""
    text = re.sub(r"<[^>]+>", " ", summary)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_paragraphs(html: str) -> str:
    """<p> 标签聚合兜底：过滤视频代码/短行/导航行后拼接。"""
    raw = re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)
    texts = []
    for p in raw:
        t = re.sub(r"<[^>]+>|&nbsp;", " ", p)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) < 20:  # 短行多为标签/页脚
            continue
        if "htmlVideoCode" in t or "newPlayer" in t:  # 视频组件代码
            continue
        if any(k in t for k in NAV_KEYWORDS):
            continue
        texts.append(t)
    return "\n".join(texts)


def extract(html: str, fallback_summary: str) -> tuple[str, str]:
    """返回 (正文, 方式)。方式：web=trafilatura / p_tags=<p>聚合 / rss=摘要兜底 / failed。

    降级链：trafilatura → p 聚合 → RSS summary，逐级做垃圾检测，
    取第一个"干净且够长"的结果；全部失败时保留最长者并如实标注。
    """
    candidates: list[tuple[str, str]] = []
    try:
        t = (trafilatura.extract(html, include_comments=False) or "").strip()
        candidates.append((t, "web"))
    except Exception:  # noqa: BLE001
        pass
    candidates.append((_extract_paragraphs(html), "p_tags"))
    candidates.append((_clean_rss_summary(fallback_summary), "rss"))

    # 逐级取第一个干净可用的
    for text, method in candidates:
        if not _is_garbage(text):
            return text, method
    # 全军覆没：保留最长者（上游按长度计失败/兜底）
    best = max(candidates, key=lambda c: len(c[0]))
    return best[0], "failed" if len(best[0]) < MIN_CONTENT_LEN else best[1]
