from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置：从 backend/.env 读取，字段与 .env.example 一一对应。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    app_name: str = "news-assistant"
    env: str = "dev"  # dev / prod
    secret_key: str = "dev-secret-change-me"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]

    # 基础设施
    database_url: str = "postgresql+psycopg://news:news@localhost:5432/news"
    redis_url: str = "redis://localhost:6379/0"

    # LLM providers（全部走 OpenAI 兼容协议，统一网关使用）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimaxi.com/v1"

    # 短信（阿里云 号码认证服务 PNVS 短信认证）
    sms_provider: str = "mock"  # mock | aliyun
    sms_aliyun_ak: str = ""
    sms_aliyun_secret: str = ""
    sms_sign_name: str = ""
    sms_template_code: str = ""

    # JWT（认证模块）
    jwt_access_ttl_minutes: int = 120  # access token 有效期 2h
    jwt_refresh_ttl_days: int = 14  # refresh token 有效期 14d（轮换）

    # Langfuse（LLM 观测，自托管 v4）
    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # 向量库（M1 后期接入）
    milvus_uri: str = ""
    milvus_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
