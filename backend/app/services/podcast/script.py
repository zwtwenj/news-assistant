"""播客脚本生成：话题提示词 → Milvus 检索素材 → 回表取正文 → LLM 写新闻播报稿。

设计要点（参考 NotebookLM / Together AI 开源教程）：
- 素材注入：标题 + 打标摘要 + 正文节选（信息量的根基，绝不只给标题）；
- 新闻要素约束：每条新闻必须交代 5W1H 与关键数字，先导语后展开；
- 忠实性：所有事实须出自素材原文（substantiated by the input text）；
- scratchpad：先在 JSON 里梳理各条新闻要素，再写口播稿（信息密度核心手段）；
- 时长驱动：素材上限按时长档位（短1/中3/长5），下限恒为 1，0 条才拒绝。
"""

import json
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.article import Article
from app.services.llm.gateway import gateway
from app.services.news import simhash as simhash_svc
from app.services.news import vector as vector_svc
from app.services.news.categories import detect_macro
from app.services.podcast import voices as voices_svc
from app.services.podcast.query_understanding import TopicIntent, understand_topic

# 生成/改写/抽卡统一用 zhipu 付费档 glm-4.5-air：免费 glm-4-flash 尾延迟 55s+
# 曾把 60s 超时打爆；关思考避免输出预算被推理 token 挤占（实测 540→169 tokens）
SCRIPT_PROVIDER = "zhipu"
SCRIPT_MODEL = "glm-4.5-air"
SCRIPT_MAX_TOKENS = 8000
_THINKING_OFF = {"thinking": {"type": "disabled"}}
SEARCH_DAYS = 7
RERANK_MIN_SCORE = 0.25  # rerank 阀门：低于直接丢弃（垃圾地板，非好差分界）
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
5. 全长不超过 {words_max} 字（语速约 280 字/分钟），
   切分为 {seg_min}~{seg_max} 个自然段落，每段一个完整意思；
   把素材讲透、讲完自然收尾——不硬凑字数；
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
   - 总量不超过 {words_max} 字（语速约 280 字/分钟），讲透即收，不硬凑；
   - 开场：A 或 B 用一句自然的引入（不要念节目名）；
   - 收尾：两人各一句简短的收束感言，不生硬。

7. speaker 只能是 "A" 或 "B"——A/B 仅是分段标记：
   口播文本中禁止出现"A"或"B"字样，互相称呼用名字（{host_a_name}/{host_b_name}）或自然称呼。

