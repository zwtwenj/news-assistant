"""播客脚本生成：话题提示词 → Milvus 检索素材 → 回表取正文 → LLM 写新闻播报稿。

设计要点（参考 NotebookLM / Together AI 开源教程）：
- 素材注入：标题 + 打标摘要 + 正文节选（信息量的根基，绝不只给标题）；
- 新闻要素约束：每条新闻必须交代 5W1H 与关键数字，先导语后展开；
- 忠实性：所有事实须出自素材原文（substantiated by the input text）；
- scratchpad：先在 JSON 里梳理各条新闻要素，再写口播稿（信息密度核心手段）；
- 时长驱动：素材上限按时长档位（短1/中3/长5），下限恒为 1，0 条才拒绝。
"""

import json
import time
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.article import Article
from app.services.llm.gateway import gateway
from app.services.news import vector as vector_svc
from app.services.podcast import voices as voices_svc
from app.services.podcast.query_understanding import understand_topic

# 脚本生成用中档模型（flash 级写新闻信息组织偏弱）；打标仍用 deepseek-v4-flash
SCRIPT_PROVIDER = "dashscope"
SCRIPT_MODEL = "qwen-plus"
SEARCH_DAYS = 7
MIN_SCORE = 0.25  # 检索分数下限：全低于此 = 库里没有相关内容
CONTENT_EXCERPT = 2000  # 每条素材注入的正文节选字数（新闻导语/背景常在文中后段，不宜截太狠）

# 页面噪音黑名单：trafilatura 抽取的正文仍可能混入导航/页脚行，注入前过滤
_NOISE_KEYWORDS = (
    "新闻频道", "点击收起", "扫一扫", "返回", "正在加载", "责任编辑", "编辑：",
    "分享到", "原标题", "最新推荐", "加载中", "首页", "客户端", "热线", "版权",
)


def _clean_content(text: str) -> str:
    """行级噪音过滤：丢弃短行、邮箱行、"来源 | 日期"行与含导航/页脚关键词的行。"""
    import re

    lines = []
    for line in text.splitlines():
        s = line.strip()
        if len(s) < 6 or "@" in s:
            continue
        if re.search(r"\|\s*20\d\d年", s):  # 来源/日期重复行
            continue
        if any(k in s for k in _NOISE_KEYWORDS):
            continue
        lines.append(s)
    return "\n".join(lines)[:CONTENT_EXCERPT]

SINGLE_PROMPT = """你是资深新闻节目撰稿人，为早间新闻电台写一期约 {minutes} 分钟的单人口播稿。

【风格与写法要求（脚本提示词）】
{script_prompt}

【本期主题（话题提示词）】
{topic_prompt}

【新闻素材】（全部事实必须出自以下素材，不得编造数字、引语或情节；素材不足预期就对已有内容深入展开，不要硬凑）
{materials}

写作规则（按顺序思考并执行）：
1. 先在 scratchpad 里逐条梳理新闻要素：
   ①事件本身——发生了什么事、在哪里、何时、影响谁（这是一条新闻的主体）；
   ②关键数字与结果；③各方行动与反应（救援/表态/措施）；
   ④为什么重要。缺要素就回素材里找，找不到不写；
2. 主次原则：先讲事件背景，再讲行动——听众必须先知道"发生了什么"，
   才能理解"谁在做什么、为什么做"。绝不能脱离事件空谈行动；
3. 口播稿结构：开场（"为您播报 N 条新闻"）→ 每条新闻先一句话导语
   （听完导语就知道发生了什么）→ 再展开细节与背景 → 收尾总结；
4. 信息优先：口语化是"怎么说"，不能牺牲"说什么"——
   每个段落必须让听众获得具体事实，禁止空泛的感慨和过渡；
5. 全长 {words_min}~{words_max} 字（语速约 280 字/分钟），
   切分为 {seg_min}~{seg_max} 个自然段落，每段一个完整意思；
6. 只输出 JSON：{{"scratchpad": "各条新闻要素梳理", "segments": [{{"text": "段落内容"}}]}}"""

DUAL_PROMPT = """你是资深新闻节目撰稿人，为一期约 {minutes} 分钟的双人新闻对谈写对话稿。

【主持人 A 人设与写法（脚本提示词A）】
{script_prompt_a}

【主持人 B 人设与写法（脚本提示词B）】
{script_prompt_b}

【本期主题（话题提示词）】
{topic_prompt}

【新闻素材】（全部事实必须出自以下素材，不得编造数字、引语或情节；素材不足预期就深聊已有内容，不要硬凑）
{materials}

写作规则：
1. 先在 scratchpad 里逐条梳理新闻要素：
   谁、何时、何地、发生了什么、关键数字/结果、为什么重要；
2. A/B 对话：主播负责播报事实（导语+关键细节），搭档负责追问、确认和补充背景——
   提问必须指向具体信息，不问空泛问题；
3. 信息优先：每轮对话都要让听众获得具体事实，禁止空转的寒暄与感慨；
4. 共 {turns_min}~{turns_max} 轮，每句不超过 100 字，总量约 {minutes} 分钟（语速约 280 字/分钟）；
5. speaker 只能是 "A" 或 "B"——注意 A/B 仅是分段标记，不是名字：
   口播文本中禁止出现"A"或"B"字样，互相称呼用"主播""老师"等自然称呼或不称呼；
6. 只输出 JSON：{{"scratchpad": "要素梳理",
   "segments": [{{"speaker": "A", "text": "..."}}]}}"""


