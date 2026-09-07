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

    # GitHub OAuth 登录（留空 = 功能关闭，/auth/github/login 返回未配置）
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = ""  # 需与 OAuth App 注册的回调完全一致，如 https://host/login/github

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

    # JWT（认证模块）—— 7 天免登录：access 直接 7 天（停用/启用靠 disabled_at 踢旧 token）；
    # refresh 7 天滑动（rotate 从当前时间重算，活跃即续期）
    jwt_access_ttl_minutes: int = 7 * 24 * 60  # access token 有效期 7d
    jwt_refresh_ttl_days: int = 7  # refresh token 滑动有效期 7d（轮换）
    # Cookie Secure 标记：仅 HTTPS 部署置 true（明文 http 下浏览器拒存 Secure Cookie，登录态会丢失）
    cookie_secure: bool = False

    # Langfuse（LLM 观测，自托管 v4）
    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # 向量库（M1 后期接入）
    milvus_uri: str = ""
    milvus_token: str = ""

    # 播客合成
    ffmpeg_path: str = "ffmpeg"  # Windows 本地开发填 backend/bin/ffmpeg.exe 绝对路径
    media_dir: str = "media"  # 本地暂存根（相对 backend/），生成中分段/拼接用
    podcast_tts_enabled: bool = True  # 调试脚本时置 false：只生成脚本不做 TTS/拼接

    # 阿里云 OSS（播客音频终存；AK 为空时自动回退本地 /media）
    oss_access_key_id: str = ""
    oss_secret: str = ""
    oss_bucket: str = "icarus1"
    oss_endpoint: str = "https://oss-cn-hangzhou.aliyuncs.com"
    oss_prefix: str = "news/podcasts"  # 对象 key 前缀（与 demo 项目共用 bucket，目录隔离）


@lru_cache
def get_settings() -> Settings:
    return Settings()
