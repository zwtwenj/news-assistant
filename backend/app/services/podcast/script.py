"""播客脚本生成：话题提示词 → Milvus 检索素材 → LLM 写脚本（时长驱动参数）。

时长规则（一等参数）：
- 素材条数：上限按时长档位（短1/中3/长5），下限 1——选了长但只检索到 1 条，
  也照样生成（对已有素材深聊到底），只有 0 条才报"素材不足"；
- 脚本长度：按中文口播语速 ~250 字/分钟换算字数/轮数区间。
"""

import json
import time
from typing import Any

from loguru import logger

from app.services.llm.gateway import gateway
from app.services.news import vector as vector_svc
from app.services.podcast import voices as voices_svc

MODEL = "deepseek-v4-flash"
SEARCH_DAYS = 7
MIN_SCORE = 0.25  # 检索分数下限：全低于此 = 库里没有相关内容

SINGLE_PROMPT = """你是资深播客撰稿人。为一期约 {minutes} 分钟的单人播客写口播稿。

【风格与写法要求（脚本提示词）】
{script_prompt}

【本期主题（话题提示词）】
{topic_prompt}

【参考新闻素材】（内容必须以此为准，不得编造事实；若素材少于预期，就对已有素材深入展开，不要硬凑）
{materials}

要求：
1. 独白口播稿，口语化、有节奏感，不用书面语和列表；
2. 全长 {words_min}~{words_max} 字（语速约 250 字/分钟），切分为 {seg_min}~{seg_max} 个自然段落；
3. 只输出 JSON：{{"segments": [{{"text": "段落内容"}}]}}"""

DUAL_PROMPT = """你是资深播客撰稿人。为一期约 {minutes} 分钟的双人对谈播客写对话稿。

【主持人 A 人设与写法（脚本提示词A）】
{script_prompt_a}

【主持人 B 人设与写法（脚本提示词B）】
{script_prompt_b}

【本期主题（话题提示词）】
{topic_prompt}

【参考新闻素材】（内容必须以此为准，不得编造事实；素材少于预期就深聊已有内容，不要硬凑）
{materials}

要求：
1. A/B 对话形式，自然口语、有来有回、可互相接话，不用书面语；
2. 共 {turns_min}~{turns_max} 轮对话，每轮 1~3 句话，总量约 {minutes} 分钟（语速约 250 字/分钟）；
3. speaker 只能是 "A" 或 "B"；
4. 只输出 JSON：{{"segments": [{{"speaker": "A", "text": "..."}}]}}"""


def _plan(target_minutes: int) -> dict[str, Any]:
    """时长 → 检索上限与脚本长度区间。素材下限恒为 1（不足则深聊）。"""
    if target_minutes <= 2:  # 短（1~2 分钟）
        return {"top_k": 1, "words": (300, 500), "segs": (3, 5), "turns": (6, 10)}
    if target_minutes <= 5:  # 中（3~5 分钟）
        return {"top_k": 3, "words": (700, 1100), "segs": (5, 9), "turns": (12, 18)}
    # 长（5~8 分钟）
    return {"top_k": 5, "words": (1200, 1800), "segs": (8, 14), "turns": (18, 28)}


def _search_materials(topic: str, top_k: int) -> list[dict[str, Any]]:
    """检索素材：近 7 天窗口，新鲜度优先。

    召回放大一倍 → 分数阈值过滤 → 按发布时间倒序取 top_k：
    语义相关性由阈值保证，"最近天气"优先命中今天/昨天而不是五天前。
    """
    week_ago = int(time.time()) - SEARCH_DAYS * 86400
    hits = vector_svc.search(topic, top_k=top_k * 2, publish_after_ts=week_ago)
    qualified = [h for h in hits if h["score"] >= MIN_SCORE]
    qualified.sort(key=lambda h: h["publish_ts"], reverse=True)
    return qualified[:top_k]


def generate_script(
    mode: str,
    topic_prompt: str,
    script_prompt: str | None,
    script_prompt_a: str | None,
    script_prompt_b: str | None,
    target_minutes: int = 4,
) -> list[dict[str, Any]]:
    """返回 [{speaker?, text}]；素材为 0 或输出非法时抛 ScriptError（任务层计失败）。"""
    plan = _plan(target_minutes)
    # 上限按档位、下限 1：检索内部已做阈值过滤与新鲜度排序，剩几条用几条（0 条才拒绝）
    hits = _search_materials(topic_prompt, plan["top_k"])
    if not hits:
        raise ScriptError("素材不足，无法为你生成播客：近期新闻库中没有与话题相关的内容")

    materials = "\n".join(
        f"- 《{h['title']}》（{h.get('tags') or []}）：摘要见原文" for h in hits
    )
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
    for _ in range(2):  # 空输出/非法 JSON 快速重试（复用 analyzer 经验）
        try:
            resp = gateway.chat(
                "deepseek",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=3000,
                temperature=0.7,
                langfuse_meta={
                    "podcast": True, "mode": mode,
                    "topic": topic_prompt[:50], "target_minutes": target_minutes,
                    "materials": len(hits),
                },
            )
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                raise ValueError("LLM 返回空内容")
            segments = _validate(json.loads(raw), mode)
            return segments
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
