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
from app.services.podcast.query_understanding import TopicIntent, understand_topic

# 脚本生成用中档模型（flash 级写新闻信息组织偏弱）；打标仍用 deepseek-v4-flash
SCRIPT_PROVIDER = "dashscope"
SCRIPT_MODEL = "qwen-plus"
SEARCH_DAYS = 7
MIN_SCORE = 0.15  # 检索分数下限（rerank 对泛 query 打分保守，粗筛放宽交给精排排序）
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

【主播身份】
你就是在为「{host_name}」写口播稿——以下是 TA 的人设，稿件语气要贴合这个人设。

【风格与写法要求（脚本提示词）】
{script_prompt}

【本期节目与主题】
节目名称：《{podcast_title}》（开场可自然点题，但不要生硬念出节目名）
本期主题（话题提示词）：{topic_prompt}

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

DUAL_PROMPT = """你是资深播客导演，为一期约 {minutes} 分钟的双人新闻对谈节目写对话稿。

【主持人身份】
主持人 A 是「{host_a_name}」，主持人 B 是「{host_b_name}」——以下是两人的人设，对话语气要各自贴合。

【主持人 A 人设与写法（脚本提示词A）】
{script_prompt_a}

【主持人 B 人设与写法（脚本提示词B）】
{script_prompt_b}

【本期节目与主题】
节目名称：《{podcast_title}》（开场可自然点题，但不要生硬念出节目名）
本期主题（话题提示词）：{topic_prompt}

【新闻素材】（全部事实必须出自以下素材，不得编造数字、引语或情节；素材不足预期就深聊已有内容，不要硬凑）
{materials}

写作规则（按顺序思考并执行）：

1. 先在 scratchpad 里梳理：①新闻要素（谁/何时/何地/什么事/数字/为什么重要）；
   ②对话设计——哪些信息由 A 抛出、哪些由 B 追问出来、哪些用来制造反应。

2. 对话感核心（最重要的规则）：
   - 两位主持人都是"活人"，不是播报员和提问机器——
     A 可以补充 B 没说完的细节，B 可以打断 A 表达惊讶，两人可以互相纠正；
   - 听到数字时要有反应（"这个数比上季度翻了一倍？"），
     听到结论时要有追问（"为什么选这个时候？"），
     听到对比时要有连接（"这不就跟上次那个情况很像吗"）；
   - 允许自然的口语化反应：对、嗯、其实、你知道吗、等等——
     这些不是废话，是让听众觉得"两个人真的在聊天"的关键。

3. 追问技巧（搭档不是复读机）：
   - 好的追问指向具体信息："具体降了多少？""受影响的有多少人？"
   - 更好的追问引导深入："这个政策对普通租房者有什么实际影响？"
   - 禁止空泛问题："你觉得怎么样？""能详细说说吗？"——这些不用出现。

4. 衔接技巧（话题转换不能生硬）：
   - 用内容搭桥："说到这个政策，另一条新闻正好也提到了相关的影响"
   - 用对比搭桥："刚才说的是好的一面，但另一边的情况就不太乐观了"
   - 禁止"接下来我们来看下一条新闻"这种节目单式过渡。

5. 忠实度约束（不可违反）：
   - 所有数字、人名、事件、结论必须出自素材；
   - 素材没提的不要编；对素材的合理解读和情感反应不算编造；
   - 如果素材不足以支撑完整讨论，就深挖已有内容，不要硬凑。

6. 结构与长度：
   - 共 {turns_min}~{turns_max} 轮对话，每句不超过 100 字；
   - 总量约 {words_min}~{words_max} 字（语速约 280 字/分钟）；
   - 开场：A 或 B 用一句自然的引入（不要念节目名）；
   - 收尾：两人各一句简短的收束感言，不生硬。

7. speaker 只能是 "A" 或 "B"——A/B 仅是分段标记：
   口播文本中禁止出现"A"或"B"字样，互相称呼用名字（{host_a_name}/{host_b_name}）或自然称呼。

8. 只输出 JSON：{{"scratchpad": "要素梳理+对话设计",
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


_RELEVANCE_PROMPT = """你是新闻编辑，判断检索到的新闻素材能否支撑用户话题的播客生成。

用户话题：{topic}

检索到的素材（标题列表）：
{titles}

