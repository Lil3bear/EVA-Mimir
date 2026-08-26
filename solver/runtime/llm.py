"""Small reliability wrapper for OpenAI-compatible completion calls."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError
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
        # DeepSeek V4 thinking rejects tool_choice. reasoning_effort 必须是
        # 顶层字段（放进 extra_body 时 tokenhub 不生效，导致每轮都按
        # 默认 high 读满 reasoning）。
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if thinking_enabled else "disabled"},
        }
        if thinking_enabled:
            kwargs["reasoning_effort"] = reasoning_effort
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


def _ensure_request_active(
    deadline: float,
    cancel_event: threading.Event | None,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("LLM request cancelled")
    if deadline and time.time() >= deadline:
        raise TimeoutError("LLM request exceeded benchmark deadline")


def _acquire_llm_slot(
    deadline: float,
    cancel_event: threading.Event | None,
) -> None:
    """Acquire the global slot without waiting past cancellation/deadline."""
    while True:
        _ensure_request_active(deadline, cancel_event)
        if deadline:
            remaining = max(0.0, deadline - time.time())
            wait = min(remaining, 0.2) if cancel_event is not None else remaining
            acquired = _LLM_SEMAPHORE.acquire(timeout=wait)
        elif cancel_event is not None:
            acquired = _LLM_SEMAPHORE.acquire(timeout=0.2)
        else:
            _LLM_SEMAPHORE.acquire()
            acquired = True
        if acquired:
            try:
                _ensure_request_active(deadline, cancel_event)
            except Exception:
                _LLM_SEMAPHORE.release()
                raise
            return


def create_with_retry(
    create: Callable[..., Any],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    deadline: float = 0.0,
    cancel_event: threading.Event | None = None,
    **kwargs: Any,
) -> Any:
    """Call a completion endpoint with bounded concurrency and retries.

    ``create`` is invoked once per attempt, after acquiring the process-wide
    slot.  Callers that need a transport timeout derived from the remaining
    budget should pass a small wrapper which computes that timeout when it is
    invoked rather than binding the client before entering this function.
    """
    attempts = max(1, max_attempts)
    request_snapshot = copy.deepcopy(kwargs)
    deadline = float(deadline or 0.0)
    for attempt in range(1, attempts + 1):
        _acquire_llm_slot(deadline, cancel_event)
        try:
            return create(**copy.deepcopy(request_snapshot))
        except Exception as exc:
            retryable = isinstance(exc, _RETRYABLE_ERRORS) or (
                isinstance(exc, APIStatusError) and exc.status_code >= 500
            )
            if not retryable or attempt == attempts:
                raise
            delay = max(0.0, min(base_delay * (2 ** (attempt - 1)), 8.0))
            if deadline:
                delay = min(delay, max(0.0, deadline - time.time()))
            if on_retry:
                on_retry(attempt, exc, delay)
        finally:
            _LLM_SEMAPHORE.release()

        _ensure_request_active(deadline, cancel_event)
        if cancel_event is not None:
            if cancel_event.wait(delay):
                raise CancelledError("LLM request cancelled during retry backoff")
        else:
            sleep(delay)
        _ensure_request_active(deadline, cancel_event)

    raise RuntimeError("unreachable")
