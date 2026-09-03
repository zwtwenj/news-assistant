"""播客脚本生成：话题提示词 → Milvus 检索素材 → LLM 写脚本（两层提示词注入）。"""

import json
from typing import Any

from loguru import logger

from app.services.llm.gateway import gateway
from app.services.news import vector as vector_svc
from app.services.podcast import voices as voices_svc

MODEL = "deepseek-v4-flash"
SEARCH_TOP_K = 6
SEARCH_DAYS = 7
MIN_SCORE = 0.25  # 检索分数下限：全低于此 = 库里没有相关内容

SINGLE_PROMPT = """你是资深播客撰稿人。为一期单人播客写口播稿。

【风格与写法要求（脚本提示词）】
{script_prompt}

【本期主题（话题提示词）】
{topic_prompt}

【参考新闻素材】（内容必须以此为准，不得编造事实）
{materials}

要求：
1. 独白口播稿，口语化、有节奏感，不用书面语和列表；
2. 全长 600~900 字，切分为 5~10 个自然段落；
3. 只输出 JSON：{{"segments": [{{"text": "段落内容"}}]}}"""

DUAL_PROMPT = """你是资深播客撰稿人。为一期双人对谈播客写对话稿。

【主持人 A 人设与写法（脚本提示词A）】
{script_prompt_a}

【主持人 B 人设与写法（脚本提示词B）】
{script_prompt_b}

【本期主题（话题提示词）】
{topic_prompt}

【参考新闻素材】（内容必须以此为准，不得编造事实）
{materials}

要求：
1. A/B 对话形式，自然口语、有来有回、可互相接话，不用书面语；
2. 共 8~14 轮对话，每轮 1~3 句话；
3. speaker 只能是 "A" 或 "B"；
4. 只输出 JSON：{{"segments": [{{"speaker": "A", "text": "..."}}]}}"""


def _search_materials(topic: str) -> list[dict[str, Any]]:
    import time

    week_ago = int(time.time()) - SEARCH_DAYS * 86400
    return vector_svc.search(topic, top_k=SEARCH_TOP_K, publish_after_ts=week_ago)


def generate_script(
    mode: str,
    topic_prompt: str,
    script_prompt: str | None,
    script_prompt_a: str | None,
    script_prompt_b: str | None,
) -> list[dict[str, Any]]:
    """返回 [{speaker?, text}]；素材不足或输出非法时抛 ScriptError（任务层计失败）。"""
    hits = _search_materials(topic_prompt)
    hits = [h for h in hits if h["score"] >= MIN_SCORE]
    if not hits:
        raise ScriptError("近期新闻库中没有与话题相关的内容，换个话题或明天再来")

    materials = "\n".join(
        f"- 《{h['title']}》（{h.get('tags') or []}）：摘要见原文" for h in hits
    )
    if mode == "single":
        prompt = SINGLE_PROMPT.format(
            script_prompt=script_prompt, topic_prompt=topic_prompt, materials=materials
        )
    else:
        prompt = DUAL_PROMPT.format(
            script_prompt_a=script_prompt_a,
            script_prompt_b=script_prompt_b,
            topic_prompt=topic_prompt,
            materials=materials,
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
                langfuse_meta={"podcast": True, "mode": mode, "topic": topic_prompt[:50]},
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