判断标准（从严）：
- "sufficient"：至少 1 篇素材直接讨论了话题提到的同一事件/政策/人物/领域
- "partial"：素材讨论的话题与用户话题有明确交集（如同一政策的不同方面、同一行业的不同事件），
  播客可以围绕交集内容展开
- "reject"：素材只是同类目/同大类，没有讨论用户话题的具体内容——
  例如用户问"量子纠缠"，检索到的是一般科技新闻；用户问"台风摩羯"，检索到的是气象政策

注意：仅仅"都属于科技领域"或"都是国内新闻"不构成 partial——必须有内容层面的交集。

只输出 JSON：{{"verdict": "sufficient/partial/reject", "reason": "15字内"}}"""


def _check_material_relevance(topic: str, hits: list[dict[str, Any]]) -> str:
    """相关性门禁：LLM 判断素材能否支撑话题。

    返回 sufficient/partial/reject；reject 由调用方阻断生成。
    失败默认 sufficient（不挡主流程——门禁自身不能成为单点故障）。
    """
    if not hits:
        return "reject"
    titles = "\n".join(f"- 《{h.get('title', '')[:50]}》" for h in hits[:5])
    try:
        resp = gateway.chat(
            "zhipu",
            messages=[{"role": "user", "content": _RELEVANCE_PROMPT.format(
                topic=topic, titles=titles)}],
            response_format={"type": "json_object"},
            max_tokens=50,
            temperature=0.0,
        )
        raw = json.loads(resp.choices[0].message.content or "{}")
        verdict = str(raw.get("verdict", "")).lower()
        return verdict if verdict in ("sufficient", "partial", "reject") else "sufficient"
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("相关性门禁失败，默认放行")
        return "sufficient"


def _hyde_doc(topic: str) -> str | None:
    """HyDE：让 LLM 写一段假设性新闻导语（新闻体语言域），作为第二检索 query。

    实验（eval/eval_hyde.py）：单用伤排序、融合提召回（miss 6→2），只做副路。
    失败返回 None 不影响主路。
    """
    try:
        resp = gateway.chat(
            "zhipu",
            messages=[{"role": "user", "content": (
                "你是新闻编辑。根据话题写一段【假设存在的新闻导语】，模仿大陆时政/财经通讯社"
                "风格（新华社腔调），120~180 字，含具体事实要素（谁/领域/动作/数字量级，"
                "可合理虚构）。只输出导语正文。\n\n话题：" + topic
            )}],
            max_tokens=300,
            temperature=0.3,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("HyDE 生成失败，走单 query 检索")
        return None


def _search_materials(
    topic: str, top_k: int, intent: TopicIntent | None = None
) -> tuple[list[dict[str, Any]], TopicIntent]:
    """检索素材（2026-09 重构 v2：统一 hybrid，去掉类目过滤）。

    ① intent 仍由创建流程产出（template 脚本风格路由保留）
    ② 全部 query 统一走 hybrid（dense+BM25 加权融合）：原始 topic + HyDE 副路
       —— 类目过滤已移除：实验证明类目排除相关文章（航班归气象导致"国际航班"
       query 找不到航班新闻），hybrid 全库搜索覆盖率更高
    返回 (命中列表 ≤ top_k+2 备选, 完整 TopicIntent)；0 命中由调用方拒绝。
    """
    if intent is None:
        intent = understand_topic(topic)
    week_ago = int(time.time()) - SEARCH_DAYS * 86400
    recall_k = top_k * 4

    queries = _hyde_doc(topic)
    hits = vector_svc.hybrid_search(
        topic, top_k=recall_k, publish_after_ts=week_ago,
        extra_queries=[queries] if queries else None,
    )
    hits = [h for h in hits if h["score"] >= MIN_SCORE]
    logger.info("具体型 hybrid 检索（{}query）命中 {}", 2 if queries else 1, len(hits))
    if not hits:
        return [], intent

    reranked = vector_svc.rerank(topic, hits)
    # 精排分为主、新鲜度为辅（相关优先，7 天窗口已保证时效下限）
    reranked.sort(
        key=lambda h: (h.get("rerank_score") or 0, h["publish_ts"]), reverse=True
    )
    return reranked[: top_k + 2], intent


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


def _template_block(template: dict | None) -> str:
    """模板句 → 脚本硬约束块（query 重写 template 节点：开场白/结束语逐字使用）。"""
    if not template:
        return ""
    lines = []
    if template.get("opening"):
        lines.append(
            f"【开场白（硬约束）】全篇第一句话必须逐字使用：「{template['opening']}」，"
            "不得改写、翻译或合并到其他句子。"
        )
    if template.get("ending"):
        lines.append(
            f"【结束语（硬约束）】全篇必须以这句话收尾，逐字使用：「{template['ending']}」"
        )
    return "\n".join(lines) + "\n\n" if lines else ""


def generate_script(
    mode: str,
    topic_prompt: str,
    script_prompt: str | None,
    script_prompt_a: str | None,
    script_prompt_b: str | None,
    target_minutes: int = 4,
    host_names: list[str] | None = None,
    podcast_title: str | None = None,
    query_rewrite: dict | None = None,
) -> dict[str, Any]:
    """返回 {"segments": [...], "materials": [命中清单], "intent": 检索意图}。

    host_names：主播名字快照（单人为 [A名]，双人为 [A名, B名]）——注入 prompt
    让 LLM 知道在为谁写稿（语气贴合人设、双人可用名字互称）。
    podcast_title：query 重写生成的节目名（开场点题用）。
    素材为 0 或输出非法时抛 ScriptError（任务层计失败）。
    """
    plan = _plan(target_minutes)
    # 创建流程已重写（title/rag_query/template 在库），重建 intent 复用；旧数据 None 则内部重写
    intent_in = (
        TopicIntent(
            tags=(query_rewrite or {}).get("tags") or [],
            query=(query_rewrite or {}).get("rag_query") or topic_prompt,
            via=(query_rewrite or {}).get("via") or "raw",
            template=(query_rewrite or {}).get("template"),
            title=(query_rewrite or {}).get("title"),
        )
        if query_rewrite
        else None
    )
    hits, intent = _search_materials(topic_prompt, plan["top_k"], intent=intent_in)
    if not hits:
        raise ScriptError("素材不足，无法为你生成播客：近期新闻库中没有与话题相关的内容")

    # ── 相关性门禁：素材"在题"≠"相关"，LLM 判断能否支撑话题 ──
    relevance = _check_material_relevance(topic_prompt, hits[: plan["top_k"]])
    if relevance == "reject":
        raise ScriptError(
            f"新闻库暂无与「{topic_prompt[:20]}」直接相关的报道，"
            "建议换个话题或等更多相关新闻入库后再试"
        )
    # partial 时不阻断，但在素材块前加提醒（LLM 会自然告知听众素材范围有限）

    template_block = _template_block(intent.template)

    materials = _load_material_text(hits, plan["top_k"])
    # 素材命中清单（结构化，落库 + Langfuse，回答"这期引用了哪些新闻"）
    materials_detail = [
        {
            "article_id": h["article_id"],
            "title": h["title"][:60],
            "category": h.get("category"),
            "recall_score": round(h["score"], 3),
            "rerank_score": round(h.get("rerank_score") or 0, 3),
        }
        for h in hits[: plan["top_k"]]
    ]
    names = host_names or []
    common = {
        "minutes": target_minutes,
        "topic_prompt": topic_prompt,
        "materials": materials,
        "podcast_title": podcast_title or topic_prompt[:20],
        "host_name": names[0] if names else "新闻主播",
        "host_a_name": names[0] if names else "主持人A",
        "host_b_name": names[1] if len(names) > 1 else "主持人B",
    }
    if mode == "single":
        prompt = template_block + SINGLE_PROMPT.format(
            script_prompt=script_prompt,
            words_min=plan["words"][0],
            words_max=plan["words"][1],
            seg_min=plan["segs"][0],
            seg_max=plan["segs"][1],
            **common,
        )
    else:
        prompt = template_block + DUAL_PROMPT.format(
            script_prompt_a=script_prompt_a,
            script_prompt_b=script_prompt_b,
            words_min=plan["words"][0],
            words_max=plan["words"][1],
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
                    "intent": intent.to_dict(), "materials_detail": materials_detail,
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
            return {"segments": segments, "materials": materials_detail,
                    "intent": intent.to_dict()}
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
