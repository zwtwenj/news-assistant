"""语义质检（质量门禁第③层）：打标前独立调用，glm-4-flash（成本趋零）。

与打标解耦（用户决策）：单一职责 prompt 稳定性最高；bad 直接短路不进打标，
省下的打标输出 token 远大于检测的输入 token。
"""

import json
from typing import Any

from loguru import logger

from app.services.llm.gateway import gateway

PROMPT = """判断下面这段从新闻页面提取的文本是否为"完整可读的新闻正文"。这是质量把关任务，请严格判定。

判 bad 的典型特征（出现任意一条即为 bad）：
- 页面导航/菜单/页脚文字（如"新闻频道""责任编辑""扫一扫""返回顶部"成片出现）
- 只有标题、来源、日期的堆砌，没有叙述性正文
- 零散短语逐行拼接，读不成连贯的新闻叙述
- 乱码、广告、与新闻无关的内容

判 good 的唯一标准：存在能连续读懂的新闻叙述文字（讲清一件或几件事），长短不限。

只输出 JSON：{{"verdict": "good 或 bad", "reason": "10字内理由"}}

标题：{title}
文本：{content}"""


def check_semantic(title: str, content: str) -> str | None:
    """返回 good/bad；调用失败返回 None（放行交由后续门禁，不阻断流水线）。"""
    text = PROMPT.format(title=title, content=content[:1500])
    for _ in range(2):  # 空输出快速重试一次
        try:
            resp = gateway.chat(
                "zhipu",  # glm-4-flash 免费档
                messages=[{"role": "user", "content": text}],
                response_format={"type": "json_object"},
                max_tokens=50,
                temperature=0.0,
                langfuse_meta={"semantic_check": True},
            )
            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                raise ValueError("空输出")
            verdict = str(json.loads(raw).get("verdict", "")).lower()
            if verdict in ("good", "bad"):
                return verdict
            raise ValueError(f"非法 verdict: {verdict}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("semantic_check fail: {}: {}", exc.__class__.__name__, str(exc)[:60])
    return None


def parse_verdict(resp: Any) -> str | None:  # pragma: no cover - 供测试 mock 用
    return resp
