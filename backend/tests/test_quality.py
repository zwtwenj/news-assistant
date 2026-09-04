"""规则质检单测：样本取自 144 篇存量数据的真实垃圾/正常形态。"""

from app.services.news.quality import check_content

# 真实垃圾形态①：纯导航页（焦点访谈失败案例的形态）
NAV_PAGE = "\n".join(
    [
        "新闻", "新闻频道", ">", "中国新闻", "某标题正文没有的页面",
        "来源：央视网 | 2026年09月03日", "原标题：", "正在加载",
        "编辑：谢博韬", "责任编辑：刘亮", "点击收起全文",
        "返回央视网首页", "返回新闻频道", "分享：", "扫一扫 分享到微信",
        "|", "返回顶部", "望海热线", "xinwenxiansuo@staff.cntv.cn",
    ]
)

# 真实垃圾形态②：半垃圾（导航 + 一小段正文，中文占比正常但结构差）
HALF_GARBAGE = "\n".join(
    [
        "扫一扫 手机继续看", "A- A+", "返回顶部",
        "某地今日举办了一场活动。", "责任编辑：张三", "分享到微信",
    ]
)

# 正常形态①：标准新闻正文（>200 字，多段）
GOOD_NEWS = "\n".join(
    [
        "水利部和中国气象局联合发布橙色预警，提示多地防范灾害风险，这是本月以来第二次发布高级别预警。",
        "预警指出未来二十四小时内部分地区发生风险较高，需要加强巡查值守力度，重点防范山区地质灾害。",
        "相关部门已启动应急响应机制，组织力量对重点区域开展拉网式排查，确保不留死角不漏隐患。",
        "专家提醒公众密切关注官方发布的信息，合理安排出行计划，避免前往危险区域并注意自身安全。",
        "目前各项防范工作正在有序推进，各地应急物资储备充足，后续情况将持续向社会通报。",
    ]
)

# 正常形态②：短讯（<200 字，真新闻 → suspect 不杀）
SHORT_NEWS = (
    "某地今日发生轻微震动，震源深度较深。"
    "据初步核实，当地暂无财产损失报告，居民生活秩序正常。"
)


def test_nav_page_is_bad() -> None:
    verdict, reasons = check_content("焦点访谈｜救援力量开展搜救", NAV_PAGE)
    assert verdict == "bad"
    assert any("导航" in r for r in reasons)


def test_half_garbage_is_bad() -> None:
    verdict, reasons = check_content("某地举办活动", HALF_GARBAGE)
    assert verdict == "bad", reasons


def test_good_news_passes() -> None:
    verdict, reasons = check_content("水利部发布预警多地防范", GOOD_NEWS)
    assert verdict == "good", reasons


def test_short_news_is_suspect_not_bad() -> None:
    verdict, _ = check_content("某地发生轻微震动", SHORT_NEWS)
    assert verdict == "suspect"


def test_empty_content_is_bad() -> None:
    assert check_content("任意标题", "")[0] == "bad"
    assert check_content("任意标题", "   \n  ")[0] == "bad"


def test_title_terms_extraction() -> None:
    from app.services.news.quality import _title_terms

    terms = _title_terms("平陆运河举行船舶通航全要素综合演练")
    assert any("平陆" in t or "运河" in t for t in terms)
    assert all(len(t) >= 2 for t in terms)
