"""正文规则质检：入库前的第一道门禁（plan 质量四层防御第②层）。

纯函数、微秒级、零成本，在 scrape 成功后同步执行：
- bad    → 任一硬指标不合格（导航页/符号页/标题不符/无段落）→ 走 failed 路径，不入库
- suspect → 仅长度偏短（<200 字，短讯可能是真新闻）→ 标记放行，交语义检测复核
- good   → 全部通过

阈值源自 144 篇存量数据的垃圾形态分析（导航页/半垃圾/正常文实测校准）。
"""

import re

# 导航/页脚特征词（行级判定用）
NAV_KEYWORDS = (
    "扫一扫", "责任编辑", "正在加载", "点击收起", "返回顶部", "分享到微信",
    "新闻频道", "首页", "编辑：", "来源：", "原标题", "客户端", "热线",
)
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
# 标题分词后的停用词（无检索意义，剔除后再算命中率）
TITLE_STOPWORDS = set("的了和与及在是对于被把从到上下") | {
    "报道", "新闻", "发布", "什么", "如何", "为什么", "有关", "关于",
}

MIN_LEN = 200          # 低于此长度 → suspect
NAV_LINE_RATIO_MAX = 0.30  # 导航行占比上限 → bad
CHINESE_RATIO_MIN = 0.60   # 中文占比下限 → bad
TITLE_HIT_RATIO_MIN = 0.50  # 标题词命中率下限 → bad


def check_content(title: str, content: str) -> tuple[str, list[str]]:
    """返回 (verdict, reasons)。verdict: good / suspect / bad。"""
    reasons: list[str] = []
    if not content or not content.strip():
        return "bad", ["正文为空"]

    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]

    # 1) 导航行占比
    if lines:
        nav_ratio = sum(1 for ln in lines if any(k in ln for k in NAV_KEYWORDS)) / len(lines)
        if nav_ratio > NAV_LINE_RATIO_MAX:
            reasons.append(f"导航行占比 {nav_ratio:.0%}")

    # 2) 中文占比（剔除非中文字符后按可读字符算）
    stripped = re.sub(r"\s", "", content)
    if stripped:
        cn_ratio = len(CHINESE_RE.findall(stripped)) / len(stripped)
        if cn_ratio < CHINESE_RATIO_MIN:
            reasons.append(f"中文占比 {cn_ratio:.0%}")

    # 3) 标题相关性：标题分词（简易 n-gram，jieba 仅在语义检测用，这里保持零依赖）
    title_terms = _title_terms(title)
    if title_terms:
        hit = sum(1 for t in title_terms if t in content) / len(title_terms)
        if hit < TITLE_HIT_RATIO_MIN:
            reasons.append(f"标题词命中率 {hit:.0%}")

    # 4) 段落结构：有效段落（去导航行后 >20 字的行）——
    #    完全没有有效段落且偏短才判 bad；单段短讯（快讯类）是真新闻形态 → 交软指标/语义检测
    effective = [ln for ln in lines if len(ln) > 20 and not any(k in ln for k in NAV_KEYWORDS)]
    if not effective and len(content) < MIN_LEN:
        reasons.append(f"有效段落 {len(effective)} 行")

    # 硬指标（1~4）任一不合格 → bad
    if reasons:
        return "bad", reasons
    # 5) 长度软指标 → suspect
    if len(content) < MIN_LEN:
        reasons.append(f"长度 {len(content)} 字")
        return "suspect", reasons
    return "good", []


def _title_terms(title: str) -> list[str]:
    """标题切词（jieba 精确分词，无跨界噪声），去停用词与单字。

    jieba 不可用时退化为整段切分（保守，仅影响命中率精度不影响方向）。
    """
    try:
        import jieba

        words = [w.strip() for w in jieba.lcut(title) if len(w.strip()) >= 2]
    except Exception:  # noqa: BLE001
        words = [seg for seg in re.split(r"[^\u4e00-\u9fff]+", title) if len(seg) >= 2]
    return [w for w in dict.fromkeys(words) if w not in TITLE_STOPWORDS]
