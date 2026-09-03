"""LLM 打标与摘要（prompt 迁自 demo，调用统一走 LLM 网关）+ 质量评分（规则分全量 / judge 采样）。"""

import json
import random
from typing import Any

from loguru import logger

from app.services.llm.gateway import gateway

CATEGORIES = [
    "娱乐", "体育", "科技", "财经", "社会", "国际",
    "军事", "教育", "健康", "汽车", "游戏", "其他",
]

PROMPT = """你是新闻编辑。对下面的新闻做分类打标和摘要。

要求：
1. summary：50~100 字的客观摘要，不评论；
2. tags：从以下分类中选择 1~3 个最贴切的：{categories}；
3. 只输出 JSON，不要任何其他文字，格式：{{"summary": "...", "tags": ["...", "..."]}}

标题：{title}
正文：{content}"""

JUDGE_PROMPT = """你是内容质量评审员。根据新闻正文评估打标结果的质量。

评分维度（1~5 整数，5 最好）：
1. faithfulness：摘要中的信息是否都能在正文中找到依据（杜撰/偏离扣分）；
2. tag_accuracy：分类标签是否准确贴切。

只输出 JSON：{{"faithfulness": n, "tag_accuracy": n, "reason": "20字内理由"}}

标题：{title}
摘要：{summary}
标签：{tags}
正文：{content}"""


def analyze(
    title: str, content: str, langfuse_meta: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """返回 {"summary": str, "tags": [str]}；失败返回 None（由任务层计 attempts）。

    DeepSeek json_object 模式偶发返回空 content（实测约 1/70），内部快速重试一次。
    """
    text = PROMPT.format(categories="/".join(CATEGORIES), title=title, content=content[:4000])
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            resp = gateway.chat(
                "deepseek",
                messages=[{"role": "user", "content": text}],
                response_format={"type": "json_object"},
                max_tokens=800,
                temperature=0.2,
                langfuse_meta=langfuse_meta,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                raise ValueError("LLM 返回空内容（json_object 偶发）")
            data = json.loads(raw)
            summary = str(data.get("summary", "")).strip()
            tags = [str(t) for t in data.get("tags", []) if t in CATEGORIES]
            if not summary or not tags:
                raise ValueError(f"输出字段缺失: summary={'有' if summary else '无'}, tags={tags}")
            return {"summary": summary, "tags": tags[:3]}
        except Exception as exc:  # noqa: BLE001  空输出/JSON 非法/字段缺失/网关失败
            last_error = exc
            logger.warning(
                "analyze attempt fail title={} err={}: {}",
                title[:30], exc.__class__.__name__, str(exc)[:80],
            )
    logger.opt(exception=True).warning(
        "analyze 最终失败 title={} last_error={}", title[:50], last_error
    )
    return None


# ---------- 质量评分（Langfuse score，plan §8） ----------

def rule_scores(summary: str, content: str) -> dict[str, float]:
    """程序化规则分（全量、零成本）：
    - summary_length：50~100 字要求，放宽到 40~150；
    - originality：20 字滑窗 ≥70% 原样出现在正文中 → 判定"复读正文"。
    """
    scores: dict[str, float] = {}
    scores["summary_length"] = 1.0 if 40 <= len(summary) <= 150 else 0.0
    if len(summary) >= 20:
        windows = [summary[i : i + 20] for i in range(0, len(summary) - 19, 10)]
        hit = sum(1 for w in windows if w in content)
        scores["originality"] = 0.0 if hit / len(windows) >= 0.7 else 1.0
    return scores


def judge(title: str, content: str, summary: str, tags: list[str]) -> dict[str, Any] | None:
    """LLM-as-judge（采样调用，走智谱 glm-4-flash 控成本）。"""
    text = JUDGE_PROMPT.format(
        title=title, summary=summary, tags="/".join(tags), content=content[:2000]
    )
    try:
        resp = gateway.chat(
            "zhipu",
            messages=[{"role": "user", "content": text}],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0.0,
            langfuse_meta={"judge": True, "article_title": title[:50]},
        )
        data = json.loads(resp.choices[0].message.content or "")
        f, t = int(data.get("faithfulness", 0)), int(data.get("tag_accuracy", 0))
        if not (1 <= f <= 5 and 1 <= t <= 5):
            raise ValueError(f"judge 分数越界: faithfulness={f}, tag_accuracy={t}")
        return {"faithfulness": f, "tag_accuracy": t, "reason": str(data.get("reason", ""))[:100]}
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("judge fail title={}", title[:50])
        return None


def should_judge(rate: float = 0.2) -> bool:
    return random.random() < rate  # noqa: S311
