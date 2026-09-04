"""播客话题的 query 理解（两层）：

1. 规则快路径：封闭标签白名单的关键词映射 + 任务词清洗（零成本零延迟，覆盖
   "XX新闻"这类直白表达的大多数）；
2. LLM 兜底：规则未抽到标签时用 glm-4-flash 做意图分类（从 12 分类白名单选
   0~2 个）+ query 改写（去掉"生成一份播客"等任务指令词，输出对检索友好的
   语义 query）。与 demo 聊天线"query 重写"同一思想的两面应用。
"""


from loguru import logger

from app.services.llm.gateway import gateway
from app.services.news.analyzer import CATEGORIES

# 关键词 → 白名单标签（快路径词表，LLM 兜底也输出同一白名单）
TOPIC_TAG_MAP = {
    "国际": "国际", "外交": "国际", "国外": "国际", "社会": "社会", "民生": "社会",
    "财经": "财经", "经济": "财经", "金融": "财经", "贸易": "财经", "股市": "财经",
    "体育": "体育", "足球": "体育", "篮球": "体育", "奥运": "体育", "亚运": "体育",
    "娱乐": "娱乐", "影视": "娱乐", "明星": "娱乐", "综艺": "娱乐", "电影": "娱乐",
    "科技": "科技", "技术": "科技", "AI": "科技", "人工智能": "科技", "芯片": "科技",
    "军事": "军事", "国防": "军事", "教育": "教育", "健康": "健康", "医疗": "健康",
    "汽车": "汽车", "游戏": "游戏",
}
# 任务指令词（对检索是噪声，清洗掉）
TASK_WORDS = ("生成", "制作", "帮我", "给我", "一份", "一期", "一段", "最近", "最新",
              "播客", "节目", "音频", "电台", "新闻", "资讯", "聊聊", "谈谈", "关于")

LLM_PROMPT = """用户想生成一期新闻播客，给出话题描述。请做两件事：
1. 从以下分类白名单中选出 0~2 个最贴切的分类：{categories}
   （话题没有明确类别倾向就选空数组，不要硬选）；
2. 把话题改写成适合新闻检索的语义 query：去掉"生成/一份/播客"等任务性词汇，
   保留核心主题词，可适当补充同义关键词。

只输出 JSON：{{"tags": ["..."], "query": "..."}}

话题：{topic}"""


class TopicIntent:
    __slots__ = ("tags", "query", "via")

    def __init__(self, tags: list[str], query: str, via: str):
        self.tags = tags  # 白名单标签子集（可为空 = 不过滤）
        self.query = query  # 清洗后的检索 query
        self.via = via  # rule / llm / raw


def _strip_task_words(topic: str) -> str:
    text = topic
    for w in TASK_WORDS:
        text = text.replace(w, "")
    # 去掉残留标点/空白/首尾助词，若仍有内容则用之，否则回退原话题
    cleaned = text.strip("，。！？、 \t").strip("了的 ")
    return cleaned if len(cleaned) >= 2 else topic


def understand_topic(topic: str) -> TopicIntent:
    """规则快路径 → LLM 兜底 → 原样兜底（永不抛错）。"""
    # 1) 规则：关键词抽标签 + 任务词清洗
    tags = [tag for kw, tag in TOPIC_TAG_MAP.items() if kw in topic]
    query = _strip_task_words(topic)
    if tags:
        return TopicIntent(tags=tags, query=query or topic, via="rule")

    # 2) LLM 兜底：口语化/隐含类别表达
    try:
        resp = gateway.chat(
            "zhipu",
            messages=[
                {"role": "user", "content": LLM_PROMPT.format(
                    categories="/".join(CATEGORIES), topic=topic)}
            ],
            response_format={"type": "json_object"},
            max_tokens=100,
            temperature=0.0,
            langfuse_meta={"query_understanding": True, "topic": topic[:50]},
        )
        import json

        data = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        llm_tags = [t for t in data.get("tags", []) if t in CATEGORIES][:2]
        llm_query = str(data.get("query", "")).strip()[:60]
        if llm_tags or llm_query:
            return TopicIntent(
                tags=llm_tags, query=llm_query or query or topic, via="llm"
            )
    except Exception as exc:  # noqa: BLE001  兜底路径失败不影响主流程
        logger.opt(exception=True).warning("query understanding fail: {}", str(exc)[:60])

    # 3) 原样兜底
    return TopicIntent(tags=[], query=topic, via="raw")
