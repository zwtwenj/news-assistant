"""封闭类目表与分类器（检索路由层，2026-09 重构）。

设计依据（实验与调研背书，见 docs/plan-retrieval-architecture.md）：
- 表来源：央视网/新浪/今日头条/THUCNews 四体系交叉共识 + 本项目真实流量补充
- LLM 仅可从本表选择（1 主类 + ≤2 副类），无造词权——白名单校验是合同，prompt 只是请求
- 与旧标签路的本质区别：封闭菜单（不会碎片化）+ 只用于过滤/路由（不参与打分）
- 事件层（event_id）暂为占位（article_id），聚类去重见 S3 规划

TODO(后续)：类目表迁移到后管配置（DB 表 + 管理界面），当前硬编码。
"""

import json
from typing import Any

import httpx
from loguru import logger

from app.core.config import get_settings

# ── 封闭类目表（改表须同步迁移脚本与后管配置规划） ──
CATEGORIES: dict[str, str] = {
    # 第一层：四体系共识核心
    "时政国内": "国内政治、政策发布、党政要闻、领导人活动",
    "国际":     "国际局势、外交、外国事务、国际组织（含境外事件）",
    "财经":     "宏观经济、金融市场、产业经济、企业动态、能源",
    "科技":     "科技产业、互联网、人工智能、数码产品、航天",
    "体育":     "体育赛事、运动员、体育产业",
    "娱乐":     "影视、明星、综艺、音乐、游戏",
    "社会":     "社会事件、民生百态、安全事故、人物故事",
    "军事":     "国防、军队、军演、军工",
    "法治":     "法律案件、司法、公安、普法",
    "教育":     "教育政策、考试招生、校园、研学",
    "文化":     "文物保护、图书出版、非遗、文化交流、旅游",
    "健康":     "医疗、医保、公共卫生、健身养生",
    # 第二层：本项目语料高频补充
    "汽车":     "汽车产业、新能源汽车、车展、智驾",
    "就业社保": "就业政策、社保、劳动权益、生育支持",
    "农业农村": "粮食安全、乡村振兴、农业科技、农民增收",
    "消费":     "消费政策、假期经济、文旅消费、市场监管、交通出行",
    # 第三层：真实流量补充（「天气播客」query 出现 3 次）
    "气象灾害": "天气预报、台风暴雨、地震地质、防灾救灾、极端气候",
    # 兜底
    "other":    "以上皆不贴切（不得作为副类目）",
}

_CLASSIFY_API = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
_CLASSIFY_MODEL = "glm-4-flash"  # 免费档；菜单分类任务无需强模型

_CLASSIFY_PROMPT = """你是新闻编辑，从固定类目表中给新闻选分类。

类目表：
{table}

规则：
1. 选出【一个主类目】——文章核心主题所属
2. 最多再选【两个副类目】——确实跨界才选，没有就给空数组
3. 都不贴切主类目选 other（other 不得作副类目）
4. 只输出 JSON：{{"primary": "类目名", "aux": ["类目名", ...]}}

标题：{title}
正文：{content}"""

_MACRO_PROMPT = """判断用户的播客话题是「具体话题」还是「宏观类目」，若是宏观类目给出对应类目。

类目表：
{table}

例子：
- "医保DRG付费改革怎么样" → 具体话题
- "最近的国际新闻" → 宏观类目：国际
- "台风摩羯的影响" → 具体话题
- "聊聊最近的天气" → 宏观类目：气象灾害
- "近期娱乐圈热点" → 宏观类目：娱乐

只输出 JSON：{{"is_macro": true/false, "category": "类目名或null"}}

话题：{topic}"""


def _chat(prompt: str) -> dict[str, Any]:
    s = get_settings()
    resp = httpx.post(
        _CLASSIFY_API,
        headers={"Authorization": f"Bearer {s.zhipu_api_key}"},
        json={
            "model": _CLASSIFY_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "max_tokens": 150,
            "temperature": 0.0,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def classify_article(title: str, content: str) -> dict[str, Any]:
    """入库时分类（1 主 + ≤2 副）。菜单违规触发一次严格重试，白名单兜底。

    返回 {"category": 主类, "aux_categories": [副类]}；任何失败返回 other/空（不阻断入库）。
    """
    table = "\n".join(f"- {k}：{v}" for k, v in CATEGORIES.items())
    try:
        out: dict[str, Any] = {}
        for attempt in range(2):
            suffix = ("\n\n注意：你上次的答案不在类目表里。主类目必须【逐字】从表中选最接近的，"
                      "禁止编造新类目。" if attempt else "")
            prompt = _CLASSIFY_PROMPT.format(
                table=table, title=title, content=content[:1200]) + suffix
            out = _chat(prompt)
            if out.get("primary") in CATEGORIES:
                break
        return {
            "category": out.get("primary") if out.get("primary") in CATEGORIES else "other",
            "aux_categories": [
                a for a in out.get("aux", [])
                if a in CATEGORIES and a != "other"
            ][:2],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("分类失败（不阻断入库）: {}", str(exc)[:80])
        return {"category": "other", "aux_categories": []}


def detect_macro(topic: str) -> str | None:
    """综述型话题路由：返回目标类目名；具体话题返回 None。

    消费方（播客检索）据此在「hybrid 检索」与「类目浏览」两条管道间分流。
    """
    table = "\n".join(f"- {k}：{v}" for k, v in CATEGORIES.items() if k != "other")
    try:
        out = _chat(_MACRO_PROMPT.format(table=table, topic=topic))
        if out.get("is_macro") and out.get("category") in CATEGORIES:
            return out["category"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("macro 检测失败，按具体话题处理: {}", str(exc)[:80])
    return None
