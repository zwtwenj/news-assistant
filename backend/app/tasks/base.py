from celery import Task


class BaseTask(Task):
    """异步任务基类：业务任务统一从这里派生（plan §5）。

    约定：
    - acks_late + 指数退避重试（max 3），与 demo 的 attempts 设计一致；
    - 幂等由子任务自行保证（按文章 ID / 任务 ID 去重）；
    - on_failure 为死信告警的唯一挂点。
    """

    acks_late = True
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 3

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # TODO(M1): 死信告警（Sentry / 飞书 webhook）
        super().on_failure(exc, task_id, args, kwargs, einfo)
