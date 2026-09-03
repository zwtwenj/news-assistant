"""Langfuse 接入（自托管 v4）。

初始化后 @observe 装饰器与 get_client() 全局可用；未配置密钥时全部 no-op，
不影响业务（观测数据非关键路径，上报失败仅记日志）。

trace 结构约定（celery 任务跨进程，contextvars 不传播，采用扁平 trace + 聚合标签）：
- 阶段任务：trace name=news/{阶段}，session_id=pipeline-{yyyymmdd}
- 文章打标：trace name=analyze/article-{id}（网关 generation 独立成 trace，metadata 带 article_id）
- score：挂在文章 trace 上（规则分全量 + judge 采样）
"""

from loguru import logger

from app.core.config import get_settings

_client = None  # type: ignore[valid-type]


def init_langfuse():
    """幂等初始化，返回 Langfuse 实例或 None（未配置）。任务/应用入口调用。"""
    global _client
    if _client is not None:
        return _client
    s = get_settings()
    if not (s.langfuse_host and s.langfuse_public_key and s.langfuse_secret_key):
        logger.info("Langfuse 未配置，观测 no-op")
        return None
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host,
        )
        logger.info("Langfuse 已初始化: {}", s.langfuse_host)
        return _client
    except Exception:
        logger.opt(exception=True).warning("Langfuse 初始化失败，观测 no-op")
        return None


def get_langfuse():
    """获取已初始化的客户端；未初始化时尝试初始化，失败返回 None。"""
    return _client or init_langfuse()


def score(trace_id: str, name: str, value: float, *, comment: str = "") -> None:
    """安全打分：Langfuse 不可用/上报失败不影响业务。"""
    lf = get_langfuse()
    if lf is None or not trace_id:
        return
    try:
        lf.create_score(trace_id=trace_id, name=name, value=value, comment=comment or None)
    except Exception:
        logger.opt(exception=True).warning("langfuse score fail name={} trace={}", name, trace_id)
