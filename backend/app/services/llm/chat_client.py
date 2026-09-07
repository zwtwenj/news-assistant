"""聊天专用 DeepSeek 流式客户端（stream + tools）。

网关（gateway）不支持流式与 function calling，聊天链路独立直连；
模型与网关注册一致（deepseek-v4-flash），凭据复用。
"""

from functools import lru_cache
from typing import Any

from loguru import logger
from openai import OpenAI

from app.core.config import get_settings

MODEL = "deepseek-v4-flash"


@lru_cache
def _client() -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=s.deepseek_base_url, api_key=s.deepseek_api_key, timeout=90)


def stream_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.5,
) -> Any:
    """流式对话。yield 逐 chunk；tools 传入时模型可发起 tool_calls
    （累积分片由调用方处理，本函数只透传 stream 对象）。"""
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": temperature,
        "max_tokens": 4000,
    }
    if tools:
        kwargs["tools"] = tools
    logger.info(
        "chat stream start model={} msgs={} tools={}",
        MODEL, len(messages), len(tools or []),
    )
    return _client().chat.completions.create(**kwargs)
