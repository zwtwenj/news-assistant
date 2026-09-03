"""simhash / rss 时间过滤 / extractor 双判的单元测试（不依赖网络与 DB）。"""

import pytest

from app.services.news import simhash as sh
from app.services.news.extractor import _clean_rss_summary, extract

# ---------- simhash ----------

# 用真实新闻长度（数百字）测试：simhash 对短文本天然不稳定，判重场景都是长正文
TEXT_A = (
    "国家统计局今日公布数据显示，三季度国内生产总值同比增长4.9%，"
    "经济持续恢复向好，就业物价总体保持稳定。" * 10
)
TEXT_A_REPOSTED = TEXT_A + "（转载）"  # 同文转载场景：全文相同 + 尾部短声明
TEXT_B = (
    "某科技公司发布新款智能手机，搭载自研芯片，影像能力大幅升级，"
    "起售价3999元，下周开售。" * 10
)


def test_simhash_identical_text() -> None:
    assert sh.simhash(TEXT_A) == sh.simhash(TEXT_A)


def test_simhash_reposted_text_is_similar() -> None:
    assert sh.is_similar(sh.simhash(TEXT_A), sh.simhash(TEXT_A_REPOSTED))


def test_simhash_unrelated_text_not_similar() -> None:
    assert not sh.is_similar(sh.simhash(TEXT_A), sh.simhash(TEXT_B))


def test_simhash_hex_roundtrip() -> None:
    value = sh.simhash(TEXT_A)
    assert sh.from_hex(sh.to_hex(value)) == value


def test_simhash_empty_text() -> None:
    # 空文本特征为空，weights 全 0 → bits 全 0；不抛错即可
    assert sh.simhash("") == 0


# ---------- extractor ----------

GOOD_HTML = (
    "<html><body><article>"
    + "<p>这是一段足够长的新闻正文内容，用于通过两百字的最低长度校验。</p>" * 20
    + "</article></body></html>"
)
NAV_HEAVY_HTML = (
    "<html><body><nav>首页 新闻 体育 娱乐 关于我们 联系方式 登录 注册</nav></body></html>"
)
RSS_SUMMARY = (
    "<p>这是RSS摘要提供的正文内容，包含一段完整的新闻概述信息，"
    "比页面抽取结果更长从而触发兜底逻辑。</p>"
)


def test_extract_prefers_web_content() -> None:
    content, method = extract(GOOD_HTML, RSS_SUMMARY)
    assert method == "web"
    assert "新闻正文内容" in content


def test_extract_falls_back_to_rss_summary() -> None:
    content, method = extract(NAV_HEAVY_HTML, RSS_SUMMARY)
    assert method == "rss"
    assert "RSS摘要" in content


def test_clean_rss_summary_strips_html() -> None:
    cleaned = _clean_rss_summary("<p>Hello&nbsp;<b>World</b></p>")
    assert cleaned == "Hello World"


# ---------- rss：24h 窗口过滤（mock httpx，不走网络） ----------

def _rss_xml(items: str) -> bytes:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>测试源</title>'
        f"{items}</channel></rss>"
    ).encode()


def test_rss_24h_window_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    from app.services.news import rss as rss_svc

    now = datetime.now(UTC)
    items = (
        f"<item><title>新文章</title><link>https://e.com/1</link>"
        f"<pubDate>{format_datetime(now)}</pubDate></item>"
        f"<item><title>三天前</title><link>https://e.com/2</link>"
        f"<pubDate>{format_datetime(now - timedelta(days=3))}</pubDate></item>"
        "<item><title>无时间</title><link>https://e.com/3</link></item>"
        "<item><title>无链接</title><pubDate>"
        f"{format_datetime(now)}</pubDate></item>"
    )

    class FakeResp:
        content = _rss_xml(items)

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(rss_svc.httpx, "get", lambda *a, **k: FakeResp())
    entries = rss_svc.fetch_feed("https://feed.test")
    assert len(entries) == 1  # 旧文、无时间、无链接全部被过滤
    assert entries[0]["title"] == "新文章"
