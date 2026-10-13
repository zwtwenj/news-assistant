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

LLM_PROMPT = """用户想生成一期新闻播客，给出话题描述。

**第一步：判断话题是否可用（valid）**
- 乱码、纯符号、纯数字、空白、无意义的字符组合，或完全无法理解想聊什么 → valid = false
- 能理解其想聊什么（即使口语化、含糊、带错别字）→ valid = true

若 valid = false，只输出：{{"valid": false, "reason": "为什么不可用，15字内"}}

若 valid = true，继续做三件事：
1. 起一个播客标题（title）：8~20 字，概括核心主题，吸引人但不夸张，
   不含"生成/一期/播客"等任务词，不含开场白结束语；
2. 把话题改写成适合新闻检索的语义 query（rag_query）：去掉"生成/一份/播客"等
   任务性词汇和开场白/结束语要求，围绕核心主题补充同义关键词（如天气话题可补充
   "降雨 台风 气象预警 天气预报"），输出 10~30 字；
3. 若话题明确要求了开场白/结束语话术，逐字提取到 template（保持原文一字不改）；
   没有就输出 null。

只输出 JSON：{{"valid": true, "title": "...", "rag_query": "...",
 "template": {{"opening": "开场白原文", "ending": "结束语原文"}} 或 null}}

话题：{topic}{feedback}"""

# 改写自检循环上限：3 次仍不通过 → 拒绝并提示用户重新描述
MAX_REWRITE_ATTEMPTS = 3


class TopicInvalidError(Exception):
    """话题不可用（乱码/无意义/无法理解）——message 直接展示给用户。"""


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
    """LLM 改写 + 自检循环：最多 3 次，全不通过则抛 TopicInvalidError。

    自检内容：输入是否可理解、改写是否忠实原意（LLM 同时输出 valid + reason）。
    不通过时带上反馈重试（首次失败多因判断抖动，反馈能显著提高第二次通过率）；
    三次仍不通过 → 抛错，由创建端点转 422 提示用户重新描述。
    LLM 调用本身异常时回退原话题（不阻断主流程）。
    """
    from app.services.news.vocabulary import match_tags

    feedback = ""
    last_reason = ""
    for attempt in range(1, MAX_REWRITE_ATTEMPTS + 1):
        data: dict = {}
        try:
            resp = gateway.chat(
                "zhipu",
                messages=[{"role": "user", "content": LLM_PROMPT.format(
                    topic=topic, feedback=feedback)}],
                response_format={"type": "json_object"},
                max_tokens=400,
                temperature=0.0,
                langfuse_meta={"query_understanding": True, "topic": topic[:50],
                               "attempt": attempt},
            )
            data = json.loads((resp.choices[0].message.content or "").strip() or "{}")
        except Exception as exc:  # noqa: BLE001  兜底：回退原话题，不阻断主流程
            logger.opt(exception=True).warning("query understanding fail: {}", str(exc)[:60])
            break

        # 自检不通过 → 带反馈重试
        if data.get("valid") is False:
            last_reason = str(data.get("reason") or "").strip()[:40]
            logger.info("query 自检不通过（第 {} 次）：{}", attempt, last_reason)
            feedback = (
                f"\n\n【上一次自检未通过】原因：{last_reason}。"
                f"请重新判断：若话题确实可理解，必须给出忠实于用户原意的改写；"
                f"若确实是乱码/无意义内容，保持 valid=false。"
            )
            continue

        llm_query = str(data.get("rag_query") or "").strip()[:60]
        if not llm_query:  # 改写为空也算不通过，重试
            last_reason = "改写结果为空"
            feedback = "\n\n【上一次改写为空】请必须输出 rag_query。"
            continue

        title = str(data.get("title") or "").strip()[:50] or None
        raw_template = data.get("template")
        template = None
        if isinstance(raw_template, dict):
            template = {k: str(v) for k, v in raw_template.items()
                        if k in ("opening", "ending") and v} or None
        tags = match_tags(llm_query)
        return TopicIntent(tags=tags[:3], query=llm_query, via="llm",
                           template=template, title=title)

    if last_reason:  # 自检三次不通过 → 拒绝
        raise TopicInvalidError(last_reason)
    # LLM 调用异常 → 回退原话题（fail-open，不误伤正常话题）
    tags = match_tags(topic)
    return TopicIntent(tags=tags[:3], query=topic, via="raw", template=None, title=None)