8. 只输出 JSON：{{"scratchpad": "要素梳理+对话设计",
   "segments": [{{"speaker": "A", "text": "..."}}]}}"""


# 实测语速校准（含标点与段间静音，三单实测 265~289 字/分钟，取保守上沿）
CHARS_PER_MINUTE = 280


def _plan(target_minutes: int) -> dict[str, Any]:
    """时长 → 检索上限与脚本字数上限。素材下限恒为 1（不足则深聊）。

    字数只设上限、不设下限（2026-09-29：写手不再被要求凑字数——
    素材密度不足时凑字数只会催生编造；上限沿用原区间上沿，中篇 1800）。
    """
    if target_minutes <= 2:  # 短（1~2 分钟）
        return {"top_k": 1, "words": (0, 750), "segs": (4, 6), "turns": (10, 14)}
    if target_minutes <= 5:  # 中（3~5 分钟）
        return {"top_k": 5, "words": (0, 1800), "segs": (7, 10), "turns": (20, 28)}
    # 长（5~8 分钟）
    return {"top_k": 5, "words": (0, 2400), "segs": (12, 16), "turns": (34, 44)}


# 话题→标签映射已迁移至 query_understanding.py（两层 query 理解）


# ── Self-Refine 质量循环（仅单人口播启用）──
#
# 数据链契约：评审是 (topic, materials, script) 的纯函数——materials 必须是
# 生成时检索并冻结的那份素材正文，评审与改写环节一律不做任何检索；
# 素材与脚本全文送审，不做任何截断。生产 Self-Refine 与离线评测共用 _ds_evaluate。

_DS_EVAL_MODEL = "deepseek-flash"

# Self-Refine：评审→重写循环两轮（评 v1、评 v2），写手最多三版
# （v3 为评②不合格后的终版盲写，质量由回归复评把关——退化即回退 v2）
REFINE_MAX_ROUNDS = 2

_DIM_LABELS = {
    "relevance": "相关性",
    "faithfulness": "事实忠实度",
    "completeness": "信息完整度",
    "readability": "口播可读性",
    "utilization": "素材利用率",
}


def _today_str() -> str:
    """当前日期（含星期）：日期由系统注入，生成与评审共用，禁止模型自编。"""
    t = time.localtime()
    return f"{time.strftime('%Y年%m月%d日', t)}（{'一二三四五六日'[t.tm_wday]}）"


def _ds_evaluate(
    topic: str, materials: str, script_text: str, today: str = "",
    cards: str = "",
) -> dict:
    """DeepSeek 评审单人口播稿（4 维 + 有事实卡时加素材利用率），返回 {维度: {score, reason}}。"""
    s = get_settings()
    ds_url = s.deepseek_base_url.rstrip("/") + "/chat/completions"
    n_mat = len(set(re.findall(r"【素材\d+】", materials)))
    thin_note = (
        f"本次素材共 {n_mat} 篇，低于 5 篇：脚本篇幅与信息量受素材所限，"
        "只评素材所含关键信息是否被脚本覆盖，不要因篇幅短、信息密度低而扣分"
        if n_mat < 5
        else ""
    )
    date_note = (
        f"【节目播出日期】{today}——脚本以「今天」「昨日」等指代日期时以此为准，不计无源。\n"
        if today
        else ""
    )
    prompts = {
        "relevance": (
            f"你是播客听众。以下是为话题「{topic}」检索到的新闻素材标题：\n\n"
            + "\n".join(f"- {ln.strip()}" for ln in materials.splitlines() if ln.startswith("【"))
            + "\n\n素材与话题的关联度 1~5。5=至少一篇直接讨论话题核心事件；"
              "3=同类目但角度不同；1=仅大类沾边。"
            + '只输出 JSON：{"score": 1~5, "reason": "15字内"}'
        ),
        "faithfulness": (
            "你是事实核查员。只核查【事实性陈述】：数字、日期、人名、机构、政策名、"
            "比例、对比、因果断言是否能在素材中找到出处。\n"
            "【口径钉死】评论性、展望性、祝愿性表述（如「迈上新台阶」「前景广阔」"
            "「让我们共同努力」）属于播音话术，不属事实核查范围，不得因此扣分；"
            "但假借他人之口的引语必须有出处。\n"
            + date_note
            + f"\n素材正文：\n{materials}\n\n脚本：\n{script_text}\n\n"
            "打分 1~5：5=全部事实性陈述可溯源；4=个别修饰性说法无源但不影响主体；"
            "3=有1~2处无源或与素材相悖；2=多处无源；1=大面积编造。"
            '只输出 JSON：{"score": 1~5, "reason": "列出无源的具体说法，60字内"}'
        ),
        "completeness": (
            f"你是播客听众。话题「{topic}」的脚本是否覆盖了关键信息，打分 1~5。\n\n"
            f"脚本：\n{script_text}\n\n"
            f"素材量参考：共 {n_mat} 篇。{thin_note}\n"
            "【篇幅长短不作为评分因素】只看素材所含关键信息是否被脚本覆盖。\n"
            "5=素材与话题的关键信息全覆盖；3=覆盖一半左右；1=只用了极小部分。"
            '只输出 JSON：{"score": 1~5, "reason": "15字内"}'
        ),
        "readability": (
            "你是新闻电台制作人。这是一篇【单人口播稿】，由一位主持人独立播报，"
            "不是双人对谈——用口播稿标准评，不要用对谈标准。看：结构清晰"
            "（导语→细节→收尾）、口语自然不念稿、节奏适中；"
            "【篇幅长短不作为评分因素】。\n\n"
            f"脚本：\n{script_text}\n\n"
            '只输出 JSON：{"score": 1~5, "reason": "15字内"}'
        ),
    }
    if cards:
        prompts["utilization"] = (
            "你是播客主编。以下是撰稿时可用的【事实卡】清单（每卡一个原子事实，"
            "来自检索素材）与据此写成的脚本。请评估【素材利用率】："
            "脚本实质覆盖了多少张卡片的关键信息（数一数被用到的卡；"
            "同一事件的多张卡合并讲述也算覆盖）。\n\n"
            f"事实卡清单：\n{cards}\n\n脚本：\n{script_text}\n\n"
            "打分 1~5：5=绝大部分卡片被实质用到；3=用到一半左右；1=只用极少数卡片。"
            'reason 指出未被使用的关键卡片。只输出 JSON：{"score": 1~5, "reason": "30字内"}'
        )
    scores = {}
    for dim, p in prompts.items():
        try:
            resp = httpx.post(
                ds_url,
                headers={"Authorization": f"Bearer {s.deepseek_api_key}"},
                json={"model": _DS_EVAL_MODEL,
                      "messages": [{"role": "user", "content": p}],
                      "max_tokens": 10000, "temperature": 0.0},
                timeout=90,
            )
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
            for src in (msg.get("content") or "", msg.get("reasoning_content") or ""):
                cl = re.sub(r"```json\s*|```\s*$", "", src.strip(), flags=re.MULTILINE).strip()
                m = re.search(r"\{[^{}]*\}", cl)
                if m:
                    try:
                        parsed = json.loads(m.group())
                        reason = parsed.get("reason") or parsed.get("comment") or ""
                        scores[dim] = {"score": parsed.get("score", 0), "reason": reason}
                        break
                    except json.JSONDecodeError:
                        continue
            else:
                scores[dim] = {"score": 0, "reason": "解析失败"}
        except Exception as exc:  # noqa: BLE001
            scores[dim] = {"score": 0, "reason": str(exc)[:60]}
    return scores


def _llm_json(text: str) -> dict:
    """LLM 输出容错解析为 dict（剥 ```json 围栏）。"""
    cleaned = re.sub(r"```json\s*|```\s*$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_rewrite_segments(text: str) -> str:
    """解析改写输出的 segments JSON（含围栏/转义容错），拼回逐行脚本文本。"""
    data = _llm_json(text)
    segs = data.get("segments")
    if not isinstance(segs, list):
        cleaned = re.sub(r"```json\s*|```\s*$", "", text.strip(), flags=re.MULTILINE).strip()
        segs = []
        for m in re.finditer(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned):
            segs.append({"text": json.loads(f'"{m.group(1)}"')})
    if not isinstance(segs, list):
        raise ValueError("改写输出缺少 segments")
    lines = [str(g.get("text", "")).strip() for g in segs if isinstance(g, dict)]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise ValueError("改写输出为空")
    return "\n".join(lines)


def _self_refine(
    topic: str, materials: str, script_text: str, today: str = "",
    rewrite_evidence: str = "", cards: str = "",
) -> tuple[str, dict]:
    """Self-Refine（仅单人）：LLM 评 → 只改不达标维度 → 退化回退。

    评审→重写循环两轮（评 v1、评 v2），写手最多三版——v3 为评②仍不合格时
    按意见的终版盲写，不再评审（质量由回归复评把关，退化即回退 v2）。
    评审对 materials 全文 + 事实卡（素材利用率维度），改写只认 rewrite_evidence
    （事实卡，缺省回退 materials），全程不检索。
    返回 (终版文本, meta)；meta 含 final_version / checks / improved / passed
    （passed=任一轮全维度≥4，终态路由：合格自动 TTS，不合格交用户决断）。
    """
    current = script_text
    final_version = 1
    check_meta: list[dict] = []

    for check_round in range(1, REFINE_MAX_ROUNDS + 1):
        scores = _ds_evaluate(topic, materials, current, today, cards=cards)
        all_pass = all(v.get("score", 0) >= 4 for v in scores.values())
        check_meta.append({"check": check_round, "all_pass": all_pass, "scores": scores})
        logger.info("Self-Refine check {}: {}", check_round, "PASS" if all_pass else "FAIL")

        if all_pass:
            break
        if any(v.get("score", 0) == 0 for v in scores.values()):
            logger.warning("Self-Refine: 评审调用失败（score=0），终止 refine")
            break
        if check_round >= REFINE_MAX_ROUNDS:
            break  # 已评满 3 轮，当前版本为终版

        failed = {d: v for d, v in scores.items() if v.get("score", 0) < 4}
        passed = [d for d, v in scores.items() if v.get("score", 0) >= 4]
        feedback = "\n".join(
            f"[{_DIM_LABELS.get(d, d)}] {v.get('score', 0)}/5 —— {v.get('reason', '')}"
            for d, v in failed.items()
        )
        preserve = "、".join(_DIM_LABELS.get(d, d) for d in passed)

        prev_script = current
        prev_snap = {d: v.get("score", 0) for d, v in scores.items()}
        try:
            rewrite_prompt = (
                f"你之前写了一篇单人口播稿，评审给出了改进意见：\n\n"
                f"评审意见：\n{feedback}\n\n"
                + (f"以下维度已合格，改写时不要降低这些维度的质量：{preserve}\n\n"
                   if preserve else "")
                + (f"【当前日期】{today}——脚本中的日期表述以此为准，不得更改。\n\n"
                   if today else "")
                + f"你之前写的脚本：\n{current}\n\n"
                f"参考事实（所有事实必须出自这里；其中没有依据的说法，删掉或"
                f"改为实际存在的信息）：\n{rewrite_evidence or materials}\n\n"
                f"只修复评审指出的问题，其余部分保持原样。"
                '只输出 JSON：{"segments": [{"text": "..."}]}'
            )
            resp = gateway.chat(
                SCRIPT_PROVIDER, model=SCRIPT_MODEL,
                messages=[{"role": "user", "content": rewrite_prompt}],
                response_format={"type": "json_object"},
                max_tokens=SCRIPT_MAX_TOKENS, temperature=0.2,
                extra_body=_THINKING_OFF,
                langfuse_meta={"podcast": True, "stage": "self_refine_rewrite",
                               "version": final_version + 1, "topic": topic[:50]},
            )
            new_text = _parse_rewrite_segments(resp.choices[0].message.content or "")
            current = new_text
            final_version += 1
            logger.info("Self-Refine rewrite done: v{}", final_version)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Self-Refine rewrite fail: {}: {}",
                           exc.__class__.__name__, str(exc)[:80])
            break

        new_scores = _ds_evaluate(topic, materials, current, today)
        regressed = any(
            new_scores.get(d, {}).get("score", 0) < prev
            for d, prev in prev_snap.items() if prev >= 4
        )
        if regressed:
            logger.warning("Self-Refine rewrite regressed, reverting")
            current = prev_script
            final_version -= 1

    meta = {"final_version": final_version, "checks": check_meta,
            "improved": current != script_text,
            "passed": any(c.get("all_pass") for c in check_meta)}
    return current, meta


# ↑↑↑ Self-Refine 函数结束 ↑↑↑


# ── 事实卡抽取层：生成端事实契约 ──
#
# 一次性生成里"能用什么事实"是隐式的（模型自己从几千字原文里捞），改为显式两段：
#   ① 抽事实卡（只搬运不改写）+ 确定性回验（数字必须命中素材、字面重合度达标）
#   ② 按卡生成（卡=事实白名单+覆盖要求），Self-Refine 改写同样只认卡
# 评审仍对素材全文（faith 分数语义不变），卡只是生成端约束。

EXTRACT_PROVIDER = "zhipu"
EXTRACT_MODEL = SCRIPT_MODEL

_EXTRACT_PROMPT = """你是新闻编辑。从新闻素材中抽取「事实卡」，供撰稿人后续写稿使用。

规则：
1. 只搬运素材中明确出现的信息，禁止推理、补充、换算数字——卡上的每个字都必须能在素材中找到依据；
2. 每卡必须【完整保留】时间与语气限定词（如「到2030年」「目标」「预计」「将」「计划」「已达」）
   ——【严禁】把未来目标/规划抽成已实现事实，严禁丢掉「到XX年」这类时间限定；
3. 每卡一个原子事实（一个数字/一个事件/一个表态/一个时间节点）；
4. 每卡标注来源素材编号（素材块以【素材N】开头），并附 quote：素材中支持该事实的
   【连续原文片段】（不少于12字，逐字复制，不得改写）；
5. 覆盖全部素材的关键事实，宁多勿少；
6. 只输出 JSON：{{"cards": [{{"src": 1, "fact": "原子事实", "quote": "原文片段"}}]}}

素材：
{materials}"""


def _fact_verifiable(fact: str, quote: str, materials: str) -> bool:
    """确定性回验：引句必须是素材的逐字子串，卡上数字必须真在素材中（数字边界安全）。

    抽取器自己的幻觉（卡上出现素材没有的事实）比漏抽更糟，宁可错杀。
    """
    if len(quote) < 12 or quote not in materials:
        return False
    for num in re.findall(r"\d+(?:\.\d+)?", fact):
        if not re.search(rf"(?<!\d){re.escape(num)}(?!\d)", materials):
            return False
    return True


def _extract_facts(topic: str, materials: str) -> tuple[str, int, int]:
    """素材 → 事实卡块。返回 (卡块, 有效卡数, 回验丢弃数)。

    LLM 抽取失败或 0 卡通过回验时返回空块，调用方回退素材原文（管道不因此中断）。
    """
    try:
        resp = gateway.chat(
            EXTRACT_PROVIDER, model=EXTRACT_MODEL,
            messages=[{"role": "user", "content": _EXTRACT_PROMPT.format(materials=materials)}],
            response_format={"type": "json_object"},
            max_tokens=4000, temperature=0.1,
            extra_body=_THINKING_OFF,
            langfuse_meta={"podcast": True, "stage": "fact_extract", "topic": topic[:50]},
        )
        data = _llm_json(resp.choices[0].message.content or "")
        raw_cards = data.get("cards") if isinstance(data.get("cards"), list) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("fact extract fail: {}: {}", exc.__class__.__name__, str(exc)[:80])
        return "", 0, 0

    cards: list[str] = []
    dropped = 0
    for c in raw_cards:
        if not isinstance(c, dict):
            continue
        fact = str(c.get("fact", "")).strip()
        quote = str(c.get("quote", "")).strip()
        if len(fact) < 6 or not _fact_verifiable(fact, quote, materials):
            dropped += 1
            continue
        cards.append(f"卡{len(cards) + 1}（素材{c.get('src', '?')}）：{fact}")

    if not cards:
        logger.warning("fact extract: 0 卡通过回验（丢弃 {}），回退素材原文", dropped)
        return "", 0, dropped

    need = max(len(cards) - 2, round(len(cards) * 0.7))
    block = (
        f"【事实卡（共 {len(cards)} 张）】脚本中的所有事实性内容必须出自下列卡片，"
        f"卡片之外的事实一律不得写入（含推算：不得用卡片数字做四则运算派生新数字）；"
        f"素材背景语境可在开场/过渡中自然提及。\n"
        f"【时态纪律】卡片中带「到XX年/目标/将/计划/预计」的是未来规划，"
        f"必须以未来时态表述，严禁写成已达成；只有带「已达/截至/今日」的才是现状。\n"
        f"覆盖要求：尽可能多地把卡片内容自然讲进脚本（目标 {need} 张左右）；"
        f"无法自然容纳的不硬塞，严禁为覆盖卡片而改变事实的时间属性或确定性。\n"
        f"卡片编号仅用于内部溯源，【禁止】把「（卡N）」等标记写进脚本正文。\n\n"
        + "\n".join(cards)
    )
    logger.info("fact extract: {} 张卡（回验丢弃 {}）", len(cards), dropped)
    return block, len(cards), dropped


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


def _group_events(category: str, rows: list) -> list[dict]:
    """宏观题 → 把类目近期文章按【新闻事件】分组（索引锚定的机械聚类）。

    不让模型"提炼子话题"（会锚定单一热点事件，实测约半数概率产出同事件×3），
    只让它做纯分组——输出组名+成员编号，模型无发挥空间。
    返回 [{"name": 组名, "query": 代表标题}...]（3~5 组，query 供精确检索）。
    """
    titles = "\n".join(f"{i + 1}. {t[:50]}" for i, (t, _s) in enumerate(rows))
    prompt = (
        f"你是新闻编辑。下面是 {category} 类目近期的 {len(rows)} 条新闻（带编号）。\n\n"
        f"{titles}\n\n"
        f"任务：把这些新闻按【新闻事件】分组——同一事件的多篇报道归为一组，"
        f"不同事件不能混入同组。输出 3~5 个组，每组给出一个事件组名，"
        f"并列出该组所有成员的编号。\n"
        f'只输出 JSON：{{"groups": [{{"name": "事件组名", "items": [1, 4, 5]}}]}}'
    )
    try:
        resp = gateway.chat(
            "zhipu", model="glm-4.5-air",
            messages=[{"role": "user", "content": prompt + "\n\n直接输出 JSON，不要解释。"}],
            response_format={"type": "json_object"},
            max_tokens=1200, temperature=0.2,
            extra_body=_THINKING_OFF,
        )
        raw = (resp.choices[0].message.content or "").strip()
        cl = re.sub(r"```json\s*|```\s*$", "", raw, flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", cl, re.DOTALL)
        data = json.loads(m.group()) if m else {}
        groups = data.get("groups") if isinstance(data.get("groups"), list) else []
        out: list[dict] = []
        used: set[int] = set()
        for g in groups:
            if not isinstance(g, dict):
                continue
            name = str(g.get("name", "")).strip()
            items = [i for i in g.get("items", []) if isinstance(i, int) and 1 <= i <= len(rows)]
            if not name or not items or used.intersection(items):
                continue
            used.update(items)
            first_title = rows[items[0] - 1][0].strip()
            out.append({"name": name, "query": first_title})
            if len(out) >= 5:
                break
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("事件分组失败: {}", str(exc)[:80])
        return []


def _search_materials_macro(topic: str, category: str, top_k: int) -> list[dict]:
    """宏观话题检索：类目近期文章 → 子题分解 → 逐子题精确检索（0.25 阀门）→ 合并去重。

    宽泛查询在 dense/sparse 上都是均匀弱匹配（rerank 实测 ~0.18 平带），无法排序；
    正解是按子话题逐个精确检索——每个子题都是具体问题，呈现断崖形态精准命中源文章。
    """
    cutoff_ts = int(time.time()) - SEARCH_DAYS * 86400
    cutoff = datetime.fromtimestamp(cutoff_ts, tz=UTC)
    with SessionLocal() as db:
        rows = db.execute(
            select(Article.title, Article.summary, Article.publish_time)
            .where(
                Article.deleted_at.is_(None),
                Article.category == category,
                Article.publish_time.is_not(None),
                Article.publish_time >= cutoff,
                Article.summary.is_not(None),
            )
            .order_by(Article.publish_time.desc())
            .limit(300)
        ).fetchall()
    if not rows:
        return []
    # ① 事件级去重：新浪滚动流同一事件会被多个子源反复推送（实测一个事件可占
    # top-50 的多个变体位）——标题 simhash 折叠
    # ② 按天分层采样：每天只取最新 3 条、跨 7 天——纯 recency top-N 会被
    # "当天最热事件"锚定（实测 3 个子题全是同一事件变体），分层后样本天然多样
    sampled: list[tuple[str, str]] = []
    title_hashes: list[int] = []
    day_count: dict[str, int] = {}
    for t, s, pt in rows:
        day = pt.strftime("%m-%d")
        if day_count.get(day, 0) >= 3:
            continue
        h = simhash_svc.simhash(t)
        if any(simhash_svc.is_similar(h, prev) for prev in title_hashes):
            continue
        title_hashes.append(h)
        day_count[day] = day_count.get(day, 0) + 1
        sampled.append((t, s))
        if len(sampled) >= 30:
            break
    groups = _group_events(category, sampled)
    if not groups:
        return []
    logger.info("宏观题 [{}] 类目 {} 事件组: {}", topic[:30], category,
                [g["name"] for g in groups])
    cutoff_ts = int(time.time()) - SEARCH_DAYS * 86400
    merged: dict[int, dict[str, Any]] = {}
    for g in groups:
        st = g["query"]
        try:
            hyde = _hyde_doc(st)
            hits = vector_svc.hybrid_search(
                st, top_k=8, publish_after_ts=cutoff_ts,
                extra_queries=[hyde] if hyde else None,
            )
            hits = [h for h in hits if h["score"] >= MIN_SCORE]
            if not hits:
                continue
            rr = vector_svc.rerank(st, hits)
            rr.sort(
                key=lambda h: (h.get("rerank_score") or 0, h["publish_ts"]), reverse=True
            )
            strong = [h for h in rr if (h.get("rerank_score") or 0) >= RERANK_MIN_SCORE][:2]
            for h in strong:
                cur = merged.get(h["article_id"])
                if cur is None or (h.get("rerank_score") or 0) > (cur.get("rerank_score") or 0):
                    merged[h["article_id"]] = h
        except Exception as exc:  # noqa: BLE001
            logger.warning("子题检索失败 [{}]: {}", st[:30], str(exc)[:60])
        time.sleep(0.2)
    out = sorted(
        merged.values(),
        key=lambda h: (h.get("rerank_score") or 0, h["publish_ts"]), reverse=True
    )
    logger.info("宏观检索：{} 个事件组合并去重后 {} 篇", len(groups), len(out))
    return out[: top_k + 2]


def search_materials_routed(
    topic: str, top_k: int, intent_in: TopicIntent | None = None
) -> tuple[list[dict[str, Any]], TopicIntent, str]:
    """带宏观/具体路由的检索入口（生成与评测共用）。

    detect_macro 判宏观 → 类目子题分解管道；判具体（或判断失败，None 安全放行）
    → 精确检索管道。返回 (hits, intent, route)。
    """
    macro_cat = detect_macro(topic)
    if macro_cat:
        hits = _search_materials_macro(topic, macro_cat, top_k)
        if hits:
            intent = understand_topic(topic)
            return hits, intent, f"macro:{macro_cat}"
        logger.warning("宏观检索 0 命中，回退精确检索管道")
    hits, intent = _search_materials(topic, top_k, intent=intent_in)
    return hits, intent, "specific"


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
    # rerank 阀门：rerank 分数跨话题不可校准（同分数在不同话题含义相反，
    # 阀门实验两轮验证绝对阈值 0.3/0.4 会误杀核心文），故 0.25 仅作垃圾地板——
    # 低于此分视为类目级沾边直接丢弃；全部低于时保底 top1（素材下限恒为 1，
    # 单篇素材由 _check_material_relevance 门禁与 partial 提醒机制兜底）
    relevant = [h for h in reranked if (h.get("rerank_score") or 0) >= RERANK_MIN_SCORE]
    if not relevant:
        relevant = reranked[:1]
        logger.warning("rerank 全部低于阀门 {}，保底 top1", RERANK_MIN_SCORE)
    return relevant[: top_k + 2], intent


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
    # ── 宏观/具体路由：宏观题走类目子题分解，具体题走精确检索（两管道共享下游）──
    hits, intent, route = search_materials_routed(
        topic_prompt, plan["top_k"], intent_in=intent_in
    )
    logger.info("检索路由 [{}]: 素材 {} 篇", route, len(hits))
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
    # 事实卡层：生成端事实契约（评审仍对 materials 全文）
    cards_block, n_cards, n_dropped = _extract_facts(topic_prompt, materials)
    gen_materials = cards_block or materials
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
        "materials": gen_materials,
        "podcast_title": podcast_title or topic_prompt[:20],
        "host_name": names[0] if names else "新闻主播",
        "host_a_name": names[0] if names else "主持人A",
        "host_b_name": names[1] if len(names) > 1 else "主持人B",
    }
    date_block = (
        f"【当前日期（硬信息）】{_today_str()}——脚本中所有日期表述"
        "（今天/昨日/近日的具体日期）必须与此一致，禁止自行编造日期。\n"
    )
    if mode == "single":
        prompt = date_block + template_block + SINGLE_PROMPT.format(
            script_prompt=script_prompt,
            words_max=plan["words"][1],
            seg_min=plan["segs"][0],
            seg_max=plan["segs"][1],
            **common,
        )
    else:
        prompt = date_block + template_block + DUAL_PROMPT.format(
            script_prompt_a=script_prompt_a,
            script_prompt_b=script_prompt_b,
            words_max=plan["words"][1],
            turns_min=plan["turns"][0],
            turns_max=plan["turns"][1],
            **common,
        )

    last_err: Exception | None = None
    words_max = plan["words"][1]
    for attempt in range(2):
        try:
            resp = gateway.chat(
                SCRIPT_PROVIDER,
                model=SCRIPT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=SCRIPT_MAX_TOKENS,
                temperature=0.7,
                extra_body=_THINKING_OFF,
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
            logger.info("script ok: {} 段 {} 字（上限 {}）", len(segments), total_chars,
                        words_max)

            # Self-Refine 质量循环：仅单人口播启用（双人不做，保持原有流程）。
            # 评审链路故障不阻断出稿：refine 失败时保留 v1，错误记入 refine meta。
            refine_meta: dict | None = None
            if mode == "single":
                script_text = "\n".join(s_["text"] for s_ in segments)
                try:
                    refined_text, refine_meta = _self_refine(
                        topic_prompt, materials, script_text, _today_str(),
                        rewrite_evidence=gen_materials, cards=cards_block,
                    )
                    if refined_text != script_text:
                        refined_segs = [
                            {"text": ln.strip()}
                            for ln in refined_text.splitlines() if ln.strip()
                        ]
                        if len(refined_segs) >= 3:
                            segments = refined_segs
                            logger.info("Self-Refine 改写完成（v{}）", refine_meta["final_version"])
                        else:
                            refine_meta["improved"] = False
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Self-Refine skipped: {}: {}",
                                   exc.__class__.__name__, str(exc)[:80])
                    refine_meta = {"final_version": 1, "checks": [], "improved": False,
                                   "error": f"{exc.__class__.__name__}: {str(exc)[:80]}"}

            return {"segments": segments, "materials": materials_detail,
                    "materials_text": materials, "fact_cards": {
                        "n": n_cards, "dropped": n_dropped, "text": cards_block,
                    }, "intent": intent.to_dict(),
                    "refine": refine_meta}
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("script attempt fail: {}: {}", exc.__class__.__name__, str(exc)[:80])
    raise ScriptError(f"脚本生成失败：{last_err}")


def _validate(data: dict | list, mode: str) -> list[dict[str, Any]]:
    if isinstance(data, list):  # 部分模型返回裸数组（无 segments 包装）
        data = {"segments": data}
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