# 实测语速校准（含标点与段间静音，三单实测 265~289 字/分钟，取保守上沿）
CHARS_PER_MINUTE = 280


def _plan(target_minutes: int) -> dict[str, Any]:
    """时长 → 检索上限与脚本长度区间。素材下限恒为 1（不足则深聊）。

    字数 = 目标分钟 × 280，再留 ~18% 余量（LLM 普遍写不够字数，宁长勿短）。
    """
    if target_minutes <= 2:  # 短（1~2 分钟）
        return {"top_k": 1, "words": (550, 750), "segs": (4, 6), "turns": (10, 14)}
    if target_minutes <= 5:  # 中（3~5 分钟）
        return {"top_k": 3, "words": (1150, 1500), "segs": (7, 10), "turns": (20, 28)}
    # 长（5~8 分钟）
    return {"top_k": 5, "words": (1900, 2400), "segs": (12, 16), "turns": (34, 44)}


# 话题→标签映射已迁移至 query_understanding.py（两层 query 理解）


def _search_materials(topic: str, top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """检索素材（三段式）：query 理解 → 多路召回 → rerank 精排。

    ① understand_topic：规则抽 tags（"国际新闻"→[国际]）+ 清洗任务词；未命中走 LLM 兜底
    ② 召回：tags 过滤的向量检索 top_k×3（无命中降级纯语义），阈值过滤
    ③ gte-rerank-v2 精排：精排分降序为主（语义相关优先），新鲜度作次级排序
    返回 (命中列表 ≤ top_k+2 备选, 意图摘要)；0 命中由调用方拒绝。
    """
    intent = understand_topic(topic)
    week_ago = int(time.time()) - SEARCH_DAYS * 86400
    recall_k = top_k * 3

    def _recall(tags_any: list[str] | None) -> list[dict[str, Any]]:
        hits = vector_svc.search(
            intent.query, top_k=recall_k, publish_after_ts=week_ago, tags_any=tags_any
        )
        return [h for h in hits if h["score"] >= MIN_SCORE]

    candidates = _recall(intent.tags or None)
    if intent.tags and not candidates:  # 类别无命中 → 降级纯语义
        logger.info("话题类别 {} 无命中，降级纯语义检索", intent.tags)
        candidates = _recall(None)
    if not candidates:
        return [], {"tags": intent.tags, "query": intent.query, "via": intent.via}

    reranked = vector_svc.rerank(intent.query, candidates)
    # 精排分为主、新鲜度为辅（相关优先，7 天窗口已保证时效下限）
    reranked.sort(
        key=lambda h: (h.get("rerank_score") or 0, h["publish_ts"]), reverse=True
    )
    intent_summary = {
        "tags": intent.tags, "query": intent.query, "via": intent.via,
        "recalled": len(candidates),
    }
    return reranked[: top_k + 2], intent_summary


def _load_material_text(hits: list[dict[str, Any]], top_k: int) -> str:
    """回表 PG 组装素材文本：标题+来源+时间+摘要+正文节选。

    正文清洗后 <80 字的素材视为"正文缺失"，跳过由备选补位（垃圾正文只会误导
    LLM 对着标题想象）；全部垃圾时保留标题+摘要并以（正文缺失）标注。
    """
    ids = [h["article_id"] for h in hits]
    with SessionLocal() as db:
        rows = db.execute(select(Article).where(Article.id.in_(ids))).scalars().all()
        by_id = {a.id: a for a in rows}

    usable: list[dict[str, Any]] = []  # (article, cleaned_content)
    for h in hits:
        a = by_id.get(h["article_id"])
        if a is None:
            continue
        cleaned = _clean_content(a.content)
        if len(cleaned) >= 80:
            usable.append({"a": a, "content": cleaned})
        if len(usable) >= top_k:
            break

    from datetime import UTC

    blocks = []
    for item in usable:
        a = item["a"]
        pub = a.publish_time.astimezone(UTC).strftime("%m-%d %H:%M") if a.publish_time else ""
        blocks.append(
            f"【素材{len(blocks) + 1}】《{a.title}》\n"
            f"来源：{a.source} ｜ 发布：{pub} ｜ 标签：{'/'.join(a.tags or [])}\n"
            f"摘要：{a.summary or '（无）'}\n"
            f"正文：{item['content']}\n"
        )
    if not blocks:
        # 全部素材正文缺失：退回第一条，只用标题+摘要并如实标注
        a = by_id.get(hits[0]["article_id"]) if hits else None
        if a is not None:
            blocks.append(
                f"【素材1】《{a.title}》\n"
                f"来源：{a.source} ｜ 标签：{'/'.join(a.tags or [])}\n"
                f"摘要：{a.summary or '（无）'}\n"
                f"正文：（缺失，仅凭标题与摘要，切勿虚构细节）\n"
            )
    return "\n".join(blocks)


def generate_script(
    mode: str,
    topic_prompt: str,
    script_prompt: str | None,
    script_prompt_a: str | None,
    script_prompt_b: str | None,
    target_minutes: int = 4,
) -> dict[str, Any]:
    """返回 {"segments": [...], "materials": [命中清单], "intent": 检索意图}。

    素材为 0 或输出非法时抛 ScriptError（任务层计失败）。
    """
    plan = _plan(target_minutes)
    hits, intent = _search_materials(topic_prompt, plan["top_k"])
    if not hits:
        raise ScriptError("素材不足，无法为你生成播客：近期新闻库中没有与话题相关的内容")

    materials = _load_material_text(hits, plan["top_k"])
    # 素材命中清单（结构化，落库 + Langfuse，回答"这期引用了哪些新闻"）
    materials_detail = [
        {
            "article_id": h["article_id"],
            "title": h["title"][:60],
            "tags": h.get("tags") or [],
            "recall_score": round(h["score"], 3),
            "rerank_score": round(h.get("rerank_score") or 0, 3),
        }
        for h in hits[: plan["top_k"]]
    ]
    common = {
        "minutes": target_minutes,
        "topic_prompt": topic_prompt,
        "materials": materials,
    }
    if mode == "single":
        prompt = SINGLE_PROMPT.format(
            script_prompt=script_prompt,
            words_min=plan["words"][0],
            words_max=plan["words"][1],
            seg_min=plan["segs"][0],
            seg_max=plan["segs"][1],
            **common,
        )
    else:
        prompt = DUAL_PROMPT.format(
            script_prompt_a=script_prompt_a,
            script_prompt_b=script_prompt_b,
            turns_min=plan["turns"][0],
            turns_max=plan["turns"][1],
            **common,
        )

    last_err: Exception | None = None
    words_min, words_max = plan["words"]
    feedback = ""  # 字数不足时的定向扩写反馈（比抽象的字数要求有效）
    for attempt in range(2):
        try:
            resp = gateway.chat(
                SCRIPT_PROVIDER,
                model=SCRIPT_MODEL,
                messages=[{"role": "user", "content": prompt + feedback}],
                response_format={"type": "json_object"},
                max_tokens=4500,
                temperature=0.7,
                langfuse_meta={
                    "podcast": True, "mode": mode,
                    "topic": topic_prompt[:50], "target_minutes": target_minutes,
                    "attempt": attempt,
                    "intent": intent, "materials_detail": materials_detail,
                },
            )
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                raise ValueError("LLM 返回空内容")
            segments = _validate(json.loads(raw), mode)
            total_chars = sum(len(s["text"]) for s in segments)
            if total_chars < words_min * 0.85 and attempt == 0:
                feedback = (
                    f"\n\n【重要：上一稿仅 {total_chars} 字，太短】"
                    f"必须扩写到 {words_min}~{words_max} 字："
                    "对素材展开更多细节、背景、追问与回应，禁止注水或重复表述。"
                )
                logger.info("script too short ({}/{}), retry with feedback", total_chars, words_min)
                continue
            if total_chars < words_min * 0.85:
                logger.warning("script still short after retry: {}/{}", total_chars, words_min)
            logger.info("script ok: {} 段 {} 字（目标 {}~{}）", len(segments), total_chars,
                        words_min, words_max)
            return {"segments": segments, "materials": materials_detail, "intent": intent}
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("script attempt fail: {}: {}", exc.__class__.__name__, str(exc)[:80])
    raise ScriptError(f"脚本生成失败：{last_err}")


def _validate(data: dict, mode: str) -> list[dict[str, Any]]:
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("segments 缺失或为空")
    out: list[dict[str, Any]] = []
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if not text or len(text) > 800:
            raise ValueError("分段文本为空或过长")
        if mode == "dual":
            speaker = str(seg.get("speaker", "")).strip().upper()
            if speaker not in ("A", "B"):
                raise ValueError(f"非法 speaker: {speaker}")
            out.append({"speaker": speaker, "text": text})
        else:
            out.append({"text": text})
    if len(out) < 3:
        raise ValueError("分段过少")
    return out


class ScriptError(Exception):
    """业务性失败（素材不足等），message 直接展示给用户。"""


def speaker_voice_map(voice_a: str, voice_b: str | None) -> dict[str, str]:
    """脚本 speaker/单人 → 实际音色 ID 的映射。"""
    if voice_b:
        return {"A": voice_a, "B": voice_b, "single": voice_a}
    return {"single": voice_a, "A": voice_a}


def describe_voices(voice_a: str, voice_b: str | None) -> str:
    if voice_b:
        return f"A={voices_svc.voice_name(voice_a)}，B={voices_svc.voice_name(voice_b)}"
    return voices_svc.voice_name(voice_a)
