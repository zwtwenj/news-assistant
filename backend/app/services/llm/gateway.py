"""统一 LLM 网关（plan §7）：超时/重试/failover/计量统一在这里，业务侧不直连 SDK。

Langfuse 埋点（plan §8）：每次成功的聊天调用记一条 generation（模型/延迟/token），
失败记 ERROR generation。调用方通过 langfuse_meta 附加业务上下文（article_id 等）。
"""

import time
from typing import Any

from loguru import logger

from app.services.llm.providers import ProviderConfig, get_providers
from app.services.observability.langfuse_client import get_langfuse

# 沿用 demo 经验：60s 超时 + 1 次重试（防线程池耗尽），理由见 demo app/llm.py 注释
REQUEST_TIMEOUT = 60
SDK_MAX_RETRIES = 1


class LLMGateway:
    def __init__(self, providers: dict[str, ProviderConfig] | None = None) -> None:
        self._providers = providers or get_providers()
        self._clients: dict[str, Any] = {}

    def _client(self, provider: str) -> Any:
        if provider not in self._clients:
            from openai import OpenAI  # 延迟导入：未配置密钥也能正常起服务

            cfg = self._providers[provider]
            self._clients[provider] = OpenAI(
                base_url=cfg.base_url,
                api_key=cfg.api_key,
                timeout=REQUEST_TIMEOUT,
                max_retries=SDK_MAX_RETRIES,
            )
        return self._clients[provider]

    def chat(
        self,
        provider: str,
        model: str | None = None,
        *,
        fallback: str | None = None,
        langfuse_meta: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """同步聊天补全，主 provider 失败自动降级 fallback。"""
        for name in filter(None, (provider, fallback)):
            cfg = self._providers.get(name)
            if cfg is None or not cfg.api_key:
                logger.warning("llm provider 未配置或缺少密钥: {}", name)
                continue
            use_model = model or cfg.default_model
            started = time.perf_counter()
            gen = self._start_generation(name, use_model, kwargs, langfuse_meta)
            try:
                resp = self._client(name).chat.completions.create(model=use_model, **kwargs)
                latency = time.perf_counter() - started
                self._end_generation(gen, resp, latency)
                # 把 trace_id 写回调用方的 meta dict：调用方可据此打分/补充 trace 信息
                if langfuse_meta is not None and gen is not None:
                    langfuse_meta["_trace_id"] = getattr(gen, "trace_id", None)
                logger.info(
                    "llm ok provider={} model={} latency={:.2f}s", name, use_model, latency
                )
                return resp
            except Exception as exc:  # noqa: BLE001
                self._fail_generation(gen, exc)
                logger.opt(exception=True).warning(
                    "llm fail provider={} model={}", name, use_model
                )
                continue
        raise RuntimeError(f"所有 LLM provider 均不可用: provider={provider} fallback={fallback}")

    # ---------- Langfuse generation 埋点（全部 no-op 安全） ----------

    @staticmethod
    def _start_generation(
        provider: str, model: str, kwargs: dict[str, Any], meta: dict[str, Any] | None
    ) -> Any:
        lf = get_langfuse()
        if lf is None:
            return None
        try:
            return lf.start_observation(
                name=f"chat/{provider}",
                as_type="generation",
                input=kwargs.get("messages"),
                model=model,
                metadata={**(meta or {}), "provider": provider},
            )
        except Exception:
            logger.opt(exception=True).warning("langfuse start_observation fail")
            return None

    @staticmethod
    def _end_generation(gen: Any, resp: Any, latency: float) -> None:
        if gen is None:
            return
        try:
            usage_details = LLMGateway._extract_usage(resp)
            output = None
            if getattr(resp, "choices", None):
                output = resp.choices[0].message.content
            # v4 SDK：先 update 补全输出/用量，再 end 关闭
            gen.update(output=output, usage_details=usage_details)
            gen.end()
        except Exception:
            logger.opt(exception=True).warning("langfuse end observation fail")

    @staticmethod
    def _extract_usage(resp: Any) -> dict[str, int] | None:
        """usage_details：互斥计费桶（Langfuse 按同名 key 匹配单价）。

        DeepSeek 返回 prompt_cache_hit_tokens / prompt_cache_miss_tokens：
        拆成 input（未命中，正常单价）+ input_cached_tokens（命中，缓存单价），
        两桶互斥不重复计费。无缓存字段的响应保持 input/output/total。
        """
        usage = getattr(resp, "usage", None)
        if usage is None:
            return None
        extra = getattr(usage, "model_extra", None) or {}
        hit = getattr(usage, "prompt_cache_hit_tokens", None)
        if hit is None:
            hit = extra.get("prompt_cache_hit_tokens", 0) or 0
        miss = getattr(usage, "prompt_cache_miss_tokens", None)
        if miss is None:
            miss = extra.get("prompt_cache_miss_tokens", 0) or 0
        output_tokens = usage.completion_tokens
        if hit or miss:
            return {
                "input": int(miss),
                "input_cached_tokens": int(hit),
                "output": int(output_tokens),
            }
        return {
            "input": usage.prompt_tokens,
            "output": output_tokens,
            "total": usage.total_tokens,
        }

    @staticmethod
    def _fail_generation(gen: Any, exc: Exception) -> None:
        if gen is None:
            return
        try:
            gen.update(level="ERROR", status_message=f"{exc.__class__.__name__}: {exc}"[:500])
            gen.end()
        except Exception:
            pass


gateway = LLMGateway()
