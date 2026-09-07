"""播客话题的 query 重写（两层 + 模板抽取）：

1. 规则快路径：关键词映射 + 任务词清洗（零成本零延迟，覆盖"XX新闻"这类直白
   表达的大多数）+ 模板句正则抽取（"用"…"开头/结尾"）；
2. LLM 兜底：规则未抽到标签时用 glm-4-flash 从动态词表挑相关标签 + rag_query
   改写 + 模板抽取。与 demo 聊天线"query 重写"同一思想。

产物是多部分 JSON（query_rewrite，多节点拆分）：
  {tags: 检索过滤标签（动态词表子集）, rag_query: 检索语义 query,
   template: {opening, ending} | None —— 脚本节点的开场白/结束语硬约束,
   via: rule / llm / raw}
未来新增节点（语气、风格…）直接在此 JSON 加 key。
"""


import re

from loguru import logger

from app.services.llm.gateway import gateway

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

LLM_PROMPT = """用户想生成一期新闻播客，给出话题描述。请做三件事：
1. 起一个播客标题（title）：8~20 字，概括核心主题，吸引人但不夸张，
   不含"生成/一期/播客"等任务词，不含开场白结束语；
2. 把话题改写成适合新闻检索的语义 query（rag_query）：去掉"生成/一份/播客"等
   任务性词汇和开场白/结束语要求，围绕核心主题补充同义关键词（如天气话题可补充
   "降雨 台风 气象预警 天气预报"），输出 10~30 字；
3. 若话题明确要求了开场白/结束语话术，提取到 template；没有就输出 null。

只输出 JSON：{{"title": "...", "rag_query": "...",
 "template": {{"opening": "开场白原文", "ending": "结束语原文"}} 或 null}}

话题：{topic}"""

# 模板句正则：引号版（”用”XX”开头”）优先，宽松版兜底（非贪婪截到提示词前）
_TMPL_QUOTED = r'[用以以是]\s*["“「『]([^"”」』]{{2,60}})["”」』]\s*(?:{}|{}|{}|{})'
_TMPL_LOOSE = (
    r'(?:{}|{})\s*(?:用|以|是)?\s*["“「『]?'
    r'([^"”」』，。！？；;]{{2,60}})["”」』]?\s*(?:{})'
)
_OPEN_WORDS = ("开头", "开场", "开始", "起始")
_CLOSE_WORDS = ("结尾", "结束", "收尾", "收场")
_OPEN_RE = re.compile(
    _TMPL_QUOTED.format(*_OPEN_WORDS) + "|" + _TMPL_LOOSE.format("开头", "开场", "起始")
)
_CLOSE_RE = re.compile(
    _TMPL_QUOTED.format(*_CLOSE_WORDS) + "|" + _TMPL_LOOSE.format("结尾", "收尾", "结束语")
)


class TopicIntent:
    __slots__ = ("tags", "query", "template", "via", "title")

    def __init__(
        self,
        tags: list[str],
        query: str,
        via: str,
        template: dict | None = None,
        title: str | None = None,
    ):
        self.tags = tags  # 词表标签子集（可为空 = 不过滤）
        self.query = query  # 清洗后的检索 query（rag_query）
        self.template = template  # {"opening": ..., "ending": ...}（可只含其一）
        self.title = title  # LLM/规则生成的播客标题（用户可后续编辑覆盖）
        self.via = via  # rule / llm / raw

    def to_dict(self) -> dict:
        """落库 podcasts.query_rewrite 的多部分 JSON（未来新节点直接加 key）。"""
        return {
            "tags": self.tags,
            "rag_query": self.query,
            "template": self.template,
            "title": self.title,
            "via": self.via,
        }


def _strip_task_words(topic: str) -> str:
    text = topic
    for w in TASK_WORDS:
        text = text.replace(w, "")
    # 去掉残留标点/空白/首尾助词，若仍有内容则用之，否则回退原话题
    cleaned = text.replace("，", " ").replace("、", " ").strip("，。！？、；; \t").strip("了的 ")
    cleaned = " ".join(cleaned.split())
    return cleaned if len(cleaned) >= 2 else topic


def extract_template(topic: str) -> tuple[dict | None, str]:
    """正则抽取开场白/结束语模板。

    返回 (template, 残余文本)：template 形如 {"opening": "...", "ending": "..."}
    （可只含其一，全未命中为 None）；残余文本已剥掉模板指令句，供检索 query 清洗。
    """
    template: dict[str, str] = {}
    residual = topic
    for regex, key in ((_OPEN_RE, "opening"), (_CLOSE_RE, "ending")):
        m = regex.search(residual)
        if m:
            phrase = (m.group(1) or "").strip().strip("，。！？、 ")
            if len(phrase) >= 2:
                template[key] = phrase
                residual = (residual[: m.start()] + residual[m.end():]).strip("，。！？、；; \t")
    return (template or None), residual


def understand_topic(topic: str) -> TopicIntent:
    """模板抽取 + rag_query 生成（规则/LLM）→ 标签由向量匹配产出（LLM 不再挑标签）。

    tags 来源：① 规则快路径 TOPIC_TAG_MAP（直白话题零成本）② 词表向量匹配
    （query 与标签词余弦 ≥ 阈值，语义泛化的确定性量化）。两者合并去重。
    """
    from app.services.news.vocabulary import get_vocabulary, match_tags

    # 0) 模板句抽取（正则，残余文本不再进检索 query）
    template, residual = extract_template(topic)
    vocabulary = get_vocabulary()
    vocab_set = set(vocabulary)

    # 1) rag_query + 标题：规则清洗 → LLM 兜底扩写（失败回退原话题）
    via = "rule"
    query = _strip_task_words(residual)
    title = query or None  # 规则路径标题 = 清洗后话题词；LLM 路径用生成的
    if not query or query == topic:  # 规则清洗无增益，走 LLM 扩写
        try:
            resp = gateway.chat(
                "zhipu",
                messages=[
                    {"role": "user", "content": LLM_PROMPT.format(topic=topic)}
                ],
                response_format={"type": "json_object"},
                max_tokens=300,
                temperature=0.0,
                langfuse_meta={"query_understanding": True, "topic": topic[:50]},
            )
            import json

            data = json.loads((resp.choices[0].message.content or "").strip() or "{}")
            llm_query = str(data.get("rag_query") or "").strip()[:60]
            llm_title = str(data.get("title") or "").strip()[:50]
            if llm_query:
                query = llm_query
                via = "llm"
            if llm_title:
                title = llm_title
            llm_template = data.get("template") if isinstance(data.get("template"), dict) else None
            merged = {**(llm_template or {}), **(template or {})}  # 正则命中优先（逐字原文更可靠）
            template = merged or None
        except Exception as exc:  # noqa: BLE001  兜底路径失败不影响主流程
            logger.opt(exception=True).warning("query understanding fail: {}", str(exc)[:60])

    # 2) 标签：规则命中 + 词表向量匹配（阈值量化，替代 LLM 挑选），合并去重
    tags = [tag for kw, tag in TOPIC_TAG_MAP.items() if kw in residual]
    tags = [t for t in dict.fromkeys(t for t in tags if t in vocab_set)]
    for t in match_tags(query):
        if t not in tags:
            tags.append(t)
    return TopicIntent(
        tags=tags[:3], query=query or topic, via=via, template=template, title=title
    )
