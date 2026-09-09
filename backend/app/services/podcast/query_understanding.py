"""播客话题的 query 重写（LLM 全量 + 标签向量匹配）。

一次 LLM 调用产出多部分 JSON（多节点拆分）：
  {tags 来源见下, rag_query: 检索语义 query,
   title: 8~20 字播客标题, template: {opening, ending} | None}

设计变更（2026-09-10）：废弃规则快路径（TOPIC_TAG_MAP 关键词映射、任务词清洗、
模板正则抽取）——规则在中文引号、模板句残留等场景接连出错（id=239 标题带整段
模板句的事故），LLM 全量处理的成本可忽略（flash 级、每期播客仅一次）。
tags 仍由词表向量匹配产出（确定性量化，不交给 LLM 猜）。
"""


import json

from loguru import logger

from app.services.llm.gateway import gateway

LLM_PROMPT = """用户想生成一期新闻播客，给出话题描述。请做三件事：
1. 起一个播客标题（title）：8~20 字，概括核心主题，吸引人但不夸张，
   不含"生成/一期/播客"等任务词，不含开场白结束语；
2. 把话题改写成适合新闻检索的语义 query（rag_query）：去掉"生成/一份/播客"等
   任务性词汇和开场白/结束语要求，围绕核心主题补充同义关键词（如天气话题可补充
   "降雨 台风 气象预警 天气预报"），输出 10~30 字；
3. 若话题明确要求了开场白/结束语话术，逐字提取到 template（保持原文一字不改）；
   没有就输出 null。

只输出 JSON：{{"title": "...", "rag_query": "...",
 "template": {{"opening": "开场白原文", "ending": "结束语原文"}} 或 null}}

话题：{topic}"""


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
        self.tags = tags  # 词表标签子集（向量匹配产出，可为空 = 不过滤）
        self.query = query  # 清洗后的检索 query（rag_query）
        self.template = template  # {"opening": ..., "ending": ...}（可只含其一）
        self.title = title  # LLM 生成的播客标题（用户可后续编辑覆盖）
        self.via = via  # llm / raw

    def to_dict(self) -> dict:
        """落库 podcasts.query_rewrite 的多部分 JSON（未来新节点直接加 key）。"""
        return {
            "tags": self.tags,
            "rag_query": self.query,
            "template": self.template,
            "title": self.title,
            "via": self.via,
        }


def understand_topic(topic: str) -> TopicIntent:
    """LLM 一次产出 title/rag_query/template；失败回退原话题（永不抛错）。

    tags 由词表向量匹配产出（query 与标签词余弦 ≥ 阈值，确定性量化）。
    """
    from app.services.news.vocabulary import match_tags

    query, title, template = topic, None, None
    via = "raw"
    try:
        resp = gateway.chat(
            "zhipu",
            messages=[{"role": "user", "content": LLM_PROMPT.format(topic=topic)}],
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0.0,
            langfuse_meta={"query_understanding": True, "topic": topic[:50]},
        )
        data = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        llm_query = str(data.get("rag_query") or "").strip()[:60]
        llm_title = str(data.get("title") or "").strip()[:50]
        llm_template = data.get("template") if isinstance(data.get("template"), dict) else None
        if llm_query:
            query = llm_query
            via = "llm"
        if llm_title:
            title = llm_title
        if llm_template:
            template = {
                k: str(v)
                for k, v in llm_template.items()
                if k in ("opening", "ending") and v
            } or None
    except Exception as exc:  # noqa: BLE001  兜底路径失败不影响主流程
        logger.opt(exception=True).warning("query understanding fail: {}", str(exc)[:60])

    tags = match_tags(query)
    return TopicIntent(tags=tags[:3], query=query, via=via, template=template, title=title)
