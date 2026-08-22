"""Small reliability wrapper for OpenAI-compatible completion calls."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)


_RETRYABLE_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

DEEPSEEK_V4_CONTEXT_TOKENS = 1_000_000
DEEPSEEK_V4_MAX_OUTPUT_TOKENS = 8_192
DEEPSEEK_V4_COMPACTION_RESERVE_TOKENS = 32_768


def _llm_limit() -> int:
    try:
        return max(1, int(os.environ.get("LLM_MAX_CONCURRENCY", "4")))
    except ValueError:
        return 4


# A process-wide gate prevents 3 challenges × 2 portfolio agents from
# overwhelming the hosted gateway.  The limit is configurable for local runs.
_LLM_SEMAPHORE = threading.BoundedSemaphore(_llm_limit())


def is_deepseek_v4(model: str) -> bool:
    return model.lower().startswith("deepseek-v4")


def completion_kwargs(
    *,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str = "high",
    thinking_enabled: bool = True,
) -> dict[str, Any]:
    """Build one OpenAI-compatible request with DeepSeek V4 semantics."""
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if tools is not None:
        kwargs["tools"] = tools
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    if is_deepseek_v4(model):
        if thinking_enabled and reasoning_effort not in {"high", "max"}:
            raise ValueError("DeepSeek V4 reasoning_effort must be high or max")
        # DeepSeek V4 thinking rejects tool_choice. extra_body also works with
        # older OpenAI SDK releases that do not expose reasoning_effort yet.
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if thinking_enabled else "disabled"},
        }
        if thinking_enabled:
            kwargs["extra_body"]["reasoning_effort"] = reasoning_effort
    elif tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    return kwargs


def assistant_message_dict(message: Any) -> dict[str, Any]:
    """Serialize an assistant message for reliable multi-turn tool replay."""
    data = message.model_dump(exclude_none=True)
    extra = getattr(message, "model_extra", {}) or {}
    reasoning = getattr(message, "reasoning_content", None) or extra.get("reasoning_content")
    if reasoning:
        data["reasoning_content"] = reasoning
    if data.get("tool_calls"):
        data["content"] = data.get("content") or ""
    return data


def create_with_retry(
    create: Callable[..., Any],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> Any:
    """Call a completion endpoint, retrying only transient provider failures."""
    attempts = max(1, max_attempts)
    request_snapshot = copy.deepcopy(kwargs)
    for attempt in range(1, attempts + 1):
        try:
            with _LLM_SEMAPHORE:
                return create(**copy.deepcopy(request_snapshot))
        except Exception as exc:
            retryable = isinstance(exc, _RETRYABLE_ERRORS) or (
                isinstance(exc, APIStatusError) and exc.status_code >= 500
            )
            if not retryable or attempt == attempts:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), 8.0)
            if on_retry:
                on_retry(attempt, exc, delay)
            sleep(delay)

    raise RuntimeError("unreachable")
