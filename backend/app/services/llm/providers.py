"""LLM provider 注册表：所有厂商统一走 OpenAI 兼容协议，新增厂商只加一处配置。"""

from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    default_model: str


def get_providers() -> dict[str, ProviderConfig]:
    s = get_settings()
    return {
        "deepseek": ProviderConfig(
            "deepseek", s.deepseek_base_url, s.deepseek_api_key, "deepseek-v4-flash"
        ),
        "zhipu": ProviderConfig("zhipu", s.zhipu_base_url, s.zhipu_api_key, "glm-4-flash"),
        "dashscope": ProviderConfig(
            "dashscope", s.dashscope_base_url, s.dashscope_api_key, "qwen-plus"
        ),
        "minimax": ProviderConfig(
            "minimax", s.minimax_base_url, s.minimax_api_key, "MiniMax-Text-01"
        ),
    }
